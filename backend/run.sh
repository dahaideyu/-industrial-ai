#!/bin/bash

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 默认值
HOST="0.0.0.0"
PORT=9300
RELOAD=false
ENV_FILE=".env"
MODEL=""

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--host)
            HOST="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -r|--reload)
            RELOAD=true
            shift
            ;;
        -e|--env)
            ENV_FILE="$2"
            shift 2
            ;;
        -m|--model)
            MODEL="$2"
            shift 2
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

# 激活虚拟环境（如果存在）
if [ -f "venv/bin/activate" ]; then
    echo "[venv] 激活虚拟环境"
    source venv/bin/activate
fi

# 构建启动命令
CMD="python app.py --env $ENV_FILE"

if [ -n "$MODEL" ]; then
    CMD="$CMD --model $MODEL"
fi

echo "========================================"
echo "  Chaowei Agent Backend"
echo "========================================"
echo "配置文件: $ENV_FILE"
echo "启动 AI Report 服务 (${HOST}:${PORT})..."
echo "命令: $CMD"
echo ""

exec $CMD
