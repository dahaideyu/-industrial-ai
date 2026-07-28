# chaowei-agent 后端架构说明

## 项目概述

这是一个 AI 设备监控与分析平台后端，基于 **FastAPI** 框架构建，采用模块化架构设计。

---

## 目录结构

```
backend/
├── app.py                          # FastAPI 应用入口（50行）
│
├── core/                           # 核心基础设施层
│   ├── config.py                   # 配置加载（环境变量、模型配置）
│   ├── database.py                 # SQLite 数据库操作
│   ├── response.py                 # 统一响应格式
│   ├── scheduler.py                # APScheduler 定时任务调度器
│   ├── job_logger.py               # 作业级日志管理
│   └── singletons.py               # 单例工厂（管理全局实例）
│
├── clients/                        # 外部服务客户端层
│   ├── upstream_client.py          # 上游系统 HTTP 客户端（拉参/回调）
│   └── ragflow_client.py           # RAGFlow 知识库客户端（检索/对话）
│
├── services/                       # 共享服务层
│   └── report_generator.py         # 报告生成器（LLM 调用 + RAGFlow 检索）
│
├── modules/                        # 业务模块层（按业务域划分）
│   ├── daily_report/               # 日报分析模块（基础）
│   ├── lean_morning_daily/         # 精益早会日报模块
│   ├── quality_overview/           # 质量概览报告模块
│   ├── device_efficiency/          # 设备效率报告模块
│   ├── report_management/          # 报告管理模块（查询/下载/调试）
│   ├── maintenance_report/         # 预测性维护报告模块
│   ├── device_warning/             # 设备预警模块
│   ├── device_param/               # 设备参数监控模块
│   ├── document_analysis/          # 文档分析模块
│   └── repair_suggestion/          # 维修建议模块
│
├── routes/                         # 路由汇总层（兼容旧路由）
│   ├── health.py                   # 健康检查
│   ├── report.py                   # 报告路由
│   ├── analysis.py                 # 分析路由
│   ├── jobs.py                     # 作业路由
│   ├── document.py                 # 文档路由
│   └── alarms.py                   # 报警路由
│
├── prompts/                        # 兼容层提示词
│   └── loader.py                   # 提示词加载器
│
└── tools/                          # 工具脚本
    ├── device_analyzer.py          # 设备分析工具
    └── migrate_mysql_to_timescale.py  # 数据迁移工具
```

---

## 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                      应用层 (app.py)                         │
│              FastAPI 应用工厂、生命周期管理、路由注册          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    业务模块层 (modules/)                      │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ lean_morning│ │   quality   │ │   device    │  ...      │
│  │   _daily    │ │  _overview  │ │ _efficiency │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
│         │               │               │                   │
│         └───────────────┼───────────────┘                   │
│                         ▼                                   │
│               每个模块包含：                                  │
│               - routes.py    (API 路由)                     │
│               - worker.py    (作业编排)                     │
│               - prompts/     (提示词模板)                    │
│               - services/    (模块服务)                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     共享服务层 (services/)                    │
│               report_generator.py (报告生成器)               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     外部客户端层 (clients/)                   │
│     upstream_client.py          ragflow_client.py           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      核心基础设施层 (core/)                   │
│  config.py  database.py  scheduler.py  response.py  ...    │
└─────────────────────────────────────────────────────────────┘
```

---

## 依赖关系

```
modules/ ──────► core/, services/, clients/
                         │
services/ ─────► core/, clients/
                         │
clients/  ─────► (无外部依赖)
                         │
core/     ─────► (无外部依赖)
```

**重要规则**：
- `modules/` 可以依赖 `core/`, `services/`, `clients/`
- `modules/` 之间**不能**相互依赖
- `core/` 和 `services/` **不能**依赖 `modules/`

---

## 核心模块说明

### 1. 应用入口 (app.py)

```python
# 职责：
- 解析命令行参数（-e 配置文件，-m 模型供应商）
- 加载环境变量
- 创建 FastAPI 应用
- 注册所有模块路由
- 管理应用生命周期（启动/关闭）
- 初始化调度器

