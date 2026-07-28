#!/usr/bin/env bash
# ============================================
# Chaowei Agent — 一键启动（仅前端 + 后端，不涉及 Docker，Linux / macOS）
# 用法:
#   ./start.sh                       # 使用默认配置 deploy/docker/.env
#   ./start.sh deploy/docker/.env.prod   # 使用指定配置
# 依赖的数据库/Redis/MinIO 等基础设施需自行准备好（外部服务器或已起的 Docker 容器）
# 需要连 Docker 一起起的完整环境，用同目录下的 start_docker.sh
# ============================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="${1:-deploy/docker/.env}"

if [ ! -f "$ENV_FILE" ]; then
    echo "[错误] 配置文件不存在: $ENV_FILE"
    exit 1
fi

echo "=== Chaowei Agent 启动 ==="
echo "配置文件: $ENV_FILE"

# 导出环境变量
export $(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$' | xargs)

# 读取功能开关状态
echo "--- 功能模块状态 ---"
echo "  SQL智能问答: ${ENABLE_SQL_QA:-false}"
echo "  报告调度器:  ${ENABLE_REPORT_SCHEDULER:-false}"

# 检查 uv 是否安装
if ! command -v uv &> /dev/null; then
    echo "[提示] uv 未安装，尝试使用 python"
    PY_CMD="python"
else
    PY_CMD="uv run"
fi

# 1. 启动后端
echo ""
echo "[1/2] 启动后端 (端口 9300)..."
$PY_CMD uvicorn backend.app:app --host 0.0.0.0 --port 9300 --reload &
BACKEND_PID=$!
echo "  后端 PID: $BACKEND_PID"

# 2. 启动前端
echo "[2/2] 启动前端 (端口 5173)..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..
echo "  前端 PID: $FRONTEND_PID"

echo ""
echo "============================================"
echo "  后端 API:  http://localhost:9300"
echo "  API 文档:  http://localhost:9300/docs"
echo "  前端页面:  http://localhost:5173"
echo "============================================"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 退出时清理
cleanup() {
    echo ""
    echo "正在停止服务..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    echo "已停止"
}
trap cleanup EXIT INT TERM

# 等待子进程
wait
