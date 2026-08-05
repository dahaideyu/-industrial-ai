#!/usr/bin/env bash
# Gitee dev 分支 -> 腾讯云自动部署。
#
# 设计成"每分钟跑一次也安全"：远端没有新提交就直接退出，什么都不做。
# 所以既可以挂 cron/systemd timer 轮询，也可以由 WebHook 触发同一个脚本。
#
# 用法：
#   ./auto-deploy.sh              # 有新提交才部署
#   ./auto-deploy.sh --force      # 不管有没有新提交都重新部署一次
#   ./auto-deploy.sh --rollback   # 回滚到上一个部署成功的版本
#
# 装成每分钟检查一次（cron）：
#   * * * * * /opt/industrial-ai/deploy/docker/scripts/auto-deploy.sh \
#       >> /data/industrial-ai/logs/auto-deploy.log 2>&1
#
# 关键行为：
#   - 用 git fetch + reset --hard 而不是 git pull：Gitee 侧是"快照式"历史，
#     万一强推过，pull 会因为非快进失败卡住，reset 不会。
#     ⚠ 这意味着服务器上的本地改动会被丢弃 —— 部署目录不要手改代码。
#   - 镜像按 commit 短 SHA 打 tag，回滚就是切回上一个 tag，不用重新构建。
#   - 不碰 postgresql / minio：compose 只重建配置变了的服务，数据库不会被重启。
#   - 起完做健康检查，不健康自动回滚到上一版本。

set -uo pipefail

REPO_DIR="${REPO_DIR:-/opt/industrial-ai}"
BRANCH="${DEPLOY_BRANCH:-dev}"
REMOTE="${DEPLOY_REMOTE:-gitee}"
APP_DATA_ROOT="${APP_DATA_ROOT:-/data/industrial-ai}"
STATE_DIR="${APP_DATA_ROOT}/deploy-state"
LOCK_FILE="/tmp/industrial-ai-deploy.lock"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:9300/api/health}"
HEALTH_RETRIES="${HEALTH_RETRIES:-30}"     # 30 次 x 5s = 最多等 150s
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.tencent.yml"
COMPOSE_PROFILES="${COMPOSE_PROFILES:---profile local-db --profile mqtt}"

# 只跑参数分析这套需要的服务。redis/minio/knb-celery-worker/repair-suggestion
# 属于知识库与维修建议功能，参数分析不依赖（device_param 模块不碰 redis/minio），
# 在 4G 小机器上不起它们能省下可观内存。
# 需要全量时：DEPLOY_SERVICES="" BUILD_SERVICES="" ./auto-deploy.sh --force
DEPLOY_SERVICES="${DEPLOY_SERVICES-industrial-ai postgresql mqtt-etl}"
# postgresql 是拉的官方镜像不用构建；跳过 knb-celery-worker(final-worker target)
# 还能省掉一个含 LibreOffice+OCR 的镜像，约 2GB 磁盘和好几分钟构建时间
BUILD_SERVICES="${BUILD_SERVICES-industrial-ai mqtt-etl}"

log() { echo "[$(date '+%F %T')] $*"; }
die() { log "错误: $*"; exit 1; }

mkdir -p "$STATE_DIR"
LAST_OK_TAG_FILE="${STATE_DIR}/last_ok_tag"

# 同一时刻只允许一个部署在跑（cron 每分钟触发，构建可能几分钟）。
# 优先用 flock；没有 flock 的环境（如 Git Bash）退回 mkdir 原子锁，
# 不能因为找不到 flock 就变成永远不部署。
LOCK_DIR="${LOCK_FILE}.d"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    log "已有部署在进行中，跳过本次"
    exit 0
  fi
else
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    # 锁目录超过 1 小时视为上次异常退出遗留，自动清理
    if [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +60 2>/dev/null)" ]; then
      log "发现过期锁，清理后继续"
      rmdir "$LOCK_DIR" 2>/dev/null && mkdir "$LOCK_DIR" 2>/dev/null || { log "锁清理失败，跳过"; exit 0; }
    else
      log "已有部署在进行中，跳过本次"
      exit 0
    fi
  fi
  trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT
fi

cd "$REPO_DIR" || die "部署目录不存在: $REPO_DIR"

MODE="${1:-}"

# ── 回滚 ──────────────────────────────────────────────────────────────────
if [ "$MODE" = "--rollback" ]; then
  [ -s "$LAST_OK_TAG_FILE" ] || die "没有可回滚的版本记录（$LAST_OK_TAG_FILE 为空）"
  PREV="$(cat "$LAST_OK_TAG_FILE")"
  log "回滚到 $PREV"
  cd "$REPO_DIR/deploy/docker" || die "找不到 deploy/docker"
  IMAGE_TAG="$PREV" docker compose $COMPOSE_FILES $COMPOSE_PROFILES up -d $DEPLOY_SERVICES
  exit $?
fi

# ── 看远端有没有新提交 ────────────────────────────────────────────────────
git fetch --quiet "$REMOTE" "$BRANCH" || die "git fetch 失败（网络/凭据）"

