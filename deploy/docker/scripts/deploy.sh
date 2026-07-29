#!/usr/bin/env bash
# ========================================
# Industrial AI 部署脚本（简化版）
#
# 用法：./deploy.sh [环境] [操作] [分支]
# 环境：test | prod | shandong | jiangxi | changxing（默认 changxing）
# 操作：update | logs | restart | down（默认 update）
# 分支：git 分支名（默认 dev）
#
# 首次部署：
#   git clone <仓库地址> /opt/industrial-ai
#   cd /opt/industrial-ai/deploy/docker
#   ./scripts/deploy.sh changxing update
#
# 指定分支部署：
#   ./scripts/deploy.sh changxing update feature/ai-report
#
# 后续更新：
#   cd /opt/industrial-ai/deploy/docker
#   ./scripts/deploy.sh changxing update
#
# 重启服务：
#   ./scripts/deploy.sh changxing restart
#
# 停止服务：
#   ./scripts/deploy.sh changxing down
#
# 查看日志：
#   ./scripts/deploy.sh changxing logs
# ========================================

set -e
export DOCKER_BUILDKIT=1

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 参数解析
ENV=${1:-changxing}
ACTION=${2:-update}
BRANCH=${3:-dev}

# 环境验证
if [ "$ENV" != "test" ] && [ "$ENV" != "prod" ] && [ "$ENV" != "shandong" ] && [ "$ENV" != "jiangxi" ] && [ "$ENV" != "changxing" ] && [ "$ENV" != "weifu" ]; then
    echo -e "${RED}错误：无效的环境 '$ENV'，可选值：test | prod | shandong | jiangxi | changxing | weifu${NC}"
    exit 1
fi

PROJECT_NAME="industrial-ai-${ENV}"
# 项目根目录（scripts -> docker -> deploy -> 项目根目录）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$PROJECT_ROOT"

case "$ACTION" in
    update)
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  Industrial AI 部署 - 环境: ${ENV}${NC}"
        echo -e "${GREEN}========================================${NC}"

        # 拉取最新代码（只触发一次认证）
        echo -e "${YELLOW}[1/3] 拉取分支 $BRANCH ...${NC}"
        git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" "origin/$BRANCH"
        git pull origin "$BRANCH"

        # 停止旧容器并强制清理冲突容器
        echo -e "${YELLOW}[2/3] 停止旧容器...${NC}"
        # 1. 先停止当前 compose 项目
        docker compose -f deploy/docker/docker-compose.yml -f "deploy/docker/docker-compose.${ENV}.yml" -p "$PROJECT_NAME" down 2>/dev/null || true
        # 2. 强制删除所有可能残留的同名容器（包括手动创建的）
        #    ai-agent/AI-agent/chaowei-agent 都是容器旧名（现已改叫 industrial-ai），保留在列表里让老部署升级时也能被清掉
        docker rm -f minio redis postgresql knb-postgresql knb-redis knb-minio knb-libreoffice knb-celery-worker industrial-ai ai-agent AI-agent chaowei-agent repair-suggestion mqtt-etl 2>/dev/null || true
        # 3. 清理可能残留的项目网络（含历次改名前 chaowei-${ENV}/ai-agent-${ENV} 项目遗留的旧网络，一次性兼容）
        docker network rm "${PROJECT_NAME}_default" "chaowei-${ENV}_default" "ai-agent-${ENV}_default" 2>/dev/null || true

        # 构建并启动（服务器部署不编译源码，加快构建速度）
        echo -e "${YELLOW}[3/3] 构建镜像并启动容器...${NC}"
        COMPILE_SOURCE=false docker compose -f deploy/docker/docker-compose.yml -f "deploy/docker/docker-compose.${ENV}.yml" -p "$PROJECT_NAME" up -d --build

        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  部署完成！${NC}"
        echo -e "${GREEN}  查看日志：cd $PROJECT_ROOT/deploy/docker && ./scripts/deploy.sh $ENV logs${NC}"
        echo -e "${GREEN}========================================${NC}"
        ;;

    restart)
        echo -e "${YELLOW}重启服务 - 环境: ${ENV} ...${NC}"
        docker compose -f deploy/docker/docker-compose.yml -f "deploy/docker/docker-compose.${ENV}.yml" -p "$PROJECT_NAME" restart
        echo -e "${GREEN}重启完成！${NC}"
        ;;

    down)
        echo -e "${YELLOW}停止服务 - 环境: ${ENV} ...${NC}"
        docker compose -f deploy/docker/docker-compose.yml -f "deploy/docker/docker-compose.${ENV}.yml" -p "$PROJECT_NAME" down
        echo -e "${GREEN}服务已停止！${NC}"
        ;;

    logs)
        docker compose -f deploy/docker/docker-compose.yml -f "deploy/docker/docker-compose.${ENV}.yml" -p "$PROJECT_NAME" logs -f
        ;;

    *)
        echo -e "${RED}用法：./scripts/deploy.sh [环境] [操作] [分支]${NC}"
        echo -e "${RED}环境：test | prod | shandong | jiangxi | changxing | weifu${NC}"
        echo -e "${RED}操作：update | restart | down | logs${NC}"
        exit 1
        ;;
esac
