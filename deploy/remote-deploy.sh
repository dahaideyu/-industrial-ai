#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="${APP_NAME:-industrial-ai}"
APP_PORT="${APP_PORT:-9300}"
PROVIDER="${PROVIDER:-deepseek}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    fail "未找到 docker compose 或 docker-compose，请先在服务器安装 Docker Compose。"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "未找到命令: $1"
}

log "开始部署 ${APP_NAME}"
cd "$PROJECT_DIR"

# 仓库根目录没有 compose 文件（都在 deploy/docker/ 下），不显式指定会报 "no configuration file"。
# 默认用基础 compose；可用环境变量覆盖以叠加分区配置，例如:
#   COMPOSE_FILE="deploy/docker/docker-compose.yml:deploy/docker/docker-compose.jiangxi.yml"
# compose 内相对路径（build context: ../..、env_file: ./.env）按 compose 文件所在目录(deploy/docker/)解析，
# 因此 env 文件约定放在 deploy/docker/.env。
export COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker/docker-compose.yml}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-industrial-ai}"

require_cmd docker

# compose 的 env_file 用 deploy/docker/.env（见 deploy/docker/docker-compose.yml），这里校验它存在
if [ ! -f "deploy/docker/.env" ]; then
  fail "服务器缺少 ${PROJECT_DIR}/deploy/docker/.env，请创建并填入真实 API Key、数据库密码等配置后重新运行 pipeline。"
fi

mkdir -p logs

log "校验 compose 配置"
PROVIDER="$PROVIDER" compose config >/dev/null

log "构建镜像"
PROVIDER="$PROVIDER" compose build --pull

log "启动容器"
PROVIDER="$PROVIDER" compose up -d --remove-orphans

log "清理旧镜像"
docker image prune -f >/dev/null || true

log "等待服务响应 http://127.0.0.1:${APP_PORT}/"
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${APP_PORT}/" >/dev/null 2>&1; then
    log "部署完成，服务已响应。"
    compose ps
    exit 0
  fi
  sleep 2
done

log "服务未在预期时间内响应，输出最近日志："
compose logs --tail=120
fail "部署后健康检查失败。"