LOCAL_SHA="$(git rev-parse HEAD 2>/dev/null || echo none)"
REMOTE_SHA="$(git rev-parse "${REMOTE}/${BRANCH}")"

if [ "$LOCAL_SHA" = "$REMOTE_SHA" ] && [ "$MODE" != "--force" ]; then
  exit 0    # 无变化，安静退出（cron 每分钟跑，不刷日志）
fi

log "发现新版本: ${LOCAL_SHA:0:7} -> ${REMOTE_SHA:0:7}"
git reset --hard "$REMOTE_SHA" --quiet || die "git reset 失败"

NEW_TAG="$(git rev-parse --short HEAD)"
PREV_TAG="$(cat "$LAST_OK_TAG_FILE" 2>/dev/null || echo '')"

cd "$REPO_DIR/deploy/docker" || die "找不到 deploy/docker"

# 构建前始终基于本次提交的明文提示词生成加密产物；密钥从 deploy/docker/.env 读取。
log "加密提示词 ..."
python "$REPO_DIR/scripts/encrypt_prompts.py" || die "提示词加密失败，请检查 deploy/docker/.env 中的 PROMPT_ENCRYPT_KEY"

# ── 构建前的内存闸门 ──────────────────────────────────────────────────────
# 4GB 的小机器上，构建（前端 vite 实测峰值约 900MB + npm/pip 安装）可能把内存吃满，
# 触发 OOM killer —— 被杀的未必是构建进程，也可能是正在服务的 industrial-ai 容器。
# 所以宁可这次不部署，也不能把线上搞挂：可用内存不够就退出，等下一分钟再试
# （届时若有别的任务结束、内存回落，会自动继续）。
MIN_FREE_MB="${MIN_FREE_MB:-1500}"
if [ -r /proc/meminfo ]; then
  avail_mb=$(awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
  swap_mb=$(awk '/^SwapTotal:/ {print int($2/1024)}' /proc/meminfo)
  if [ -n "$avail_mb" ] && [ "$avail_mb" -lt "$MIN_FREE_MB" ]; then
    if [ "${swap_mb:-0}" -ge 2048 ]; then
      log "可用内存偏低（${avail_mb}MB < ${MIN_FREE_MB}MB），但有 ${swap_mb}MB swap 兜底，继续构建"
    else
      log "可用内存不足（${avail_mb}MB < ${MIN_FREE_MB}MB）且 swap 不足 2GB，跳过本次构建以免 OOM 影响线上服务"
      log "建议加 swap：fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile"
      exit 0
    fi
  fi
fi

# ── 构建 ──────────────────────────────────────────────────────────────────
# COMPILE_SOURCE=false：服务器部署不做 Cython 编译，构建快很多（沿用 deploy.sh 的做法）
log "构建镜像 tag=${NEW_TAG} ..."
if ! COMPILE_SOURCE=false IMAGE_TAG="$NEW_TAG" \
     docker compose $COMPOSE_FILES build $BUILD_SERVICES; then
  log "构建失败，保持当前运行版本不变"
  exit 1
fi

# ── 启动 ──────────────────────────────────────────────────────────────────
# 不用 down：compose 只会重建镜像/配置变了的服务，postgresql/minio/redis 原地不动
log "启动服务 ..."
if ! IMAGE_TAG="$NEW_TAG" docker compose $COMPOSE_FILES $COMPOSE_PROFILES up -d $DEPLOY_SERVICES; then
  log "启动失败"
  [ -n "$PREV_TAG" ] && { log "回滚到 $PREV_TAG"; IMAGE_TAG="$PREV_TAG" docker compose $COMPOSE_FILES $COMPOSE_PROFILES up -d $DEPLOY_SERVICES; }
  exit 1
fi

# ── 健康检查 ──────────────────────────────────────────────────────────────
log "健康检查 $HEALTH_URL ..."
ok=0
for i in $(seq 1 "$HEALTH_RETRIES"); do
  if curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; then
    ok=1
    log "健康检查通过（第 ${i} 次尝试）"
    break
  fi
  sleep 5
done

if [ "$ok" -ne 1 ]; then
  log "健康检查失败（等了 $((HEALTH_RETRIES * 5))s）"
  docker compose $COMPOSE_FILES logs --tail=50 industrial-ai || true
  if [ -n "$PREV_TAG" ]; then
    log "自动回滚到 $PREV_TAG"
    IMAGE_TAG="$PREV_TAG" docker compose $COMPOSE_FILES $COMPOSE_PROFILES up -d $DEPLOY_SERVICES
  else
    log "没有上一个成功版本，保持现状等人工处理"
  fi
  exit 1
fi

echo "$NEW_TAG" > "$LAST_OK_TAG_FILE"
log "部署成功: $NEW_TAG"

# 清理旧镜像，别把盘撑爆。三个 target 各一个 tag，保留最近 3 轮 = 9 个
docker images "industrial-ai*" --format '{{.Repository}}:{{.Tag}} {{.CreatedAt}}' \
  | grep -v ':latest' | sort -k2 -r | tail -n +10 \
  | awk '{print $1}' | xargs -r docker rmi 2>/dev/null || true

exit 0
