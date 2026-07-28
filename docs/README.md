# 工业 AI 分析平台

> 前后端分离的工业智能分析系统。后端按业务拆分为三大模块：日报分析、设备预警、文档分析接口。

---

## 一、项目概述

系统面向工业生产场景，通过 LLM 与设备数据分析能力提供报告生成、设备预警和文档解析接口。

### 技术栈

| 层级 | 技术栈 | 说明 |
|-----|--------|------|
| 前端 | Vue 3 + Vite + Tailwind CSS | 单页应用 |
| 后端 | FastAPI + Uvicorn | REST API + SSE |
| AI | LangChain + ChatOpenAI | 支持多供应商 LLM |

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
│   │   └── document_analysis/            # 模块3：文档分析接口
│   │       └── routes.py                 # /api/document_analysis
│   ├── routes/                           # 兼容层路由转发
│   ├── services/                         # 兼容层服务转发
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

---

## 四、API 列表

### 模块1：日报分析

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/templates` | GET | 列出可用报告模板 |
| `/api/ai_report` | POST | 基于模板流式生成报告（SSE） |

### 模块2：设备预警

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

> 报警分析 API 详细文档见 [alarm_analysis_api.md](./alarm_analysis_api.md)

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

> 预测性维护报告系统详细文档见 [predictive_maintenance_architecture.md](./predictive_maintenance_architecture.md)

### 通用接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |

---

## 五、扩展建议

1. 日报模板扩展：在 `backend/modules/daily_report/prompts/` 新增模板并更新 `loader.py`。
2. 设备预警能力扩展：在 `backend/modules/device_warning/ai_analysis/` 增加算法模块。
3. 文档分析增强：可在 `backend/modules/document_analysis/` 增加 OCR、结构抽取、向量检索能力。
