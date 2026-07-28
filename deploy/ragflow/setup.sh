#!/usr/bin/env bash
# ========================================
# RAGFlow 独立部署脚本（用于服务器上单独起一套本地/自建 RAGFlow）
#
# 跟主项目 docker-compose 完全独立、互不干扰——RAGFlow 官方栈本身较重
# （RAGFlow 服务 + 文档检索引擎(Elasticsearch/Infinity) + MySQL + Redis + MinIO），
# 不适合合并进 deploy/docker/docker-compose.yml 一起管理，所以单独一个文件夹自己管生命周期。
#
# 用法：./setup.sh [操作]
# 操作：
#   install      首次：clone 官方仓库 + 环境检查 + 启动（默认）
#   up           启动（启动前做一次环境检查，只提示不阻断）
#   down         停止（不要自己加 -v，会把 RAGFlow 的数据卷全删了）
#   restart / logs / status
#   check        只做环境检查（内核参数、端口冲突），不启动
#   fetch        只 clone 官方仓库不启动（deploy_all.sh 改端口前用 / 离线打包前用）
#   upgrade      升级版本（数据卷保留）：RAGFLOW_TAG=v0.xx.x ./setup.sh upgrade
#                旧 ragflow-src 改名备份不删除，改过的 docker/.env 要手动对照搬到新目录
#   save-images  在有外网的机器上把 RAGFlow 全套镜像导出为 tar（离线部署用）
#   load-images  在无外网的服务器上导入 save-images 产出的 tar
#
# 首次部署（服务器有外网）：
#   cd ragflow && ./setup.sh install
#
# 离线部署（服务器无外网）：
#   有网机器:  ./setup.sh save-images   # 自动 clone + pull + docker save
#   把整个 deploy/ragflow/（含 ragflow-src/）和 ragflow-images.tar 拷到服务器
#   服务器:    ./setup.sh load-images && ./setup.sh up
#
# 部署完成后的配置回填（API key / 数据集 / 助手 ID / 主项目 .env）见 README.md
# ========================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# RAGFlow 官方仓库 + 版本号：部署前建议去
# https://github.com/infiniflow/ragflow/releases 确认当前稳定版 tag 是否要更新
REPO_URL="https://github.com/infiniflow/ragflow.git"
REPO_TAG="${RAGFLOW_TAG:-v0.17.2}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="$SCRIPT_DIR/ragflow-src"
COMPOSE_FILE="$SRC_DIR/docker/docker-compose.yml"
IMAGES_TAR_DEFAULT="$SCRIPT_DIR/ragflow-images.tar"

ACTION=${1:-install}

_compose() {
    (cd "$SRC_DIR/docker" && docker compose "$@")
}

_ensure_src() {
    if [ -d "$SRC_DIR" ]; then
        echo -e "${YELLOW}[跳过] $SRC_DIR 已存在，如需重新拉取请先删除该目录${NC}"
    else
        echo -e "${YELLOW}clone RAGFlow 官方仓库 (tag=$REPO_TAG)...${NC}"
        git clone --depth 1 --branch "$REPO_TAG" "$REPO_URL" "$SRC_DIR"
    fi
    if [ ! -f "$COMPOSE_FILE" ]; then
        echo -e "${RED}错误：$COMPOSE_FILE 不存在，RAGFlow 仓库结构可能变了，去仓库里确认 docker-compose 文件实际位置${NC}"
        exit 1
    fi
}

# 读 ragflow-src/docker/.env 里某个变量的值；未 clone 或键不存在时用官方默认值（$2）
_rf_env() {
    local val=""
    if [ -f "$SRC_DIR/docker/.env" ]; then
        val=$(grep -E "^[[:space:]]*$1=" "$SRC_DIR/docker/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | tr -d '[:space:]')
    fi
    echo "${val:-$2}"
}

_port_in_use() {
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk 'NR>1 {print $4}' | grep -Eq "[:.]$1\$"
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]$1\$"
    else
        return 1  # 两个工具都没有就跳过端口检测
    fi
}

