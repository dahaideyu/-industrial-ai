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
# 启动/停止容器时启用的 compose profile：
#   local-db = 容器内 TimescaleDB（PG_HOST=postgresql 的基地必须带，否则 postgresql
#              服务被 profile 挡住不启动，应用连不上库；见 docker-compose.yml）
#   mqtt     = MQTT ETL（老基地不跑 MQTT 就不加）
# 默认带 local-db；某环境要连外部 PG、不想起容器内 PG 时，用环境变量覆盖清空：
#   DEPLOY_PROFILES="" ./deploy.sh test update
COMPOSE_PROFILES="${DEPLOY_PROFILES:---profile local-db}"
# 项目根目录（scripts -> docker -> deploy -> 项目根目录）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

case "$ENV" in
    test)
        PROMPT_ENV_FILE="$PROJECT_ROOT/deploy/docker/.env.test"
        ;;
    prod)
        PROMPT_ENV_FILE="$PROJECT_ROOT/deploy/docker/.env.prod"
        ;;
    shandong|jiangxi|changxing)
        PROMPT_ENV_FILE="$PROJECT_ROOT/deploy/docker/.env.prod.${ENV}"
        ;;
    weifu)
        # 威孚当前没有独立的 .env.prod.weifu，沿用通用生产配置。
        PROMPT_ENV_FILE="$PROJECT_ROOT/deploy/docker/.env.prod"
        ;;
esac

[ -f "$PROMPT_ENV_FILE" ] || {
    echo -e "${RED}错误：找不到环境配置文件 '$PROMPT_ENV_FILE'${NC}"
    exit 1
}

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

        # 构建前始终重新加密提示词；密钥由当前环境对应的配置文件提供。
        # 服务器上可能没有 python 命令（Linux 常见只有 python3），自动探测可用解释器；
        # 加密脚本还需要 cryptography 库（缺失时脚本会自行报错提示安装）。
        echo -e "${YELLOW}[2/4] 加密提示词...${NC}"
        PYTHON_BIN=""
        for cand in python3 python; do
            if command -v "$cand" >/dev/null 2>&1; then
                PYTHON_BIN="$cand"
                break
            fi
        done
        if [ -z "$PYTHON_BIN" ]; then
            echo -e "${RED}错误：找不到 python/python3 解释器，无法加密提示词。${NC}"
            echo "请先安装（Debian/Ubuntu）："
            echo "  sudo apt update && sudo apt install -y python3 python3-pip"
            echo "  pip3 install cryptography"
            exit 1
        fi
        PROMPT_ENV_FILE="$PROMPT_ENV_FILE" "$PYTHON_BIN" "$PROJECT_ROOT/scripts/encrypt_prompts.py"

        # 停止旧容器并强制清理冲突容器
        echo -e "${YELLOW}[3/4] 停止旧容器...${NC}"
        # 1. 先停止当前 compose 项目
        docker compose -f deploy/docker/docker-compose.yml -f "deploy/docker/docker-compose.${ENV}.yml" -p "$PROJECT_NAME" $COMPOSE_PROFILES down 2>/dev/null || true
        # 2. 强制删除所有可能残留的同名容器（包括手动创建的）
        #    ai-agent/AI-agent/chaowei-agent 都是容器旧名（现已改叫 industrial-ai），保留在列表里让老部署升级时也能被清掉
        #    industrial-ai 还会带环境后缀（industrial-ai-test / industrial-ai-prod / industrial-ai-changxing 等），
        #    因为各环境 compose 覆盖了 container_name，必须一并清理，否则 up 时报 "container name already in use"
        docker rm -f minio redis postgresql knb-postgresql knb-redis knb-minio knb-libreoffice knb-celery-worker \
            industrial-ai industrial-ai-test industrial-ai-prod industrial-ai-shandong industrial-ai-jiangxi industrial-ai-changxing industrial-ai-weifu industrial-ai-yongxu \
            ai-agent AI-agent chaowei-agent repair-suggestion mqtt-etl 2>/dev/null || true
        # 3. 清理可能残留的项目网络（含历次改名前 chaowei-${ENV}/ai-agent-${ENV} 项目遗留的旧网络，一次性兼容）
        docker network rm "${PROJECT_NAME}_default" "chaowei-${ENV}_default" "ai-agent-${ENV}_default" 2>/dev/null || true

        # 构建并启动（服务器部署不编译源码，加快构建速度）
        echo -e "${YELLOW}[4/4] 构建镜像并启动容器...${NC}"
        COMPILE_SOURCE=false docker compose -f deploy/docker/docker-compose.yml -f "deploy/docker/docker-compose.${ENV}.yml" -p "$PROJECT_NAME" $COMPOSE_PROFILES up -d --build

        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  部署完成！${NC}"
        echo -e "${GREEN}  查看日志：cd $PROJECT_ROOT/deploy/docker && ./scripts/deploy.sh $ENV logs${NC}"
        echo -e "${GREEN}========================================${NC}"
        ;;

    restart)
        echo -e "${YELLOW}重启服务 - 环境: ${ENV} ...${NC}"
        docker compose -f deploy/docker/docker-compose.yml -f "deploy/docker/docker-compose.${ENV}.yml" -p "$PROJECT_NAME" $COMPOSE_PROFILES restart
        echo -e "${GREEN}重启完成！${NC}"
        ;;

    down)
        echo -e "${YELLOW}停止服务 - 环境: ${ENV} ...${NC}"
        docker compose -f deploy/docker/docker-compose.yml -f "deploy/docker/docker-compose.${ENV}.yml" -p "$PROJECT_NAME" $COMPOSE_PROFILES down
        echo -e "${GREEN}服务已停止！${NC}"
        ;;

    logs)
        docker compose -f deploy/docker/docker-compose.yml -f "deploy/docker/docker-compose.${ENV}.yml" -p "$PROJECT_NAME" $COMPOSE_PROFILES logs -f
        ;;

    *)
        echo -e "${RED}用法：./scripts/deploy.sh [环境] [操作] [分支]${NC}"
        echo -e "${RED}环境：test | prod | shandong | jiangxi | changxing | weifu${NC}"
        echo -e "${RED}操作：update | restart | down | logs${NC}"
        exit 1
        ;;
esac
