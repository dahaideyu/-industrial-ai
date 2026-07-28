# 工业 AI 分析平台

> 前后端分离的工业智能分析系统。后端按业务拆分为四大模块：日报分析、设备预警、文档分析接口、预测性维护报告。

---

## 一、项目概述

系统面向工业生产场景，通过 LLM 与设备数据分析能力提供报告生成、设备预警和文档解析接口。

### 技术栈

| 层级 | 技术栈 | 说明 |
|-----|--------|------|
| 前端 | Vue 3 + Vite + Tailwind CSS | 单页应用 |
| 后端 | FastAPI + Uvicorn | REST API + SSE |
| AI | LangChain + ChatOpenAI | 支持多供应商 LLM |
| 数据库 | PostgreSQL / TimescaleDB | 设备时序数据与报警存储 |

---

## 二、项目结构

```text
chaowei-agent/
├── frontend/
├── backend/
│   ├── app.py
│   ├── core/
│   ├── data/
│   ├── modules/
│   │   ├── daily_report/                 # 模块1：日报分析
│   │   │   ├── routes.py                 # /api/ai_report, /api/templates
│   │   │   ├── services/
│   │   │   │   └── report_generator.py
│   │   │   └── prompts/
│   │   │       ├── loader.py
│   │   │       └── *.txt
│   │   ├── device_warning/               # 模块2：设备预警
│   │   │   ├── analysis_routes.py        # /api/device_analysis*
│   │   │   ├── jobs_routes.py            # /api/jobs*
│   │   │   ├── services/
│   │   │   │   ├── device_analyzer.py
│   │   │   │   └── job_manager.py
│   │   │   └── ai_analysis/              # 设备分析算法
│   │   ├── document_analysis/            # 模块3：文档分析接口
│   │   │   └── routes.py                 # /api/document_analysis
│   │   └── maintenance_report/           # 模块4：预测性维护报告
│   │       ├── routes.py                 # /api/maintenance-reports/*
│   │       ├── services/
│   │       │   ├── data_aggregator.py
│   │       │   ├── analysis_integrator.py
│   │       │   ├── report_generator.py
│   │       │   └── scheduler.py
│   │       └── prompts/
│   │           ├── loader.py
│   │           └── *.txt
│   ├── routes/                           # 兼容层路由转发（含 /api/alarms*）
│   ├── services/                         # 兼容层服务转发
│   ├── core/knowledge_management/        # 知识库管理核心层
│   ├── clients/knowledge_management/     # 知识库管理外部客户端
│   ├── services/knowledge_management/    # 知识库管理服务层
│   ├── routes/knowledge_management/      # 知识库管理 API 路由
│   └── prompts/                          # 兼容层提示词转发
├── docs/
└── ecosystem.config.js
```

说明：
- `routes/`、`services/`、`prompts/` 保留为兼容层，避免旧导入路径失效。
- 新功能应优先放入 `backend/modules/<module_name>/`。

---

## 三、快速开始

### 环境要求

- Python 3.10+
- Node.js 18+

### 1. 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 配置环境变量

在项目根目录创建 `.env`：

```bash
PROVIDER=deepseek

DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_MODEL=deepseek-chat

POSTGRES_HOST=10.1.2.227
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-password
```

### 4. 启动服务

后端：

```bash
cd backend
python app.py
```

前端：

```bash
cd frontend
npm run dev
```

### 5. Docker Compose 部署

```bash
docker compose up -d
```

前端与后端统一通过 **9300** 端口访问（Nginx 反向代理）：
- 前端页面：`http://localhost:9300/`
- 后端 API：`http://localhost:9300/api/`

### 6. 知识库管理模块（可选）

知识库管理模块需要额外的基础设施服务。启用方式：

```bash
# 在 .env 中启用
ENABLE_KNOWLEDGE_BASE=true

# 启动基础设施
docker compose up -d knb-postgresql knb-redis knb-minio knb-tika knb-libreoffice knb-celery-worker
```

> 详细部署说明见 [docs/features/knowledge-management/DEPLOYMENT.md](./docs/features/knowledge-management/DEPLOYMENT.md)

---

## 四、API 列表