# 环境检查。$1: strict=致命项不过就退出（install 用，SKIP_PREFLIGHT=1 可跳过）；warn=只提示
preflight() {
    local mode="${1:-warn}" fatal=0

    echo -e "${YELLOW}—— 环境检查 ——${NC}"

    if ! command -v docker >/dev/null 2>&1; then
        echo -e "${RED}[x] docker 未安装${NC}"
        exit 1
    fi
    if ! docker compose version >/dev/null 2>&1; then
        echo -e "${RED}[x] docker compose v2 不可用（RAGFlow 官方 compose 需要 v2）${NC}"
        exit 1
    fi

    # Elasticsearch 硬性要求：不满足时 ES 容器反复重启，RAGFlow 起不来（首启失败头号原因）
    if [ "$(uname -s)" = "Linux" ]; then
        local mmc
        mmc=$(sysctl -n vm.max_map_count 2>/dev/null || echo 0)
        if [ "${mmc:-0}" -lt 262144 ]; then
            echo -e "${RED}[x] vm.max_map_count=${mmc}，需 >= 262144${NC}"
            echo    "    临时生效: sudo sysctl -w vm.max_map_count=262144"
            echo    "    永久生效: echo 'vm.max_map_count=262144' | sudo tee -a /etc/sysctl.conf && sudo sysctl -p"
            fatal=1
        else
            echo -e "${GREEN}[v] vm.max_map_count=${mmc}${NC}"
        fi
    fi

    # 端口占用检查——重点：跟主项目（deploy/docker）同机部署时 MinIO 9000/9001 必撞。
    # 端口取值优先读 ragflow-src/docker/.env（clone 之后），否则按官方 v0.17.x 默认值。
    local item port label
    for item in \
        "$(_rf_env SVR_HTTP_PORT 9380)|API(SVR_HTTP_PORT)" \
        "80|Web UI(官方 compose 硬编码 80:80)" \
        "443|Web UI https(官方 compose 硬编码 443:443)" \
        "$(_rf_env MINIO_PORT 9000)|MinIO(MINIO_PORT)——主项目 minio 也占 9000" \
        "$(_rf_env MINIO_CONSOLE_PORT 9001)|MinIO 控制台(MINIO_CONSOLE_PORT)——主项目 minio 也占 9001" \
        "$(_rf_env REDIS_PORT 6379)|Redis(REDIS_PORT)——主项目 legacy 模式的 knb-redis 也占 6379" \
        "$(_rf_env MYSQL_PORT 5455)|MySQL(MYSQL_PORT)" \
        "$(_rf_env ES_PORT 1200)|Elasticsearch(ES_PORT)"
    do
        port="${item%%|*}"
        label="${item#*|}"
        if _port_in_use "$port"; then
            echo -e "${YELLOW}[!] 宿主机端口 $port 已被占用 —— $label${NC}"
            echo    "    占用者是别的服务：改 ragflow-src/docker/.env 里对应变量（80/443 是硬编码，要改官方 compose）"
            echo    "    占用者是本 RAGFlow 已在运行：忽略即可"
        else
            echo -e "${GREEN}[v] 宿主机端口 $port 空闲 —— $label${NC}"
        fi
    done

    if [ "$fatal" = "1" ]; then
        if [ "$mode" = "strict" ] && [ "${SKIP_PREFLIGHT:-0}" != "1" ]; then
            echo -e "${RED}环境检查未通过，先按上面提示修复；确要跳过用 SKIP_PREFLIGHT=1 ./setup.sh $ACTION${NC}"
            exit 1
        fi
        echo -e "${YELLOW}[!] 环境检查有未通过项，继续执行（启动后注意看 elasticsearch 容器日志）${NC}"
    fi
    echo -e "${YELLOW}——————————${NC}"
}

