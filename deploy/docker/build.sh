#!/usr/bin/env bash
set -e

# ============================================
# 工业智能体 一键构建脚本 —— 应用镜像(app/worker/lean 三个 target)
# + PostgreSQL(TimescaleDB) 镜像，一起打进一个 tar，供离线拷贝到服务器 docker load。
# 用法: ./build.sh [版本/tag]
# 示例: ./build.sh 1.0.0
# 三个镜像名固定为 industrial-ai / industrial-ai-worker / industrial-ai-lean，
# 必须跟 docker-compose.yml 里对应服务的 image: 字段一致，否则 docker load 之后
# `docker compose up` 找不到同名镜像会重新触发本地构建。
# 三个 target 复用同一套 Dockerfile 前置 stage（frontend-build/backend-deps/
# code-protect），Docker 构建缓存会自动跳过已构建过的公共 stage，不会重复三遍。
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

IMAGE_NAME="industrial-ai"
VERSION="${1:-latest}"

APP_IMAGE="${IMAGE_NAME}:${VERSION}"
WORKER_IMAGE="${IMAGE_NAME}-worker:${VERSION}"
LEAN_IMAGE="${IMAGE_NAME}-lean:${VERSION}"
TAR_FILE="${IMAGE_NAME}-${VERSION}-bundle.tar"
KEY_FILE="${SCRIPT_DIR}/build_key.txt"

PG_IMAGE=$(grep -E 'image:.*timescale/timescaledb' "$SCRIPT_DIR/docker-compose.yml" | awk '{print $2}')
if [ -z "$PG_IMAGE" ]; then
    echo "错误: 没能从 docker-compose.yml 里解析到 timescale/timescaledb 镜像名，脚本需要更新"
    exit 1
fi

echo "============================================"
echo "超维agent 离线打包脚本"
echo "应用镜像 (industrial-ai):        ${APP_IMAGE}"
echo "Worker 镜像 (knb-celery-worker): ${WORKER_IMAGE}"
echo "精简镜像 (repair-suggestion/mqtt-etl): ${LEAN_IMAGE}"
echo "数据库镜像: ${PG_IMAGE}"
echo "============================================"
echo ""

# 0. 加密提示词（生成 key + 加密所有 prompts/*.txt → prompts_encrypted.json）
echo "[0/5] 加密提示词..."
if python "$PROJECT_ROOT/scripts/encrypt_prompts.py"; then
    :
else
    echo "警告: 提示词加密失败，继续构建..."
fi
echo ""

# 1. 构建完整应用镜像（含 nginx + 前端 + LibreOffice，默认 target: final-app）
echo "[1/5] 构建应用镜像 ${APP_IMAGE}（含 Cython 编译）..."
docker build -f "$SCRIPT_DIR/Dockerfile" \
    --build-arg COMPILE_SOURCE=true \
    --build-arg VITE_ENABLE_SQL_QA=true \
    -t "$APP_IMAGE" \
    "$PROJECT_ROOT"
echo ""

# 2. 构建 worker 镜像（含 LibreOffice + OCR，不含 nginx/前端，target: final-worker）
echo "[2/5] 构建 worker 镜像 ${WORKER_IMAGE}..."
docker build -f "$SCRIPT_DIR/Dockerfile" \
    --target final-worker \
    --build-arg COMPILE_SOURCE=true \
    -t "$WORKER_IMAGE" \
    "$PROJECT_ROOT"
echo ""

# 3. 构建精简镜像（纯后端运行时，target: final-base）
echo "[3/5] 构建精简镜像 ${LEAN_IMAGE}..."
docker build -f "$SCRIPT_DIR/Dockerfile" \
    --target final-base \
    --build-arg COMPILE_SOURCE=true \
    -t "$LEAN_IMAGE" \
    "$PROJECT_ROOT"
echo ""

# 4. 拉取 PostgreSQL/TimescaleDB 官方镜像（本地已有相同 tag 则跳过）
echo "[4/5] 检查/拉取数据库镜像 ${PG_IMAGE} ..."
if docker image inspect "$PG_IMAGE" >/dev/null 2>&1; then
    echo "本地已存在，跳过拉取"
else
    docker pull "$PG_IMAGE"
fi
echo ""

# 5. 四个镜像一起导出到同一个 tar
echo "[5/5] 导出镜像到 ${TAR_FILE} ..."
docker save -o "$TAR_FILE" "$APP_IMAGE" "$WORKER_IMAGE" "$LEAN_IMAGE" "$PG_IMAGE"

# 读取密钥文件（由 encrypt_prompts.py 生成）
ENCRYPT_KEY=""
if [ -f "$KEY_FILE" ]; then
    ENCRYPT_KEY=$(cat "$KEY_FILE")
    rm -f "$KEY_FILE"
fi

echo "============================================"
echo "打包完成!"
echo ""
echo "镜像文件: ${TAR_FILE}"
echo ""
if [ -n "$ENCRYPT_KEY" ]; then
    echo "============================================"
    echo "!! 提示词加密密钥（更新服务器 .env）!!"
    echo ""
    echo "PROMPT_ENCRYPT_KEY=${ENCRYPT_KEY}"
    echo ""
    echo "============================================"
    echo ""
fi
echo "部署步骤（服务器上）:"
echo "  1. 上传 ${TAR_FILE} 到服务器"
echo "  2. docker load -i ${TAR_FILE}"
echo "  3. 参考 .env.example 在 deploy/docker/.env 里配好真实配置"
echo "  4. cd deploy/docker"
echo "     如果这次部署要用打包进来的本地数据库（而不是连外部数据库服务器）："
echo "       export IMAGE_TAG=${VERSION}"
echo "       docker compose --profile local-db up -d"
echo "     如果继续用外部数据库服务器，不需要本地这个 postgresql 容器："
echo "       export IMAGE_TAG=${VERSION}"
echo "       docker compose up -d"
echo "  （不加 --build，加载进来的三个镜像会直接复用，不会在服务器上重新构建）"
if [ -n "$ENCRYPT_KEY" ]; then
    echo ""
    echo "  5. 在服务器的 .env 中更新密钥:"
    echo "     PROMPT_ENCRYPT_KEY=${ENCRYPT_KEY}"
fi
echo "============================================"