# 启动方式：
python backend/app.py -e .env.test -m deepseek
```

### 2. 核心基础设施 (core/)

| 文件 | 职责 | 主要函数/类 |
|------|------|------------|
| config.py | 配置加载 | `load_config()`, `CONFIG` |
| database.py | 数据库操作 | `init_db()`, `upsert_report()`, `query_reports()` |
| response.py | 统一响应 | `success_response()`, `error_response()` |
| scheduler.py | 定时调度 | `init_scheduler()`, `get_scheduler()` |
| job_logger.py | 作业日志 | `JobLogger` |
| singletons.py | 单例管理 | `get_upstream_client()`, `get_report_generator_singleton()` |

### 3. 外部客户端 (clients/)

| 文件 | 职责 | 主要方法 |
|------|------|---------|
| upstream_client.py | 上游系统交互 | `pull_*_params()`, `callback_complete()` |
| ragflow_client.py | RAGFlow 知识库 | `stream()`, `retrieve()`, `download_document()` |

### 4. 共享服务 (services/)

| 文件 | 职责 | 主要方法 |
|------|------|---------|
| report_generator.py | 报告生成引擎 | `generate_reports_stream()`, `generate_report_with_citation()` |

---

## 业务模块详解

### 模块1: 精益早会日报 (lean_morning_daily)

**功能**：生成精益早会日报，支持单工序和批量模式

**API 路由**：
- `POST /api/agent/trigger` - 手动触发单工序作业
- `POST /api/agent/trigger/batch` - 批量触发所有车间
- `GET /api/agent/jobs/{job_id}` - 查询作业状态
- `POST /api/factory-report/generate` - 同步生成工厂级报告
- `POST /api/factory-report/trigger` - 异步触发工厂级报告

**核心文件**：
```
lean_morning_daily/
├── routes.py          # 路由定义
├── worker.py          # AgentWorker（作业编排）
└── prompts/           # 6个提示词模板
    ├── lean_morning_daily_report01/02/03.txt
    └── factory_morning_daily_report01/02/03.txt
```

**作业流程**：
```
拉参 → 加载历史 → 生成3份报告 → 持久化 → 回调上游
```

---

### 模块2: 质量概览报告 (quality_overview)

**功能**：生成质量日/周/月报告

**API 路由**：
- `POST /api/quality_overview` - 触发日周月报告
- `POST /api/quality_overview/daily` - 触发日报
- `POST /api/quality_overview/weekly` - 触发周报
- `POST /api/quality_overview/monthly` - 触发月报

**核心文件**：
```
quality_overview/
├── routes.py          # 路由定义
├── worker.py          # QualityOverviewWorker
└── prompts/           # 9个提示词模板
    ├── quality_daily_report01/02/03.txt
    ├── quality_weekly_report01/02/03.txt
    └── quality_monthly_report01/02/03.txt
```

---

### 模块3: 设备效率报告 (device_efficiency)

**功能**：生成设备效率日/周/月报告，支持工厂级和车间级

**API 路由**：
- `POST /api/device-efficiency/daily` - 触发日报
- `POST /api/device-efficiency/weekly` - 触发周报
- `POST /api/device-efficiency/monthly` - 触发月报

**核心文件**：
```
device_efficiency/
├── routes.py          # 路由定义
├── worker.py          # DeviceEfficiencyWorker
└── prompts/           # 18个提示词模板
    ├── device_factory_daily/weekly/monthly_report01/02/03.txt
    └── device_workshop_daily/weekly/monthly_report01/02/03.txt
```

---

### 模块4: 报告管理 (report_management)

**功能**：报告查询、下载、调试

**API 路由**：
- `POST /api/reports/query` - 分页查询报告列表
- `POST /api/reports/detail` - 查询报告详情
- `POST /api/document/download` - 代理下载 RAGFlow 文档
- `GET /api/env/debug` - 环境配置调试

**核心文件**：
```
report_management/
└── routes.py          # 路由定义
```

---

### 其他模块

| 模块 | 功能 | 说明 |
|------|------|------|
| maintenance_report | 预测性维护报告 | 生成设备维护建议报告 |
| device_warning | 设备预警 | AI 异常检测、故障预测 |
| device_param | 设备参数监控 | 实时数据查询、运行分析 |
| document_analysis | 文档分析 | RAGFlow 文档解析 |
| repair_suggestion | 维修建议 | 工单评分、维修建议生成 |
| daily_report | 日报分析 | 基础报告生成（被其他模块使用） |

---

## 数据流向

### 报告生成流程

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  上游系统    │────►│  拉参接口    │────►│   Worker    │
│ (外部数据源) │     │ (upstream)  │     │  (作业编排) │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    ▼                          ▼                          ▼
            ┌─────────────┐           ┌─────────────┐           ┌─────────────┐
            │  加载历史    │           │  生成报告    │           │  持久化     │
            │  上下文     │           │  (LLM)      │           │  (SQLite)   │
            └─────────────┘           └──────┬──────┘           └─────────────┘
                                             │
                                             ▼
                                    ┌─────────────────┐
                                    │  回调上游系统    │
                                    │  (报告结果)     │
                                    └─────────────────┘
```

