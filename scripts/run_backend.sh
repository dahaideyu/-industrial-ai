#!/usr/bin/env bash
set -e

# 回到项目根目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "========================================"
echo "  Chaowei Agent Backend Service"
echo "========================================"

# 环境配置文件：默认 .env.test，可通过参数覆盖（如 .env.prod）
ENV_FILE="${1:-.env.test}"

if [ ! -f "$PROJECT_ROOT/$ENV_FILE" ]; then
    echo "[错误] 配置文件不存在: $ENV_FILE"
    echo "可用配置: .env.test, .env.prod, .env.prod.shandong, .env.prod.jiangxi"
    exit 1
fi

# 检查 uv 是否安装
if command -v uv &> /dev/null; then
    echo "[启动] 使用 uv + pyproject.toml"
    export CHAOWEI_ENV_FILE="$ENV_FILE"
    exec uv run uvicorn backend.app:app --host 0.0.0.0 --port 9300 --reload
elif [ -d "backend/venv" ]; then
    echo "[启动] 使用 backend/venv"
    source backend/venv/bin/activate
    python backend/app.py --env "$ENV_FILE"
else
    echo "[启动] 直接使用系统 Python"
    python backend/app.py --env "$ENV_FILE"
fi
