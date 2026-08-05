# chaowei-agent 本地测试启动方法

1.编辑.env文件

```
# ========================================
# 测试环境配置
# ========================================

# 模型供应商（测试环境默认使用 DeepSeek）
PROVIDER=deepseek

# ========================================
# DeepSeek 配置 (PROVIDER=deepseek 时使用)
# ========================================
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=CHANGE_ME
DEEPSEEK_MODEL=deepseek-v4-flash

# ========================================
# Qwen (阿里灵积) 配置 (PROVIDER=qwen3 时使用)
# ========================================
QWEN3_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN3_API_KEY=sk-your-qwen-key-here
QWEN3_MODEL=qwen-plus

# ========================================
# OpenAI 配置 (PROVIDER=openai 时使用)
# ========================================
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-your-openai-key-here
OPENAI_MODEL=gpt-4

# ========================================
# 本地模型配置 (PROVIDER=local_qwen3 时使用)
# ========================================
LOCAL_QWEN3_BASE_URL=http://10.1.1.4:8001/v1
LOCAL_QWEN3_API_KEY=dummy-key
LOCAL_QWEN3_MODEL=qwen3.5-27b

# ========================================
# PostgreSQL 配置（测试环境）
# ========================================
POSTGRES_HOST=CHANGE_ME
POSTGRES_FALLBACK_HOST=CHANGE_ME
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=CHANGE_ME

# ========================================
# RAGFlow 知识库配置（测试环境）
# ========================================
RAGFLOW_BASE_URL=http://CHANGE_ME:9380
RAGFLOW_API_KEY=CHANGE_ME
RAGFLOW_CONVERSATION_ID=
RAGFLOW_DATASET_ID=c3f4e6dc325e11f1884379f023bc5255
RAGFLOW_MODEL=qwen-plus
RAGFLOW_EMBEDDING_MODEL=text-embedding-v4@Tongyi-Qianwen

# ========================================
# 上游系统配置（测试环境）
# ========================================
UPSTREAM_MOCK=false
UPSTREAM_BASE_URL=CHANGE_ME:18081
UPSTREAM_SECRET=CHANGE_ME
UPSTREAM_TIMEOUT=30
UPSTREAM_RETRY_COUNT=3

# ========================================
# 定时任务调度器配置（测试环境启用）
# ========================================

# 是否启用定时任务调度器
# true = 启用定时任务，按 cron 表达式自动执行
# false = 禁用定时任务，只能手动调用 API 触发
ENABLE_REPORT_SCHEDULER=true

# 精益早会日报定时执行的 cron 表达式
# 格式: 分钟 小时 日 月 周
# 示例:
#   "57 8 * * *"  = 每天早上 8:57 执行
#   "0 9 * * 1-5" = 工作日（周一到周五）早上 9:00 执行
#   "0 */2 * * *" = 每 2 小时执行一次
# 默认值: 57 8 * * *（每天早上 8:57）
LEAN_MORNING_DAILY_CRON=30 5 * * *

# 是否启用批量生成模式
# true  = 一次性生成所有车间/工序的早会日报（推荐生产环境使用）
# false = 单工序模式，只生成下面配置的单个车间/工序的报告
LEAN_MORNING_DAILY_BATCH_ENABLED=true

# 批量模式下指定要生成的车间 ID 列表（逗号分隔）
# 留空 = 生成所有车间的报告（默认）
# 示例: "1,2,3" = 只生成车间 1、2、3 的报告
# 测试环境建议配置少量车间，避免消耗过多资源
LEAN_MORNING_DAILY_WORKSHOP_IDS=1,2

# ─── 以下是单工序模式的配置（BATCH_ENABLED=false 时生效） ───

# 单工序模式下的默认车间 ID
# 仅当 LEAN_MORNING_DAILY_BATCH_ENABLED=false 时生效
LEAN_MORNING_DAILY_WORKSHOP_ID=1

# 单工序模式下的默认工序 ID
# 仅当 LEAN_MORNING_DAILY_BATCH_ENABLED=false 时生效
LEAN_MORNING_DAILY_PROCEDURE_ID=2

# ========================================
# 质量报告定时任务配置
# ========================================

# 质量日报定时执行的 cron 表达式
# 默认: 留空 = 禁用
QUALITY_DAILY_CRON=
QUALITY_WEEKLY_CRON=
QUALITY_MONTHLY_CRON=

# ========================================
# 设备效率报告定时任务配置
# ========================================

# 设备效率日报定时执行的 cron 表达式
# 格式: 分钟 小时 日 月 周
# 默认: 每天早上 5:20
DEVICE_EFFICIENCY_DAILY_CRON=0 6 * * *

# 设备效率周报定时执行的 cron 表达式
# 默认: 每周一早上 5:20
# 留空 = 禁用该定时任务
DEVICE_EFFICIENCY_WEEKLY_CRON=0 6 * * 1

# 设备效率月报定时执行的 cron 表达式
# 默认: 每月1号早上 5:20
# 留空 = 禁用该定时任务
DEVICE_EFFICIENCY_MONTHLY_CRON=0 6 1 * *

# 设备效率报告的车间 ID（可选，留空表示仅工厂级）
# 批量模式（优先）：逗号分隔多个车间 ID
# 示例: "1,2" = 同时生成车间 1 和车间 2 的报告
DEVICE_EFFICIENCY_WORKSHOP_IDS=1,2

# 单车间模式（批量为空时生效）
# 留空 = 仅工厂级报告
DEVICE_EFFICIENCY_WORKSHOP_ID=

# ========================================
# 日志级别（测试环境用 INFO）
# ========================================
LOG_LEVEL=INFO

# ========================================
# Agentic QA 智能问答平台
# ========================================
# 启用Agentic QA模块
ENABLE_SQL_QA=true

# MySQL（被查询的业务数据库）
AQA_MYSQL_HOST=CHANGE_ME
AQA_MYSQL_PORT=3306
AQA_MYSQL_USER=zxzz
AQA_MYSQL_PASSWORD=CHANGE_ME
AQA_MYSQL_DATABASE=jxcw

# Vanna
AQA_VANNA_MODEL=deepseek
AQA_VANNA_CHROMA_PATH=./backend/data/agentic_qa/vanna-knowledge
AQA_ENTITY_CHROMA_PATH=./backend/data/agentic_qa/entity-knowledge

# Neo4j（可选，不可用时自动降级）
AQA_NEO4J_URI=bolt://CHANGE_ME:7687
AQA_NEO4J_USER=neo4j
AQA_NEO4J_PASSWORD=CHANGE_ME

# 应用配置
AQA_APP_ENV=development
AQA_APP_SECRET_KEY=dev-secret-change-in-production
AQA_DATABASE_URL=sqlite:///./backend/data/agentic_qa/system_data/app.db
AQA_GRAPH_MAPPING_PATH=config/graph_mapping.yaml

# ========================================
# ENABLE_KNOWLEDGE 知识库管理平台
# ========================================
# 启用知识库管理模块
ENABLE_KNOWLEDGE_BASE=true

# PostgreSQL（知识库专用）
KNB_PG_HOST=localhost
KNB_PG_PORT=5432
KNB_PG_DB=knowledge_base
KNB_PG_USER=zxzz
KNB_PG_PASSWORD=CHANGE_ME

# Redis
KNB_REDIS_URL=redis://localhost:6379/1

# MinIO 对象存储
KNB_MINIO_ENDPOINT=localhost:9000
KNB_MINIO_ACCESS_KEY=CHANGE_ME
KNB_MINIO_SECRET_KEY=CHANGE_ME
KNB_MINIO_BUCKET=knowledge-base


# ========================================
# PLC 解析服务配置
# ========================================
# PLC解析模型API配置
PLC_DASHSCOPE_API_KEY=CHANGE_ME
PLC_DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 模型配置
PLC_VISION_MODEL=qwen3-vl-plus
PLC_TEXT_MODEL=qwen3.7-plus

 # 超时配置（秒）
PLC_VISION_TIMEOUT=120.0
PLC_TEXT_TIMEOUT=180.0
PLC_MAX_RETRIES=3

# PDF 处理配置
PLC_PDF_DPI=300
```

2.手动启动docker镜像依赖：

```
cd docker

docker compose up -d knb-postgresql knb-redis knb-minio
```

3.在项目根目录启动前后端与celery队列

```bash
./start.bat --model deepseek
```

​
