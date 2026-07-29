#!/usr/bin/env bash
# Docker 容器入口
set -e

echo "=== Industrial AI Starting ==="
echo "ENABLE_SQL_QA: ${ENABLE_SQL_QA:-true}"
echo "ENABLE_REPORT_SCHEDULER: ${ENABLE_REPORT_SCHEDULER:-false}"
echo "PROVIDER: ${PROVIDER:-deepseek}"

# ---- 等待依赖服务就绪 ----
# 连库变量统一用 PG_*（旧名 KNB_PG_* 已废弃，见 backend/core/pg_env.py）
if [ "${ENABLE_KNOWLEDGE_BASE:-false}" = "true" ]; then
  WAIT_PG_HOST="${PG_HOST:-}"
  WAIT_PG_PORT="${PG_PORT:-5432}"
  WAIT_PG_USER="${PG_USER:-zxzz}"
  WAIT_PG_DB="${PG_DB:-knowledge_base}"
  WAIT_PG_PASSWORD="${PG_PASSWORD:-}"
  if [ -z "$WAIT_PG_HOST" ]; then
    echo "[0/3] PG_HOST not set, skip waiting for PostgreSQL"
  else
    echo "[0/3] Waiting for PostgreSQL (${WAIT_PG_HOST}:${WAIT_PG_PORT})..."
    for i in $(seq 1 30); do
      if PGPASSWORD="$WAIT_PG_PASSWORD" pg_isready -h "$WAIT_PG_HOST" -p "$WAIT_PG_PORT" -U "$WAIT_PG_USER" -d "$WAIT_PG_DB" 2>/dev/null; then
        echo "PostgreSQL is ready"
        break
      fi
      if [ $i -eq 30 ]; then
        echo "WARNING: PostgreSQL not ready after 60s, starting anyway..."
      else
        echo "  waiting... ($i/30)"
        sleep 2
      fi
    done
  fi
fi

# 启动 nginx
echo "[1/3] Starting nginx..."
nginx

# 启动 FastAPI 后端
PORT=${BACKEND_PORT:-9300}
echo "[2/3] Starting backend on port $PORT..."
cd /app
exec /app/.venv/bin/uvicorn backend.app:app --host 0.0.0.0 --port $PORT --workers 1
