#!/bin/bash
# 首次启动本地 TimescaleDB 容器时执行（数据卷为空才会触发，幂等无害）。
# 所有应用表统一放进 $POSTGRES_DB（默认 knowledge_base）库 ——
# 设备参数(24张) + 知识库(14张) + AI报告(1张) + Agentic QA(4张)，表名互不重叠。
# 应用连接目标库由 PG_DB / POSTGRES_DB 环境变量统一控制。
set -e

echo "[init] 检查并创建 zxzz 角色..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'zxzz') THEN CREATE ROLE zxzz LOGIN SUPERUSER PASSWORD 'Admin@Zxzz'; END IF; END \$\$;"

echo "[init] 初始化 ${POSTGRES_DB} 库 schema（设备参数 / job）..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -f /docker-entrypoint-initdb.d/schemas/01_schema_postgres.sql

echo "[init] 初始化 ${POSTGRES_DB} 库 schema（知识库）..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -f /docker-entrypoint-initdb.d/schemas/02_schema_knowledge_base.sql

echo "[init] 初始化 ${POSTGRES_DB} 库 schema（AI 报告持久化表）..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -f /docker-entrypoint-initdb.d/schemas/03_schema_ai_analysis_report.sql

echo "[init] 初始化 ${POSTGRES_DB} 库 schema（Agentic QA 应用数据，原 SQLite）..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -f /docker-entrypoint-initdb.d/schemas/04_schema_agentic_qa.sql

echo "[init] 完成。所有表已统一在 ${POSTGRES_DB} 库中。"
