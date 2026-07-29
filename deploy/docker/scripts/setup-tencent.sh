#!/usr/bin/env bash
# 腾讯云一键部署（参数分析，不含 RAGFlow）—— 把原本 6 步手工操作合成一条命令。
#
# 用法：
#   ./setup-tencent.sh                 # 完整初始化 + 启动
#   ./setup-tencent.sh --check         # 只做体检，不改任何东西
#   ./setup-tencent.sh --no-swap       # 跳过 swap 创建
#   ./setup-tencent.sh --all-services  # 连 redis/minio/worker/维修建议一起起
#
# 可重复执行：已建过的目录/卷/swap 会跳过，不会重复创建或覆盖 .env。

set -uo pipefail

APP_DATA_ROOT="${APP_DATA_ROOT:-/data/industrial-ai}"
REPO_DIR="${REPO_DIR:-/opt/industrial-ai}"
ENV_FILE="${APP_DATA_ROOT}/config/.env"
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.tencent.yml"
PROFILES="--profile local-db --profile mqtt"
SERVICES="industrial-ai postgresql mqtt-etl"
BUILD_SERVICES="industrial-ai mqtt-etl"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:9300/api/health}"

CHECK_ONLY=0; DO_SWAP=1
for a in "$@"; do
  case "$a" in
    --check) CHECK_ONLY=1 ;;
    --no-swap) DO_SWAP=0 ;;
    --all-services) SERVICES=""; BUILD_SERVICES="" ;;
    *) echo "未知参数: $a"; exit 2 ;;
  esac
done

RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[1;33m'; NC=$'\033[0m'
ok()   { echo "${GRN}  ✓${NC} $*"; }
warn() { echo "${YEL}  !${NC} $*"; }
bad()  { echo "${RED}  ✗${NC} $*"; }
step() { echo; echo "${GRN}== $* ==${NC}"; }
fail=0

# ── 1. 环境体检 ───────────────────────────────────────────────────────────
step "1/6 环境体检"

command -v docker >/dev/null 2>&1 && ok "docker $(docker --version | awk '{print $3}' | tr -d ,)" \
  || { bad "没装 docker"; fail=1; }
docker compose version >/dev/null 2>&1 && ok "docker compose $(docker compose version --short 2>/dev/null)" \
  || { bad "docker compose v2 不可用（需要 docker compose 而非 docker-compose）"; fail=1; }
docker info >/dev/null 2>&1 && ok "当前用户可操作 docker" \
  || { bad "当前用户无权限操作 docker，执行: sudo usermod -aG docker \$USER 后重新登录"; fail=1; }

mem_total=$(awk '/^MemTotal:/{print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
[ "$mem_total" -ge 3500 ] && ok "内存 ${mem_total}MB" || warn "内存仅 ${mem_total}MB，构建可能吃紧"

disk_free=$(df -BG --output=avail "$(dirname "$APP_DATA_ROOT")" 2>/dev/null | tail -1 | tr -dc '0-9')
[ "${disk_free:-0}" -ge 15 ] && ok "$(dirname "$APP_DATA_ROOT") 可用 ${disk_free}G" \
  || warn "可用磁盘仅 ${disk_free:-?}G，镜像+构建缓存约需 10G"

[ "$fail" -eq 1 ] && { echo; bad "前置条件不满足，先解决上面的 ✗"; exit 1; }

# ── 2. swap ───────────────────────────────────────────────────────────────
step "2/6 swap（4G 机器构建时防 OOM）"
swap_mb=$(awk '/^SwapTotal:/{print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
if [ "$swap_mb" -ge 2048 ]; then
  ok "已有 swap ${swap_mb}MB"
elif [ "$CHECK_ONLY" -eq 1 ]; then
  warn "无 swap（体检模式不创建）"
elif [ "$DO_SWAP" -eq 0 ]; then
  warn "按 --no-swap 跳过"
else
  echo "  创建 4G swap ..."
  if sudo fallocate -l 4G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=4096 status=none; then
    sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    ok "swap 已启用并写入 /etc/fstab"
  else
    warn "swap 创建失败，继续（构建时注意内存）"
  fi
fi

# ── 3. 目录与外部卷 ───────────────────────────────────────────────────────
step "3/6 目录与数据卷"
if [ "$CHECK_ONLY" -eq 0 ]; then
  sudo mkdir -p "$APP_DATA_ROOT"/{config,appdata,logs,dead_letter,backup,deploy-state}
  sudo chown -R "$(id -u):$(id -g)" "$APP_DATA_ROOT"
fi
[ -d "$APP_DATA_ROOT/config" ] && ok "$APP_DATA_ROOT 就绪" || { bad "目录未创建"; exit 1; }

for v in industrial_pgdata industrial_minio; do
  if docker volume inspect "$v" >/dev/null 2>&1; then
    ok "卷 $v 已存在（数据保留）"
  elif [ "$CHECK_ONLY" -eq 1 ]; then
    warn "卷 $v 不存在"
  else
    docker volume create "$v" >/dev/null && ok "卷 $v 已创建"
  fi
done

# ── 4. 配置文件 ───────────────────────────────────────────────────────────
step "4/6 配置文件 $ENV_FILE"
if [ ! -f "$ENV_FILE" ]; then
  if [ "$CHECK_ONLY" -eq 1 ]; then bad "配置文件不存在"; exit 1; fi
  cp "$REPO_DIR/deploy/docker/.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  bad "已从模板生成 $ENV_FILE，请先填好再重新运行本脚本"
  echo "     必填：PG_PASSWORD / MINIO_SECRET_KEY / DEEPSEEK_API_KEY / MQTT_BROKER / MQTT_TOPIC"
  echo "     注意：PG_HOST 要填 postgresql（容器服务名），PG_PORT 填 5432"
  exit 1
fi
ok "配置文件存在"

getv() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r'; }
# MINIO_SECRET_KEY 即使不起 minio 也必须有值：compose 用了 ${VAR:?} 语法，
# 解析整个文件时就插值，与 profile / 起不起该服务无关，缺了会直接报错
for k in PG_PASSWORD MINIO_SECRET_KEY PG_HOST PG_PORT PG_DB PG_USER; do
  v="$(getv "$k")"
  if [ -z "$v" ]; then bad "$k 未设置"; fail=1
  elif [[ "$v" == your-* || "$v" == "<"* ]]; then bad "$k 还是模板占位符: $v"; fail=1
  else ok "$k 已设置"; fi
done

[ "$(getv PG_HOST)" = "postgresql" ] || warn "PG_HOST=$(getv PG_HOST)（容器内应为 postgresql）"
[ "$(getv PG_PORT)" = "5432" ] || warn "PG_PORT=$(getv PG_PORT)（容器内应为 5432，15432 是宿主机映射口）"

prov="$(getv PROVIDER)"; keyname=""
case "$prov" in
  deepseek) keyname=DEEPSEEK_API_KEY ;; openai) keyname=OPENAI_API_KEY ;;
  dashscope|qwen) keyname=DASHSCOPE_API_KEY ;;
esac
if [ -n "$keyname" ]; then
  kv="$(getv "$keyname")"
  { [ -n "$kv" ] && [[ "$kv" != your-* ]]; } && ok "PROVIDER=$prov, $keyname 已设置" \
    || { bad "PROVIDER=$prov 但 $keyname 未正确设置（AI 分析会失败）"; fail=1; }
else
  warn "PROVIDER=$prov 未识别，请自行确认对应 API key 已配"
fi

mb="$(getv MQTT_BROKER)"
[ -n "$mb" ] && ok "MQTT_BROKER=$mb" || warn "MQTT_BROKER 为空 —— mqtt-etl 起来也不会有数据进库"

[ "$fail" -eq 1 ] && { echo; bad "配置有问题，修好 $ENV_FILE 再重跑"; exit 1; }

# ── 5. 校验 compose ───────────────────────────────────────────────────────
step "5/6 校验 compose 配置"
cd "$REPO_DIR/deploy/docker" || { bad "找不到 $REPO_DIR/deploy/docker"; exit 1; }
if $COMPOSE $PROFILES config >/dev/null 2>"$APP_DATA_ROOT/logs/compose-config.err"; then
  ok "compose 配置可解析"
else
  bad "compose 配置有误："
  sed 's/^/     /' "$APP_DATA_ROOT/logs/compose-config.err" | head -10
  exit 1
fi

if [ "$CHECK_ONLY" -eq 1 ]; then echo; ok "体检通过（未做任何改动）"; exit 0; fi

# ── 6. 分阶段启动 ─────────────────────────────────────────────────────────
step "6/6 启动服务"

echo "  [1/3] 启动数据库（首次会自动建表，含 hypertable，可能要 1-2 分钟）..."
$COMPOSE $PROFILES up -d postgresql || { bad "数据库启动失败"; exit 1; }

echo -n "  等待数据库就绪 "
for i in $(seq 1 60); do
  if docker exec postgresql pg_isready -U "$(getv PG_USER)" -d "$(getv PG_DB)" >/dev/null 2>&1; then
    echo; ok "数据库就绪"; break
  fi
  echo -n "."; sleep 3
  [ "$i" -eq 60 ] && { echo; bad "等待超时，看日志: docker logs postgresql"; exit 1; }
done

echo "  [2/3] 构建并启动应用（首次构建约 5-10 分钟）..."
COMPILE_SOURCE=false $COMPOSE build $BUILD_SERVICES || { bad "构建失败"; exit 1; }
$COMPOSE $PROFILES up -d $SERVICES || { bad "启动失败"; exit 1; }

echo -n "  [3/3] 健康检查 "
healthy=0
for i in $(seq 1 40); do
  if curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; then healthy=1; echo; ok "应用健康"; break; fi
  echo -n "."; sleep 5
done
if [ "$healthy" -ne 1 ]; then
  echo; bad "健康检查未通过，最近日志："
  $COMPOSE logs --tail=40 industrial-ai
  exit 1
fi

# ── 收尾 ──────────────────────────────────────────────────────────────────
echo
echo "${GRN}========================================${NC}"
echo "${GRN}  部署完成${NC}"
echo "${GRN}========================================${NC}"
$COMPOSE $PROFILES ps
echo
echo "访问：http://$(curl -s --max-time 3 ifconfig.me 2>/dev/null || echo '<公网IP>'):9300"
echo "      （腾讯云安全组需放行 9300 端口）"
echo
echo "确认数据在进库："
echo "  docker exec -it postgresql psql -U $(getv PG_USER) -d $(getv PG_DB) \\"
echo "    -c \"SELECT count(*), max(point_time) FROM device_alarm_info;\""
echo
echo "接下来建议："
echo "  1) 配 7 天保留策略（否则传感器表无限增长）："
echo "     docker exec -i postgresql psql -U $(getv PG_USER) -d $(getv PG_DB) \\"
echo "       < $REPO_DIR/deploy/docker/init-sql/migrations/006_raw_retention_7d.sql"
echo "  2) 开自动部署：见 deploy/docker/腾讯云部署.md 第二部分"
echo "  3) 配备份：crontab 加 scripts/backup.sh"