case "$ACTION" in
    install)
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  RAGFlow 首次部署${NC}"
        echo -e "${GREEN}========================================${NC}"

        _ensure_src
        preflight strict

        echo -e "${YELLOW}启动 RAGFlow（首次会拉取镜像，较慢）...${NC}"
        _compose up -d

        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  部署完成，查看状态：./setup.sh status${NC}"
        echo -e "${GREEN}  查看日志：./setup.sh logs${NC}"
        echo -e "${GREEN}  下一步（API key/数据集/助手 ID/主项目 .env 回填）见 README.md${NC}"
        echo -e "${GREEN}========================================${NC}"
        ;;

    up)
        preflight warn
        echo -e "${YELLOW}启动 RAGFlow...${NC}"
        _compose up -d
        echo -e "${GREEN}已启动！${NC}"
        ;;

    down)
        echo -e "${YELLOW}停止 RAGFlow...${NC}"
        _compose down
        echo -e "${GREEN}已停止！（数据卷保留；千万别手动加 -v，会删光 RAGFlow 数据）${NC}"
        ;;

    restart)
        echo -e "${YELLOW}重启 RAGFlow...${NC}"
        _compose restart
        echo -e "${GREEN}重启完成！${NC}"
        ;;

    logs)
        _compose logs -f
        ;;

    status)
        _compose ps
        ;;

    check)
        preflight warn
        ;;

    fetch)
        _ensure_src
        ;;

    upgrade)
        # 升级到新版本：数据都在 named volume 里，换源码目录不动数据——
        # API key/数据集/助手 ID/已解析文档全保留，主项目 .env 无需改动。
        # 旧目录只改名备份不删除，方便对照搬运你改过的 docker/.env（端口等）。
        if [ ! -d "$SRC_DIR" ]; then
            echo -e "${RED}错误：$SRC_DIR 不存在，还没装过，直接 ./setup.sh install${NC}"
            exit 1
        fi
        if [ -z "${RAGFLOW_TAG:-}" ]; then
            echo -e "${RED}用法：RAGFLOW_TAG=v0.xx.x ./setup.sh upgrade（必须显式指定目标版本，"
            echo -e "防止误用脚本里的默认旧 tag 空跑一遍）${NC}"
            exit 1
        fi
        echo -e "${YELLOW}[1/3] 停止当前 RAGFlow（数据卷保留）...${NC}"
        _compose down
        BAK_DIR="$SRC_DIR.old-$(date +%Y%m%d-%H%M%S)"
        echo -e "${YELLOW}[2/3] 备份旧源码目录 → $BAK_DIR${NC}"
        mv "$SRC_DIR" "$BAK_DIR"
        echo -e "${YELLOW}[3/3] clone 新版本 ($REPO_TAG)...${NC}"
        if ! git clone --depth 1 --branch "$REPO_TAG" "$REPO_URL" "$SRC_DIR"; then
            echo -e "${RED}clone 失败。回滚：mv $BAK_DIR $SRC_DIR && ./setup.sh up${NC}"
            exit 1
        fi
        if [ ! -f "$COMPOSE_FILE" ]; then
            echo -e "${RED}错误：新版本里 $COMPOSE_FILE 不存在，仓库结构变了；"
            echo -e "回滚：rm -rf $SRC_DIR && mv $BAK_DIR $SRC_DIR && ./setup.sh up${NC}"
            exit 1
        fi
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  新版本源码就绪，接下来手动两步：${NC}"
        echo -e "${GREEN}  1. 对照旧配置，把你改过的端口等搬进新 .env（别整个覆盖，新版可能有新增键）：${NC}"
        echo -e "${GREEN}     diff $BAK_DIR/docker/.env $SRC_DIR/docker/.env${NC}"
        echo -e "${GREEN}  2. ./setup.sh up   （数据卷自动复用；离线环境先在有网机器 save-images 换新镜像）${NC}"
        echo -e "${GREEN}  确认新版本运行正常后可删除备份目录 $BAK_DIR${NC}"
        echo -e "${GREEN}========================================${NC}"
        ;;

    save-images)
        _ensure_src
        echo -e "${YELLOW}[1/2] 拉取 RAGFlow 全套镜像...${NC}"
        _compose pull
        IMAGES=$(_compose config --images | sort -u)
        if [ -z "$IMAGES" ]; then
            echo -e "${RED}错误：没解析出镜像清单，检查 ragflow-src/docker/ 下的 compose/.env${NC}"
            exit 1
        fi
        OUT="${2:-$IMAGES_TAR_DEFAULT}"
        echo -e "${YELLOW}[2/2] 导出以下镜像到 $OUT ...${NC}"
        echo "$IMAGES"
        # shellcheck disable=SC2086
        docker save $IMAGES -o "$OUT"
        echo -e "${GREEN}导出完成：$(du -h "$OUT" | cut -f1)${NC}"
        echo -e "${GREEN}把整个 deploy/ragflow/（含 ragflow-src/）和该 tar 拷到目标服务器，"
        echo -e "然后执行：./setup.sh load-images && ./setup.sh up${NC}"
        ;;

    load-images)
        TAR="${2:-$IMAGES_TAR_DEFAULT}"
        if [ ! -f "$TAR" ]; then
            echo -e "${RED}错误：$TAR 不存在（可用第二个参数指定 tar 路径）${NC}"
            exit 1
        fi
        echo -e "${YELLOW}导入镜像 $TAR ...${NC}"
        docker load -i "$TAR"
        echo -e "${GREEN}导入完成，接着执行：./setup.sh up${NC}"
        ;;

    *)
        echo -e "${RED}用法：./setup.sh [install|up|down|restart|logs|status|check|fetch|upgrade|save-images|load-images]${NC}"
        exit 1
        ;;
esac