### 模块1：日报分析

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/templates` | GET | 列出可用报告模板 |
| `/api/ai_report` | POST | 基于模板流式生成报告（SSE） |

### 模块2：设备预警 & 报警分析

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/device_analysis/modules` | GET | 列出设备分析模块 |
| `/api/device_analysis` | POST | 执行设备分析 |
| `/api/jobs` | GET | 获取 Job 列表 |
| `/api/jobs/summary` | GET | 获取 Job 统计摘要 |
| `/api/jobs/{job_name}` | GET | 获取指定 Job 历史 |
| `/api/alarms` | GET | 分页查询报警记录 |
| `/api/alarms/statistics` | GET | 获取报警统计信息 |
| `/api/alarms/analysis` | POST | 执行报警分析（SQL统计+AI检测） |
| `/api/alarms/devices` | GET | 获取报警设备列表 |
| `/api/alarms/types` | GET | 获取报警类型定义 |

> 报警分析 API 详细文档见 [docs/alarm_analysis_api.md](./docs/alarm_analysis_api.md)
>
> 报警分析系统架构文档见 [docs/alarm_analysis_architecture.md](./docs/alarm_analysis_architecture.md)

### 模块3：文档分析接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/document_analysis` | POST | 文档基础分析（字数、行数、关键词） |

### 模块4：预测性维护报告

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/maintenance-reports/generate` | POST | 生成单台设备报告 |
| `/api/maintenance-reports/generate/stream` | POST | 流式生成报告（SSE） |
| `/api/maintenance-reports/generate/batch` | POST | 批量生成报告（后台任务） |
| `/api/maintenance-reports/list` | GET | 查询报告列表 |
| `/api/maintenance-reports/detail/{id}` | GET | 获取报告详情 |
| `/api/maintenance-reports/schedule/trigger` | POST | 手动触发报告生成 |
| `/api/maintenance-reports/schedule/status` | GET | 获取调度器状态 |

> 预测性维护报告系统详细文档见 [docs/predictive_maintenance_architecture.md](./docs/predictive_maintenance_architecture.md)

### 模块5：知识库管理（可选模块）

> 通过 `ENABLE_KNOWLEDGE_BASE=true` 启用，需要 PostgreSQL、Redis、MinIO 等基础设施。

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/knowledge-management/bases` | GET/POST | 知识库列表 / 创建知识库 |
| `/api/knowledge-management/bases/{id}` | GET/PUT/DELETE | 知识库详情 / 更新 / 删除 |
| `/api/knowledge-management/bases/{id}/categories` | GET/POST | 文档类别管理 |
| `/api/knowledge-management/bases/{id}/targets` | GET/POST | 收集对象管理 |
| `/api/knowledge-management/bases/{id}/plans` | GET/POST | 收集计划管理 |
| `/api/knowledge-management/documents` | POST | 上传文档 |
| `/api/knowledge-management/documents/{id}/review` | POST | AI 审核 |
| `/api/knowledge-management/documents/{id}/approve` | POST | 人工审批 |
| `/api/knowledge-management/documents/{id}/publish` | POST | 发布到知识库 |
| `/api/knowledge-management/documents/{id}/chunks` | GET | 查看文档切片 |

> 知识库管理模块详细文档见 [docs/features/knowledge-management/README.md](./docs/features/knowledge-management/README.md)

### 通用接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |

---

## 五、详细文档索引

| 文档 | 说明 |
|------|------|
| [docs/alarm_analysis_api.md](./docs/alarm_analysis_api.md) | 报警分析 API 接口文档 |
| [docs/alarm_analysis_architecture.md](./docs/alarm_analysis_architecture.md) | 报警分析系统架构与逻辑 |
| [docs/predictive_maintenance_architecture.md](./docs/predictive_maintenance_architecture.md) | 预测性维护报告系统架构 |
| [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) | 部署指南 |
| [docs/features/knowledge-management/README.md](./docs/features/knowledge-management/README.md) | 知识库管理模块概览 |
| [docs/features/knowledge-management/DEPLOYMENT.md](./docs/features/knowledge-management/DEPLOYMENT.md) | 知识库管理部署指南 |
| [docs/features/knowledge-management/USER_GUIDE.md](./docs/features/knowledge-management/USER_GUIDE.md) | 知识库管理用户手册 |

---

## 六、扩展建议

1. 日报模板扩展：在 `backend/modules/daily_report/prompts/` 新增模板并更新 `loader.py`。
2. 设备预警能力扩展：在 `backend/modules/device_warning/ai_analysis/` 增加算法模块。
3. 文档分析增强：可在 `backend/modules/document_analysis/` 增加 OCR、结构抽取、向量检索能力。
4. 预测性维护前端完善：报告列表、详情、车间汇总等查询接口尚待前端页面开发。