### 报告类型

每种报告类型通常生成 **3 份报告**：

1. **基础报告** (01) - 注入原始数据，生成基础分析
2. **趋势分析** (02) - 使用前序报告上下文 + 历史报告
3. **改善建议** (03) - 使用前序报告上下文 + RAGFlow 知识库

---

## 调度器配置

通过环境变量配置定时任务：

```bash
# 精益早会日报
LEAN_MORNING_DAILY_CRON=57 8 * * *          # 每天 8:57
LEAN_MORNING_DAILY_BATCH_ENABLED=true       # 启用批量模式
LEAN_MORNING_DAILY_WORKSHOP_IDS=1,2,3       # 指定车间（空=全部）

# 质量概览报告
QUALITY_DAILY_CRON=0 6 * * *               # 每天 6:00
QUALITY_WEEKLY_CRON=0 6 * * 1              # 每周一 6:00
QUALITY_MONTHLY_CRON=0 6 1 * *             # 每月1号 6:00

# 设备效率报告
DEVICE_EFFICIENCY_DAILY_CRON=0 6 * * *     # 每天 6:00
DEVICE_EFFICIENCY_WEEKLY_CRON=0 6 * * 1    # 每周一 6:00
DEVICE_EFFICIENCY_MONTHLY_CRON=0 6 1 * *   # 每月1号 6:00

# 启用调度器
ENABLE_REPORT_SCHEDULER=true
```

---

## 启动方式

### 开发环境

```bash
# 方式1：直接运行
python backend/app.py -e .env.test -m deepseek

# 方式2：使用 uvicorn（支持热重载）
uvicorn backend.app:app --host 0.0.0.0 --port 9300 --reload

# 方式3：使用启动脚本
run_backend.bat          # Windows
.\run_backend.ps1        # PowerShell
```

### 生产环境

```bash
# PM2 启动
pm2 start ecosystem.config.js --env deepseek

# Docker 启动
docker-start.sh
```

### PyCharm 配置

```
Name: AI Report 服务
Script path: D:\资料\文件\专心代码库\report_agent\backend\app.py
Parameters: -e .env.test -m deepseek
Working directory: D:\资料\文件\专心代码库\report_agent
```

---

## 环境配置文件

| 文件 | 用途 |
|------|------|
| .env | 默认配置（测试环境） |
| .env.test | 测试环境配置 |
| .env.prod | 生产环境配置 |
| .env.prod.shandong | 山东工厂配置 |
| .env.prod.jiangxi | 江西工厂配置 |

---

## API 文档

启动服务后访问：
- Swagger UI: http://localhost:9300/docs
- ReDoc: http://localhost:9300/redoc

---

## 开发指南

### 添加新模块

1. 在 `backend/modules/` 下创建新目录
2. 创建 `__init__.py`、`routes.py`、`worker.py`
3. 在 `app.py` 中注册路由：
   ```python
   from modules.new_module import new_module_router
   app.include_router(new_module_router)
   ```

### 添加新 API

1. 在模块的 `routes.py` 中定义路由
2. 使用 `success_response()` 和 `error_response()` 返回统一格式
3. 后台异步任务使用 `threading.Thread`

### 添加新提示词

1. 在模块的 `prompts/` 目录下创建 `.txt` 文件
2. 在 `loader.py` 中添加映射关系

---

## 常见问题

**Q: 导入模块失败？**
A: 确保 `backend/` 目录在 `sys.path` 中，或使用相对导入

**Q: 数据库路径错误？**
A: 检查 `core/database.py` 中的 `DEFAULT_DB_PATH` 配置

**Q: 调度器未启动？**
A: 确保 `ENABLE_REPORT_SCHEDULER=true` 环境变量已设置

**Q: 模型配置错误？**
A: 检查 `PROVIDER` 环境变量和对应的 `{PROVIDER}_BASE_URL`、`{PROVIDER}_API_KEY`