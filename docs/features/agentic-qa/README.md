# 工业数据智能问答平台 — 开发者文档

面向工业场景的 NL2SQL 智能问答平台，支持自然语言查询设备、产线、维修工单、点检记录等核心数据，并可融合设备文档进行辅助问答。

## 目录

- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [核心设计](#核心设计)
  - [ReAct 编排循环](#react-编排循环)
  - [预处理层](#预处理层)
  - [工具集](#工具集)
  - [Vanna NL2SQL 引擎](#vanna-nl2sql-引擎)
  - [SQL 安全检查](#sql-安全检查)
  - [RAGFlow 集成](#ragflow-集成)
  - [WebSocket 实时推送](#websocket-实时推送)
- [数据层](#数据层)
  - [MySQL 业务数据库](#mysql-业务数据库)
  - [ChromaDB 向量存储](#chromadb-向量存储)
  - [嵌入模型](#嵌入模型)
- [API 设计](#api-设计)
- [前端架构](#前端架构)
- [配置管理](#配置管理)
- [本地开发](#本地开发)
- [扩展指南](#扩展指南)
- [常见问题](#常见问题)

---

## 系统架构

SQL-QA 作为 chaowei-agent 的可选功能模块，通过 `ENABLE_SQL_QA=true` 环境变量启用。

```
用户 Web 端 (Vue 3 + Vite)
        │ HTTP REST + WebSocket
┌───────▼──────────────────────────────────────────┐
│              FastAPI 统一入口 (app.py)              │
│  - JWT 认证中间件                                   │
│  - 功能开关: ENABLE_SQL_QA 控制 SQL-QA 路由加载     │
│  - CORS 中间件                                      │
│  - 启动时初始化 Vanna Agent + 数据库 + 种子用户      │
└───────┬──────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────┐
│               ReAct 编排循环 (master_loop.py)      │
│                                                    │
│  预处理层（无LLM, ~300ms）                          │
│    ├─ 实体向量搜索 (ChromaDB)                       │
│    └─ Schema 关键词匹配 (Vanna)                     │
│       │                                            │
│       ▼                                            │
│  增强 ReAct 循环 (MAX 6轮)                          │
│    │ 每轮: LLM 思考 → 工具调用 → 结果 → 下一轮      │
│    │                                               │
│    ├─ 实体模糊 → ask_clarification → 用户多选      │
│    ├─ 意图模糊 → ask_clarification → 反问          │
│    ├─ 生成SQL → execute_sql → 数据                 │
│    └─ 有数据 → 立即回答 + 追问建议                  │
│                                                    │
│  实时推送: 思考过程 + 执行步骤 (WebSocket)           │
└───────┬──────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────┐
│                  数据层                            │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │  MySQL   │  │  SQLite  │  │  ChromaDB × 2  │  │
│  │ (jxcw)   │  │ (app.db) │  │  - vanna-kb    │  │
│  └──────────┘  └──────────┘  │  - entity-kb   │  │
│                               └────────────────┘  │
│  ┌──────────────────────┐                        │
│  │  RAGFlow (外部服务)   │                        │
│  └──────────────────────┘                        │
│  ┌──────────────────────┐                        │
│  │  Neo4j (可选外部)     │                        │
│  └──────────────────────┘                        │
└──────────────────────────────────────────────────┘
```

### 核心数据流

```
用户提问 (需 JWT 认证)
  → 预处理 (实体向量 + Schema 匹配, 不依赖 LLM)
  → ReAct 循环:
       ├─ 实体模糊 → ask_clarification → 用户多选（含全选 + 手动输入）
       ├─ 多数据源歧义 → 反问用户选哪种
       ├─ 生成完整 JOIN SQL → 执行 → 拿到数据
       └─ 立刻回答 + 追问建议 (纯文本 + 表格 + 图表 + SQL)
  
  实时推送: 思考过程纯文本流式 + 执行步骤条 (WebSocket)
```

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 前端 | Vue 3 + Vite 5 | SPA 单页应用 |
| 后端 | FastAPI (Python 3.12+) | 异步 REST API + WebSocket |
| 认证 | JWT (python-jose) + bcrypt | 用户登录认证, 24h 有效期 |
| ORM | SQLAlchemy + SQLite | 用户/会话/消息持久化 |
| AI 编排 | ReAct Loop (自研) | LLM 工具调用循环, 自主决策 + 自我修正 |
| NL2SQL | Vanna 2.0 + ChromaDB | 向量记忆检索 + SQL 生成 |
| LLM | DeepSeek (OpenAI 兼容) | SQL 生成 / 意图理解 / 实体消歧 / 结果总结 |
| 图数据库 | Neo4j (可选) | 知识图谱实体消歧, 不可用时自动降级 |
| 文档问答 | RAGFlow | 设备手册 / 维修文档检索 |
| 向量嵌入 | BAAI/bge-small-zh-v1.5 (768维) | 中文语义向量 |
| 业务数据库 | MySQL (jxcw) | 工业过程数据, pymysql + DictCursor |
| 实时通信 | WebSocket | 思考过程 + 执行步骤实时推送 |
| 图表 | 自定义 Chart 组件 | 数据分析图表 |
| 包管理 | uv (Python), npm (前端) | 依赖管理 |
| SQL 解析 | sqlglot | SQL 语法树分析与安全检查 |

---

## 项目结构

> SQL-QA 作为 chaowei-agent 的可选功能模块，代码分布在以下命名空间中。

```
chaowei-agent/
├── backend/
│   ├── app.py                          # 统一入口 (ENABLE_SQL_QA 控制 SQL-QA 路由加载)
│   ├── core/agentic_qa/                # SQL-QA 核心基础设施
│   │   ├── config.py                   # Pydantic Settings
│   │   ├── database.py                 # SQLAlchemy engine + session (SQLite)
│   │   ├── llm.py                      # DeepSeek LLM 封装 (OpenAI SDK)
│   │   ├── graph_client.py             # Neo4j 图数据库客户端
│   │   ├── graph_importer.py           # MySQL + YAML → Neo4j 图谱导入
│   │   └── logger.py                   # 按天轮转日志
│   ├── routes/agentic_qa/              # API 路由
│   │   ├── routes.py                   # /api/query, /api/query/confirm
│   │   ├── auth.py                     # /api/auth/login, /api/auth/me
│   │   ├── sessions.py                 # 会话 CRUD
│   │   ├── dependencies.py             # get_current_user 依赖注入
│   │   ├── admin.py                    # 管理后台 (记忆库/训练/实体/图谱/统计)
│   │   └── websocket.py               # WebSocket 实时推送
│   ├── services/
│   │   ├── agentic_qa/                 # ReAct 编排循环 (核心)
│   │   │   ├── master_loop.py          # ReAct 主循环 (工具调用 + 结果处理)
│   │   │   ├── master_prompt.py        # 结构化角色提示词
│   │   │   ├── tools.py                # 工具集 (generate_sql, execute_sql, 等)
│   │   │   └── preprocess.py           # 预处理层 (实体搜索 + Schema 匹配)
│   │   ├── agentic_qa/agents/          # 工具的实际实现
│   │   │   ├── sql_agent.py            # SQL 生成 + 执行
│   │   │   ├── entity_resolver.py      # 实体消歧 + 别名管理
│   │   │   ├── analysis_agent.py       # 数据分析 + Chart 生成
│   │   │   ├── rag_agent.py            # RAGFlow 文档查询
│   │   │   └── general_agent.py        # 通用问答
│   │   └── ...
│   └── data/agentic_qa/                # 运行时数据
│       ├── entity-knowledge/           # 实体 ChromaDB 向量库
│       ├── vanna-knowledge/            # Vanna 记忆 ChromaDB 向量库
│       └── system_data/                # 应用数据库 SQLite
├── frontend/src/
│   ├── views/sql_qa/                   # SQL-QA Vue 组件
│   ├── composables/sql_qa/             # 状态管理
│   └── api/sqlQaClient.js              # API 客户端
├── docker/                             # Docker 部署文件
├── config/                             # 配置文件 (graph_mapping.yaml, .env 模板)
├── start.sh / start.bat                # 一键启动脚本
└── pyproject.toml                      # uv 依赖管理
```

---

## 核心设计

### ReAct 编排循环

核心编排在 `backend/services/agentic_qa/master_loop.py`，采用 LLM 原生工具调用 (function calling)：

```
用户问题 + 预处理上下文
  → ReAct 循环 (MAX 6轮):
       每轮: LLM 思考 (content) → 调用工具 (tool_calls) → 获取结果 → 下一轮
       
       决策框架:
       ├─ Q1: 问题清晰可生成 SQL? → 直接 generate_sql
       ├─ Q2: 实体名模糊? → ask_clarification (多选 + 全选 + 手动输入)
       ├─ Q3: 同一概念多数据源? → ask_clarification (反问用户)
       └─ Q4: 意图不明确? → ask_clarification (给选项)
       
       行动原则:
       ├─ 一次生成完整 JOIN SQL (不零碎查询)
       ├─ 有结果立刻回答 + 追问建议
       └─ 失败 → diagnose → 重试一次 → 换思路
```

**关键组件**：

| 文件 | 职责 |
|------|------|
| `master_loop.py` | ReAct 主循环, 工具调用编排, 追问解析, 思考流式推送 |
| `master_prompt.py` | 角色定义 + 决策框架 + 行动指南 + 思考要求 + 自我校验 |
| `tools.py` | 工具集 (generate_sql, execute_sql, ask_clarification, 等) |
| `preprocess.py` | 预处理层 (实体向量搜索 + Schema 匹配, 不依赖 LLM) |

### 预处理层

在 ReAct 循环启动前，并行执行两个纯算法搜索，结果注入 system prompt：

| 预处理 | 方式 | 耗时 |
|--------|------|------|
| 实体候选 | ChromaDB 向量搜索 Top-5 | ~200ms |
| 相关表 Schema | Vanna 关键词检索 | ~50ms |

预处理上下文让 LLM 不需要再调 `search_entities` / `get_schema`，直接进入决策。

### 工具集

| 工具 | 用途 |
|------|------|
| `generate_sql` | Vanna 记忆检索 → LLM 生成 SQL |
| `execute_sql` | 安全检查 → 执行 SQL → 返回数据 |
| `ask_clarification` | 实体多选 / 意图反问 (支持全选 + 手动输入) |
| `diagnose_sql_error` | LLM 诊断 SQL 错误并修正 |
| `typo_check` | 检查实体名拼写错误 |
| `analyze_data` | 生成数据洞察 + Chart 配置 |
| `query_rag` | RAGFlow 文档检索 |
| `search_entities` | 向量搜索实体 (预处理已覆盖, 按需调用) |
| `get_schema` | 获取表结构 (预处理已覆盖, 按需调用) |

### Vanna NL2SQL 引擎

定义在 `backend/vanna_integration/`，核心组件：

**VannaAgentManager** (`agent.py`)：单例模式管理 Vanna Agent 生命周期。
- 使用 `ChromaAgentMemory` 作为向量存储后端
- 支持 SQL 对记忆和文档记忆两种类型
- 提供 `train()`, `get_memories()`, `edit_memory()`, `delete_memory()` 等操作方法

**Enhancers** (`enhancers.py`)：在 LLM 生成 SQL 前注入上下文：
- `MemoryRetrievalEnhancer`：从 ChromaDB 检索相似历史问答
- `SchemaContextEnhancer`：检索相关表结构定义
- `CombinedEnhancer`：合并以上两者，统一注入提示词

**DeepSeekLlmService** (`deepseek_llm.py`)：适配 Vanna 的 `LlmService` 接口，封装 DeepSeek API 调用。

### SQL 安全检查

定义在 `backend/services/agentic_qa/vanna/guard.py`，双层校验：

1. **关键词黑名单**：拦截 `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `REPLACE`
2. **sqlglot 语法树分析**：解析 SQL 为 AST，确保最外层语句是 `SELECT`
3. **自动修正**：强制添加 `LIMIT` 限制（如未指定）

通过 Vanna 的 `LifecycleHook` 机制在 SQL 执行前自动触发。

### RAGFlow 集成

定义在 `backend/services/agentic_qa/ragflow/client.py` 和 `backend/services/agentic_qa/agents/rag_agent.py`：

- 使用 RAGFlow 的对话 API (SSE 流式)
- 支持解析思考过程、引用块和最终回答
- 代理文档下载：后端转发 RAGFlow 文档流，避免前端跨域问题
- 前端 PDF 预览：使用 pdfjs-dist 渲染，支持分页浏览

### WebSocket 实时推送

定义在 `backend/routes/agentic_qa/websocket.py`：

- 连接路径：`/api/ws/{session_id}`
- 消息格式：`{ type: "step_update" | "complete", step, status, message, elapsed_ms }`
- 前端在 `useChat.ts` 中建立连接，逐步累积步骤列表
- 完成后自动折叠为摘要栏，点击可展开详情

---

## 数据层

### MySQL 业务数据库

通过 `backend/services/agentic_qa/db/mysql.py` 的连接池访问：

```python
# 使用 pymysql + DictCursor, 返回字典格式
# 自动为 sys_line 和 dev_device 表添加 del_flag=0 条件
```

两张家用核心表：

| 表名 | 逻辑实体 | 关键字段 |
|------|----------|----------|
| `sys_line` | 产线 | id, name, type, del_flag |
| `dev_device` | 设备 | id, name, short_no, device_type, factory, status, position, del_flag |

其他表的访问通过 Vanna 的 INFORMATION_SCHEMA 自省或管理后台手动索引实现。

### ChromaDB 向量存储

三个独立的 ChromaDB 持久化集合：

| 存储路径 | 集合名 | 用途 |
|----------|--------|------|
| `./backend/data/agentic_qa/vanna-knowledge/` | `industrial_sql_memories` | Vanna Agent 记忆 (SQL 对 + 文档) |
| `./backend/data/agentic_qa/vanna-knowledge/` | `table_schema_index` | 表结构文档索引 |
| `./backend/data/agentic_qa/entity-knowledge/` | `entity_index` | 实体向量索引 (产线 + 设备) |
| `./backend/data/agentic_qa/entity-knowledge/` | `entity_aliases` | 实体别名映射 |
| `./backend/data/agentic_qa/entity-knowledge/` | `custom_metrics` | 自定义业务指标 |

### 嵌入模型

默认使用 `all-MiniLM-L6-v2` (384维)，推荐安装中文模型。本地模型文件位于 `backend/services/agentic_qa/bge-small-zh-v1.5/`：

```bash
uv pip install sentence-transformers
# 有本地模型时优先使用本地文件，否则自动下载 BAAI/bge-small-zh-v1.5 (768维)
```

嵌入模型通过 `backend/core/agentic_qa/embeddings.py` 的单例模式管理，切换模型后需重建所有向量索引。

---

## API 设计

### 认证接口

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/api/auth/login` | POST | 否 | 登录 → `{token, user}` (默认 admin/admin) |
| `/api/auth/me` | GET | 是 | 当前用户信息 |

### 核心查询接口

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/api/query` | POST | 是 | 智能问答入口 (完整 LangGraph 流程, 支持对话历史) |
| `/api/query/confirm` | POST | 是 | 实体确认后继续查询 (支持多选) |
| `/api/feedback` | POST | 是 | 用户反馈 (正确→保存待审核, 错误→记录反馈) |
| `/api/health` | GET | 否 | 健康检查 |

### 会话接口

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/api/sessions` | GET | 是 | 用户会话列表 `?page=1&limit=50` |
| `/api/sessions` | POST | 是 | 创建新会话 |
| `/api/sessions/{id}` | GET | 是 | 会话详情 + 全部消息 |
| `/api/sessions/{id}` | PUT | 是 | 更新标题/memory |
| `/api/sessions/{id}` | DELETE | 是 | 删除会话 (CASCADE 消息) |
| `/api/sessions/{id}/messages` | POST | 是 | 追加消息 (fire-and-forget) |

### 管理接口

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/api/admin/schemas/status` | GET | 是 | 表索引状态 |
| `/api/admin/schemas/index` | POST | 是 | 索引表结构 |
| `/api/admin/schemas/unindex` | POST | 是 | 取消索引 |
| `/api/admin/memories` | GET | 是 | 记忆库列表 (支持 type/search/limit 过滤) |
| `/api/admin/memories/{id}` | DELETE | 是 | 删除单条记忆 |
| `/api/admin/memories/batch-delete` | POST | 是 | 批量删除记忆 `{ ids: [...] }` |
| `/api/admin/memories/train` | POST | 是 | 手动训练 |
| `/api/admin/memories/edit` | PUT | 是 | 编辑记忆 (删除旧向量 + 重新向量化) |
| `/api/admin/memories/export` | GET | 是 | 导出记忆库 JSON `?type=sql_pair|documentation` |
| `/api/admin/memories/import` | POST | 是 | 导入记忆库 JSON (Merge 模式, 跳过重复) |
| `/api/admin/training-review` | GET | 是 | 待审核列表 |
| `/api/admin/training-review/action` | POST | 是 | 审核操作 (approve/edit/delete) |
| `/api/admin/entities/registry` | GET | 是 | 实体注册表 |
| `/api/admin/entities/search` | POST | 是 | 向量搜索实体 |
| `/api/admin/entities/index` | POST | 是 | 重建实体索引 |
| `/api/admin/entities/aliases` | GET/POST | 是 | 别名 CRUD |
| `/api/admin/entities/aliases/export` | GET | 是 | 导出别名 JSON |
| `/api/admin/entities/aliases/import` | POST | 是 | 导入别名 JSON |
| `/api/admin/entities/metrics` | GET/POST | 是 | 指标 CRUD |
| `/api/admin/entities/metrics/export` | GET | 是 | 导出指标 JSON |
| `/api/admin/entities/metrics/import` | POST | 是 | 导入指标 JSON |
| `/api/admin/reload-graph` | POST | 是 | 热重载 Neo4j 知识图谱 |
| `/api/admin/graph-status` | GET | 是 | Neo4j 图数据库状态 |
| `/api/admin/stats` | GET | 是 | 使用统计 |
| `/api/admin/presets` | GET/POST | 是 | 预置问题 |

### WebSocket

| 端点 | 说明 |
|------|------|
| `/api/ws/{session_id}?token=xxx` | 实时步骤推送 (JWT 认证通过 query 参数) |

### RAGFlow 代理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/ragflow/document-preview` | GET | 代理获取文档 (Base64) |
| `/api/ragflow/document-download` | GET | 代理下载文档 (PDF 流) |

---

## 前端架构

### 路由设计

使用 Vue Router (Hash 模式)：

| 路由 | 组件 | 用途 |
|------|------|------|
| `/sql-qa` | SqlQaLayout | SQL-QA 主聊天界面 |
| `/sql-qa/admin/entities` | AdminEntities | 实体管理 (别名/指标/索引/图谱) |
| `/sql-qa/admin/monitor` | AdminMonitor | 效果监控 |
| `/sql-qa/admin/training` | AdminTraining | 训练管理 |
| `/sql-qa/pdf` | PdfPage | PDF 文档查看 |

### 状态管理

使用 Vue 3 Composition API (composables)：

| Composable | 职责 |
|-----------|------|
| `useSqlQaAuth` | JWT 认证 (login/logout/token) |
| `useSqlQaSessions` | 会话列表 CRUD, 本地缓存 |
| `useSqlQaChat` | 聊天逻辑, WebSocket, 消息管理 |

### 开发代理

Vite 开发服务器将 `/api` 请求代理到后端 `http://localhost:9300`。

---

## 配置管理

所有配置通过环境变量管理，由 `backend/core/agentic_qa/config.py` 的 Pydantic `BaseSettings` 自动加载 `.env` 文件。Agentic QA 相关配置使用 `AQA_` 前缀：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | (必填) | DeepSeek API 密钥 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | 模型名称 |
| `AQA_MYSQL_HOST` | (必填) | MySQL 主机 |
| `AQA_MYSQL_PORT` | `3306` | MySQL 端口 |
| `AQA_MYSQL_USER` | (必填) | 用户名 |
| `AQA_MYSQL_PASSWORD` | (必填) | 密码 |
| `AQA_MYSQL_DATABASE` | (必填) | 数据库名 |
| `RAGFLOW_BASE_URL` | (必填) | RAGFlow 服务地址 |
| `RAGFLOW_API_KEY` | (必填) | RAGFlow API 密钥 |
| `AQA_DATABASE_URL` | `sqlite:///./backend/data/agentic_qa/system_data/app.db` | 应用数据库 (SQLite, 可切换 PostgreSQL) |
| `AQA_VANNA_CHROMA_PATH` | `./backend/data/agentic_qa/vanna-knowledge` | ChromaDB 持久化路径 |
| `AQA_ENTITY_CHROMA_PATH` | `./backend/data/agentic_qa/entity-knowledge` | 实体 ChromaDB 持久化路径 |
| `AQA_APP_ENV` | `development` | 运行环境 |
| `AQA_APP_SECRET_KEY` | (必填) | 应用密钥 (JWT 签名) |

---

## 本地开发

### 环境要求

- Python 3.12+
- Node.js 18+
- uv (Python 包管理器)
- MySQL 数据库（需已有业务数据）
- RAGFlow（可选，用于文档问答）
- Neo4j（可选，用于知识图谱实体消歧）

### 安装与启动

```bash
# 1. 安装依赖
uv sync

# 2. 安装前端依赖
cd frontend && npm install && cd ..

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，启用 SQL-QA:
#   ENABLE_SQL_QA=true
# 填写 DeepSeek API Key、MySQL 连接信息等

# 4. 启动开发模式
./start.sh          # Linux/Mac
start.bat           # Windows

# 或者分别启动：
# 后端: uv run uvicorn backend.app:app --host 0.0.0.0 --port 9300 --reload
# 前端: cd frontend && npm run dev

# 5. 指定模型
uv run python backend/app.py --model deepseek
```

### 功能开关

在 `.env` 中控制可选模块：

```bash
ENABLE_SQL_QA=true              # SQL 智能问答
ENABLE_REPORT_SCHEDULER=false   # 报告自动调度
```

---

## 扩展指南

### 添加新的意图类型

1. 在 `backend/services/agentic_qa/agents/question_analyzer.py` 的 `INTENT_CLASSIFICATION_SYSTEM` 提示词中添加新意图描述
2. 在 `backend/services/agentic_qa/agents/graph.py` 的 `route_after_intent()` 中添加路由分支
3. 如需新处理节点，在 `graph.py` 中添加节点函数并注册到状态图

### 添加新的实体类型

1. 在 `backend/services/agentic_qa/agents/entity_resolver.py` 的 `_ENTITY_REGISTRY` 中添加实体配置：
```python
{
    "entity_type": "new_entity",
    "table": "your_table",
    "search_columns": ["name", "description"],
    "label_column": "name",
    "value_column": "id",
}
```
2. 在管理后台 → 实体工具中重建索引

### 添加新的 Enhancer

1. 在 `backend/services/agentic_qa/vanna/enhancers.py` 中创建新的 Enhancer 类，继承 `Enhancer`
2. 实现 `get_context()` 方法
3. 在 `CombinedEnhancer` 中注册新的 Enhancer
4. 在 `sql_agent.py` 的 SQL 生成流程中注入

### 自定义 LLM

修改 `backend/core/agentic_qa/llm.py` 中的 `get_llm()` 函数，支持其他 OpenAI 兼容的 API。

---

## 常见问题

### 切换嵌入模型后搜索异常

不同嵌入模型生成的向量维度不同（英文 384 维，中文 768 维），切换后必须重建所有 ChromaDB 索引：删除 `./backend/data/agentic_qa/vanna-knowledge` 和 `./backend/data/agentic_qa/entity-knowledge` 目录后重启。

### 为什么有些表查不到

系统不会自动发现所有数据库表。需要在管理后台 → 数据库索引中手动索引需要查询的表结构。

### del_flag 过滤逻辑

系统自动为 `sys_line` 和 `dev_device` 表添加 `del_flag=0` 条件。这是硬编码在 SQL 生成逻辑中的，如需修改，参见 `backend/services/agentic_qa/agents/sql_agent.py`。

### 日志位置

- `./logs/agentic-qa/YYYY-MM-DD.log` — 按天轮转的完整日志 (DEBUG)
- `./logs/agentic-qa/error.log` — 仅错误日志 (ERROR)
- 控制台同步输出 INFO 级别
