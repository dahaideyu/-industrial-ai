# 工业数据智能问答平台（Agentic QA）— 开发者文档

面向工业场景的 NL2SQL 智能问答平台，采用 ReAct Agent 架构，支持自然语言查询设备、产线、维修工单、点检记录等核心数据，融合知识图谱实体消歧、向量记忆检索、RAGFlow 文档问答等能力。

---

## 目录

- [系统架构](#系统架构)
- [ReAct Agent 核心架构](#react-agent-核心架构)
- [预处理并行流水线](#预处理并行流水线)
- [工具插件体系](#工具插件体系)
- [Vanna NL2SQL 引擎](#vanna-nl2sql-引擎)
- [知识图谱集成 (Neo4j)](#知识图谱集成-neo4j)
- [向量存储 (ChromaDB)](#向量存储-chromadb)
- [实体消歧引擎](#实体消歧引擎)
- [RAGFlow 文档问答](#ragflow-文档问答)
- [WebSocket 实时推送](#websocket-实时推送)
- [数据库模型](#数据库模型)
- [API 端点](#api-端点)
- [前端架构](#前端架构)
- [配置管理](#配置管理)
- [目录结构](#目录结构)
- [技术栈](#技术栈)

---

## 系统架构

Agentic QA 作为 chaowei-agent 的可选功能模块，通过 `ENABLE_SQL_QA=true` 环境变量启用。

```
用户 Web 端 (Vue 3 + Vite)
        │ HTTP REST + WebSocket
┌───────▼──────────────────────────────────────────┐
│              FastAPI 统一入口 (app.py)              │
│  - JWT 认证中间件                                   │
│  - 功能开关: ENABLE_SQL_QA 控制路由加载              │
│  - 启动时初始化 Vanna Agent + Neo4j 图谱 + 数据库    │
└───────┬──────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────┐
│           ReAct 编排循环 (master_loop.py)           │
│                                                    │
│  ┌─────────────────────────────────────────────┐  │
│  │ 预处理层 (并行, ~300ms)                       │  │
│  │  ├─ LLM 槽位提取 (实体/指标/时间)             │  │
│  │  ├─ Vanna Schema 匹配                        │  │
│  │  ├─ ChromaDB 相似查询搜索                     │  │
│  │  └─ Neo4j 主题检索 + Blueprint 生成           │  │
│  └─────────────────┬───────────────────────────┘  │
│                    ▼                               │
│  ┌─────────────────────────────────────────────┐  │
│  │ ReAct 循环 (MAX 50步)                         │  │
│  │  每步: LLM 流式思考 → 工具调用 → 结果 → 反思  │  │
│  │                                               │  │
│  │  工具并行执行 (asyncio.gather)                 │  │
│  │  自我反思 (execute_sql 0行/超1000行时触发)     │  │
│  │  连续失败 3 次 / 策略循环检测 → 停止           │  │
│  └─────────────────┬───────────────────────────┘  │
│                    ▼                               │
│  ┌─────────────────────────────────────────────┐  │
│  │ 结论生成                                     │  │
│  │  ├─ 有数据 → LLM 生成结论 + 追问建议          │  │
│  │  └─ 需澄清 → ask_clarification → 用户选择     │  │
│  └─────────────────────────────────────────────┘  │
│                                                    │
│  实时推送: 思考流 + 步骤状态 (WebSocket)             │
└───────┬──────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────┐
│                    数据层                          │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │  MySQL   │  │PostgreSQL│  │  ChromaDB × 7  │  │
│  │ 业务数据  │  │ 会话/消息│  │  向量集合      │  │
│  └──────────┘  └──────────┘  └────────────────┘  │
│  ┌──────────────────────┐  ┌──────────────────┐  │
│  │  Neo4j (知识图谱)    │  │ RAGFlow (文档QA) │  │
│  └──────────────────────┘  └──────────────────┘  │
└──────────────────────────────────────────────────┘
```

---

## ReAct Agent 核心架构

核心编排在 `backend/services/agentic_qa/master_loop.py`，采用 LLM 原生工具调用（function calling）实现 ReAct 循环。

### 执行流程

```
用户问题
  ↓
预处理 (并行, ~300ms)
  ↓
Plan 阶段 (简单问题 <30字符跳过)
  ↓
ReAct 循环:
  ┌─────────────────────────────────────────────┐
  │ LLM 流式输出 (thinking + tool_calls)          │
  │   ↓                                         │
  │ 解析工具调用 → 并行执行 (asyncio.gather)      │
  │   ↓                                         │
  │ 收集结果 → 注入上下文                         │
  │   ↓                                         │
  │ 自我反思 (should_reflect):                    │
  │   - execute_sql 返回 0 行 → 重新分析          │
  │   - execute_sql 返回 >1000 行 → 加条件限制    │
  │   - search_entities 返回 0 → 换搜索策略       │
  │   - diagnose_sql_error → 诊断修正             │
  │   ↓                                         │
  │ 下一轮...                                     │
  └─────────────────────────────────────────────┘
  ↓
结论生成 (有数据但无实质性回答时触发)
  ↓
返回结果 (answer + sql + results + chart + followups)
```

### 停止条件

| 条件 | 说明 |
|------|------|
| final answer + 数据 | 正常完成 |
| 连续失败 3 次 | 工具执行失败达到上限 |
| 策略循环检测 | `AgentState.detect_strategy_loop()` 检测到重复策略 |
| 最大 50 步 | 防止无限循环 |

### AgentState 状态追踪

`backend/services/agentic_qa/agent_state.py` 定义 `AgentState` 数据类：

| 字段 | 说明 |
|------|------|
| question | 原始问题 |
| plan | 查询计划 |
| executed_steps | 已执行步骤列表 |
| last_sql | 最近一次 SQL |
| query_results | 查询结果 |
| final_answer | 最终回答 |
| consecutive_failures | 连续失败计数 |
| strategy_history | 策略历史（用于循环检测） |

---

## 预处理并行流水线

`backend/services/agentic_qa/preprocess.py` 的 `assemble_context()` 在 ReAct 循环前并行执行：

| 预处理任务 | 方式 | 耗时 | 输出 |
|-----------|------|------|------|
| 槽位提取 | LLM 结构化提取 | ~500ms | 实体、指标、时间范围 |
| Schema 匹配 | Vanna 关键词检索 | ~50ms | 相关表结构 |
| 相似查询 | ChromaDB 向量搜索 | ~200ms | 历史 QA 对 |
| 主题检索 | Neo4j 实体检索 | ~100ms | 图谱上下文 |

输出 `QueryBlueprint`：通过 `blueprint.py` 的 BFS 遍历 Neo4j 图谱，找到实体标签间的可达路径，生成 JOIN 规范和 WHERE 提示。

---

## 工具插件体系

采用插件架构，所有工具继承 `BaseTool` ABC，通过 `ToolRegistry` 注册。每个工具暴露 OpenAI function-calling schema。

### 11 个注册工具

| 工具 | 文件 | 说明 |
|------|------|------|
| `generate_sql` | `sql_tools.py` | Vanna 增强 NL2SQL（Schema 注入 + 记忆检索） |
| `execute_sql` | `sql_tools.py` | 安全检查 → 执行 SQL → 返回数据 |
| `diagnose_sql_error` | `sql_tools.py` | LLM 诊断 SQL 错误并修正 |
| `typo_check` | `sql_tools.py` | 实体名拼写错误检测 |
| `search_entities` | `entity_tools.py` | 实体搜索（完整消歧流水线） |
| `get_schema` | `entity_tools.py` | 表结构检索 |
| `ask_clarification` | `clarify_tool.py` | 暂停等待用户澄清（分组选项） |
| `query_rag` | `rag_tool.py` | RAGFlow 文档问答（SSE 流式） |
| `analyze_data` | `analysis_tool.py` | 数据洞察 + 图表配置生成 |
| `answer_general` | `general_tool.py` | 通用/闲聊问答 |
| `read_memory` | `memory_tool.py` | 会话记忆缓存读取 |

### 工具执行机制

```python
# master_loop.py 中的并行执行
tool_calls = parse_tool_calls(llm_response)
results = await asyncio.gather(*[execute_tool(tc) for tc in tool_calls])
```

---

## Vanna NL2SQL 引擎

位于 `backend/services/agentic_qa/vanna/`，基于 Vanna 2.0 框架。

### 核心组件

| 文件 | 类/接口 | 说明 |
|------|---------|------|
| `agent.py` | `VannaAgentManager` | 单例管理 Vanna Agent 生命周期，ChromaAgentMemory + MySQLRunner |
| `deepseek_llm.py` | `LlmServiceImpl` | 适配 Vanna 的 `LlmService` 接口，封装 OpenAI 兼容 API |
| `enhancers.py` | `SchemaContextEnhancer` | 从 `table_schema_index` 集合检索相关表结构注入 system prompt |
| `enhancers.py` | `MemoryRetrievalEnhancer` | 从 `industrial_sql_memories` 集合检索相似历史 QA 注入 |
| `guard.py` | `SqlSecurityHook` | Vanna 生命周期钩子，SQL 执行前自动触发安全检查 |

### Enhancer 注入流程

```
generate_sql 调用
  ↓
SchemaContextEnhancer: 关键词匹配 → 注入相关表 DDL
  ↓
MemoryRetrievalEnhancer: 向量搜索 → 注入相似 QA 对
  ↓
CombinedEnhancer: 合并两者 → 注入 LLM system prompt
  ↓
LLM 生成 SQL
```

### SQL 安全检查

`backend/services/agentic_qa/vanna/guard.py` 双层校验：

1. **关键词黑名单**：拦截 `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `REPLACE`
2. **sqlglot 语法树分析**：解析 SQL 为 AST，确保最外层语句是 `SELECT`
3. **自动修正**：强制添加 `LIMIT 1000`（如未指定）
4. **维护表时间范围**：特定表自动添加时间范围条件

通过 Vanna 的 `LifecycleHook` 机制在 SQL 执行前自动触发。

---

## 知识图谱集成 (Neo4j)

### 连接配置

通过 `AQA_NEO4J_URI`, `AQA_NEO4J_USER`, `AQA_NEO4J_PASSWORD` 环境变量配置。

### 图谱 Schema（graph_mapping.yaml）

`config/graph_mapping.yaml` 定义节点和关系：

**节点定义**：
```yaml
node_types:
  - table: dev_device          # MySQL 源表
    label: Device              # Neo4j 标签
    label_zh: 设备             # 中文标签
    type_key: device_type      # 类型字段
    id_field: id               # ID 字段
    name_field: name           # 名称字段
    alias_fields: [short_no]   # 别名字段
```

**关系定义**：
```yaml
relationships:
  - from_table: dev_device
    fk_field: line_id
    to_table: sys_line
    rel_type: BELONGS_TO
```

还支持 `manual_nodes` 和 `manual_relationships` 手工定义。

### 图谱导入流程

`backend/core/agentic_qa/graph_importer.py` 的 `import_to_neo4j()`：

1. 为所有标签创建唯一约束（`id` 字段）
2. 创建 CJK 全文索引（`entity_fulltext`），使用 CJK 分析器，索引 `name` 和 `aliases` 字段
3. 批量 MERGE 节点（每批 500 条，从 MySQL 读取）
4. 批量 MERGE 关系
5. MERGE 手工节点和关系

### 图谱查询

`backend/core/agentic_qa/graph_client.py` 的 `GraphClient`：

| 方法 | 说明 |
|------|------|
| `search_entity()` | 全文搜索 → 跨类型搜索 → CONTAINS 降级 |
| `get_entity_context()` | 获取实体关系链（深度 1-3） |
| `find_paths()` | BFS 查找两实体间的最短路径 |

---

## 向量存储 (ChromaDB)

使用 ChromaDB 持久化存储，共 7 个集合：

| 集合名 | 存储路径 | 用途 |
|--------|----------|------|
| `industrial_sql_memories` | `vanna-knowledge/` | Vanna Agent 记忆（QA 对 + 文档记忆） |
| `table_schema_index` | `vanna-knowledge/` | 表结构 DDL 和列信息索引 |
| `entity_index` | `entity-knowledge/` | 实体名称向量索引 |
| `entity_aliases` | `entity-knowledge/` | 实体别名→标准名映射 |
| `custom_metrics` | `entity-knowledge/` | 用户自定义业务指标 |
| `batch_generated_drafts` | `entity-knowledge/` | AI 批量生成的训练草稿 |
| `training_review_queue` | `entity-knowledge/` | 待审核训练条目 |

### 嵌入模型

`backend/core/agentic_qa/embeddings.py` 懒加载 `BAAI/bge-small-zh-v1.5`（512 维中文 SentenceTransformer）。本地缓存于 `backend/services/agentic_qa/bge-small-zh-v1.5/`，优先于 HuggingFace 下载。加载失败时降级到 `all-MiniLM-L6-v2`（384 维）。

---

## 实体消歧引擎

`backend/services/agentic_qa/agents/entity_resolver.py` 实现多级搜索流水线：

```
用户输入中的实体提及
  ↓
① 别名搜索 (ChromaDB entity_aliases, 余弦距离阈值 0.65)
  ↓ 命中 → 返回
② Neo4j 全文搜索 (CJK 分析器) + LLM 质量评估
  ↓ 命中 → 返回
③ ChromaDB 向量搜索 (entity_index)
  ↓ 命中 → 返回
④ SQL LIKE 模糊匹配 (处理相似字符，如 "合膏" vs "和膏")
  ↓ 命中 → 返回
⑤ 全量数据库加载 (最后手段)
```

### CRUD 管理

| 操作 | 说明 |
|------|------|
| 别名管理 | 添加/删除/导出/导入实体别名映射 |
| 指标管理 | 添加/删除/导出/导入自定义业务指标 |
| 索引重建 | 从 MySQL 重新构建实体向量索引 |

---

## RAGFlow 文档问答

### RAGFlow 客户端

`backend/services/agentic_qa/ragflow/client.py` 实现 SSE 流式客户端：

| 功能 | 说明 |
|------|------|
| 对话 API | SSE 流式问答，解析思考过程、引用块、最终回答 |
| 文档操作 | 文档列表、上传、删除 |
| 切片管理 | 切片列表、搜索 |
| 文档下载 | 代理下载避免前端跨域 |

### rag_agent 工作流

```
query_rag(question)
  ↓
调用 RAGFlow Chat Assistant API (SSE 流式)
  ↓
解析流式事件:
  - thinking_chunk → 思考过程
  - reference → 引用文档块
  - answer → 最终回答
  ↓
收集引用文档信息 (文档名、页码、切片内容)
  ↓
返回 { answer, references }
```

---

## WebSocket 实时推送

`backend/routes/agentic_qa/websocket.py`：

- **连接路径**：`/api/ws/{session_id}?token=<jwt>`
- **认证**：支持统一模式（HMAC + PostgreSQL sys_user）或独立模式（JWT + SQLite users）

### 消息类型

| type | 说明 | data |
|------|------|------|
| `step_update` | 步骤状态更新 | `{ step, status, message, elapsed_ms }` |
| `thinking_chunk` | LLM 思考流式片段 | `{ content }` |
| `thinking_end` | LLM 思考结束 | `{}` |
| `complete` | 查询完成 | `{ result }` |

### 前端处理

`useSqlQaChat.js` composable 管理 WebSocket 生命周期：
- 建立连接 → 逐步累积步骤列表 → 打字机效果显示回答
- 完成后自动折叠为摘要栏，点击可展开详情

---

## 数据库模型

应用数据库使用 PostgreSQL（可通过 `AQA_DATABASE_URL` 切换 SQLite），通过 SQLAlchemy 2.0 ORM 管理。

### User（用户）

表名：`users`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| username | VARCHAR | 用户名（唯一） |
| password_hash | VARCHAR | bcrypt 密码哈希 |
| is_active | BOOLEAN | 是否启用 |

### ChatSession（会话）

表名：`chat_sessions`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| user_id | INTEGER | FK → User |
| title | VARCHAR | 会话标题（可 LLM 自动生成） |
| memory | JSON | 会话记忆（确认的实体等） |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

### ChatMessage（消息）

表名：`chat_messages`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| session_id | UUID | FK → ChatSession |
| role | VARCHAR | `user` / `assistant` |
| content | TEXT | 消息内容 |
| sql | TEXT | 生成的 SQL |
| results | JSON | 查询结果 |
| result_groups | JSON | 多 SQL 结果分组 |
| steps | JSON | 执行步骤列表 |
| entity_candidates | JSON | 实体候选 |
| clarification_groups | JSON | 澄清分组选项 |
| followups | JSON | 追问建议 |
| analysis_chart | JSON | 图表配置 |
| analysis_suggestions | JSON | 分析建议 |
| thinking | TEXT | LLM 思考过程 |
| source | VARCHAR | 来源 |
| feedback | VARCHAR | 用户反馈 |
| elapsed_ms | INTEGER | 耗时 |
| created_at | TIMESTAMP | 创建时间 |

### EntityConfig（实体注册配置）

表名：`entity_configs`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| entity_type | VARCHAR | 实体类型 |
| table_name | VARCHAR | MySQL 源表 |
| search_columns | JSON | 搜索列 |
| label_column | VARCHAR | 标签列 |
| value_column | VARCHAR | 值列 |

---

## API 端点

### 认证

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/api/auth/login` | POST | 否 | 登录 → `{token, user}` |
| `/api/auth/me` | GET | 是 | 当前用户信息 |

### 核心查询

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/api/query` | POST | 是 | 智能问答入口（完整 ReAct 流程） |
| `/api/query/confirm` | POST | 是 | 实体确认后继续查询 |
| `/api/query/compose` | POST | 是 | 从澄清选项组合自然语言 |
| `/api/feedback` | POST | 是 | 用户反馈（正确/错误） |
| `/api/feedback/record` | POST | 是 | 记录错误反馈到审核队列 |
| `/api/init` | POST | 是 | 初始化会话 |
| `/api/health` | GET | 否 | 健康检查 |

**查询请求格式**：
```json
{
  "question": "3号车间有哪些设备？",
  "use_rag": false,
  "session_id": "uuid",
  "user_role": "admin",
  "session_memory": {},
  "history": []
}
```

**查询响应格式**：
```json
{
  "success": true,
  "answer": "3号车间共有15台设备...",
  "sql": "SELECT * FROM dev_device WHERE factory='3号车间'",
  "results": [...],
  "result_groups": [...],
  "needs_clarification": false,
  "clarification_groups": null,
  "followups": ["查看设备状态分布", "查看维修记录"],
  "analysis_chart": { "type": "bar", "data": {...} },
  "analysis_suggestions": [...],
  "elapsed_ms": 2340,
  "source": "sql"
}
```

### 会话管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/sessions` | GET | 会话列表（分页） |
| `/api/sessions` | POST | 创建会话 |
| `/api/sessions/{id}` | GET | 会话详情 + 全部消息 |
| `/api/sessions/{id}` | PUT | 更新标题/memory |
| `/api/sessions/{id}` | DELETE | 删除会话（级联删除消息） |
| `/api/sessions/{id}/messages` | POST | 追加消息 |
| `/api/sessions/{id}/generate-title` | POST | LLM 自动生成标题 |

### 管理后台

**记忆管理**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/admin/memories` | GET | 记忆列表（type/search/limit 过滤） |
| `/api/admin/memories/{id}` | DELETE | 删除单条 |
| `/api/admin/memories/batch-delete` | POST | 批量删除 |
| `/api/admin/memories/train` | POST | 手动训练 |
| `/api/admin/memories/edit` | PUT | 编辑（删除旧向量 + 重新向量化） |
| `/api/admin/memories/export` | GET | 导出 JSON |
| `/api/admin/memories/import` | POST | 导入 JSON（Merge 模式） |

**实体管理**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/admin/entities/registry` | GET | 实体注册表 |
| `/api/admin/entities/search` | POST | 向量搜索实体 |
| `/api/admin/entities/index` | POST | 重建实体索引 |
| `/api/admin/entities/configs` | GET/POST/PUT/DELETE | 实体配置 CRUD |
| `/api/admin/entities/aliases` | GET/POST/PUT/DELETE | 别名 CRUD + 导入导出 |
| `/api/admin/entities/metrics` | GET/POST/PUT/DELETE | 指标 CRUD + 导入导出 |

**Schema 管理**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/admin/schemas/status` | GET | 表索引状态 |
| `/api/admin/schemas/index` | POST | 索引表结构 |
| `/api/admin/schemas/unindex` | POST | 取消索引 |

**知识图谱**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/admin/reload-graph` | POST | 热重载 Neo4j 图谱 |
| `/api/admin/graph-status` | GET | 图数据库状态（节点计数） |
| `/api/admin/graph-mapping` | GET/PUT | 图谱映射 YAML 读取/编辑 |

**批量生成**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/admin/batch-generate` | POST | 启动 AI 批量训练生成 |
| `/api/admin/batch-generate/status/{job_id}` | GET | 生成进度 |
| `/api/admin/batch-drafts` | GET/POST/PUT/DELETE | 训练草稿 CRUD |

**训练审核**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/admin/training-review` | GET | 待审核列表 |
| `/api/admin/training-review/action` | POST | 审核操作（approve/edit/delete） |

**统计**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/admin/stats` | GET | 使用统计 |

### RAGFlow 代理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/ragflow/document-preview` | GET | 代理获取文档（Base64） |
| `/api/ragflow/document-download` | GET | 代理下载文档（PDF 流） |

### WebSocket

| 端点 | 说明 |
|------|------|
| `/api/ws/{session_id}?token=xxx` | 实时步骤推送 |

---

## 前端架构

### 页面组件

| 组件 | 路由 | 说明 |
|------|------|------|
| `SqlQaLayout.vue` | `/sql-qa` | 主聊天界面布局（侧边栏 + 消息区 + 输入区） |
| `ChatPage.vue` | `/sql-qa` | 聊天页面 |
| `AdminTraining.vue` | `/sql-qa/admin/training` | 训练数据管理（记忆 CRUD、导入导出、批量生成、审核） |
| `AdminMonitor.vue` | `/sql-qa/admin/monitor` | 使用统计监控 |
| `AdminEntities.vue` | `/sql-qa/admin/entities` | 实体管理（注册表、别名、指标、Schema 索引） |
| `PdfPage.vue` | `/sql-qa/pdf` | PDF 文档查看器 |

### 聊天组件（25+）

| 组件 | 说明 |
|------|------|
| `AgenticSteps.vue` | 实时 Agent 执行步骤展示（预处理→实体解析→SQL→执行→分析） |
| `AgenticThinking.vue` | LLM 思考/推理内容实时展示 |
| `SqlQaMessageBubble.vue` | 聊天气泡（SQL + 结果表 + 图表 + 反馈按钮） |
| `SqlQaInputArea.vue` | 文本输入框 + 发送按钮 |
| `SqlQaResultTable.vue` | SQL 查询结果表格展示 |
| `SqlQaChart.vue` | 图表渲染（柱状图/折线图/饼图） |
| `SqlQaResultGroups.vue` | 多 SQL 结果分组展示 |
| `SqlQaExecutionSteps.vue` | 执行步骤时间线 |
| `SqlQaAnalysisSuggestions.vue` | 可点击分析建议芯片 |
| `SqlQaFeedbackButtons.vue` | 点赞/点踩反馈 |
| `SqlQaCitationPopup.vue` | RAGFlow 文档引用弹窗 |
| `SqlQaConfirmModal.vue` | 实体确认模态框（分组多选） |
| `SqlQaWelcomeScreen.vue` | 欢迎屏幕（预置问题） |
| `SqlQaSchemaIndex.vue` | Schema 索引管理 |
| `SqlQaBatchGenerate.vue` | 批量生成配置 |
| `SqlQaTrainForm.vue` | 训练表单 |
| `SqlQaTrainingReview.vue` | 训练审核队列 |
| `SqlQaMemoryManager.vue` | 记忆管理器 |
| `SqlQaImportModal.vue` | 导入弹窗 |
| `SqlQaPagination.vue` | 分页组件 |
| `SqlQaStepProgress.vue` | 步骤进度条 |
| `SqlQaStatCard.vue` | 统计卡片 |
| `SqlQaLoginForm.vue` | 登录表单 |
| `SqlQaSelect.vue` | 下拉选择 |
| `SqlQaPdfViewer.vue` | PDF 查看器（pdfjs-dist） |
| `SqlQaRightPanel.vue` | 右侧面板 |

### Composables

| Composable | 职责 |
|-----------|------|
| `useSqlQaChat.js` | WebSocket 管理、消息发送、实体确认、打字机效果、流式步骤/思考/回答更新 |
| `useSqlQaSessions.js` | 会话 CRUD、懒加载消息、localStorage 持久化、API 同步 |
| `useSqlQaAuth.js` | JWT Token 管理（localStorage）、登录/登出 |
| `useSqlQaConfirm.js` | Promise 化的确认对话框 |

### API 客户端

`api/sqlQaClient.js` — Axios 实例，JWT 拦截器，60+ 导出 API 函数覆盖所有端点。

---

## 配置管理

所有配置通过环境变量管理，由 `backend/core/agentic_qa/config.py` 的 Pydantic Settings 自动加载。

### Provider 模式

`PROVIDER` 环境变量（默认 `deepseek`）决定使用哪个 LLM。系统读取 `{PROVIDER}_API_KEY`, `{PROVIDER}_BASE_URL`, `{PROVIDER}_MODEL`。

### 配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PROVIDER` | `deepseek` | LLM 提供商 |
| `DEEPSEEK_API_KEY` | (必填) | API 密钥 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | 模型名称 |
| `AQA_MYSQL_HOST` | (必填) | MySQL 主机 |
| `AQA_MYSQL_PORT` | `3306` | MySQL 端口 |
| `AQA_MYSQL_USER` | (必填) | 用户名 |
| `AQA_MYSQL_PASSWORD` | (必填) | 密码 |
| `AQA_MYSQL_DATABASE` | (必填) | 数据库名 |
| `AQA_NEO4J_URI` | (可选) | Neo4j 连接 URI |
| `AQA_NEO4J_USER` | (可选) | Neo4j 用户名 |
| `AQA_NEO4J_PASSWORD` | (可选) | Neo4j 密码 |
| `RAGFLOW_BASE_URL` | (可选) | RAGFlow 地址 |
| `RAGFLOW_API_KEY` | (可选) | RAGFlow API Key |
| `AQA_DATABASE_URL` | `sqlite:///...` | 应用数据库 |
| `AQA_VANNA_CHROMA_PATH` | `./backend/data/agentic_qa/vanna-knowledge` | Vanna ChromaDB 路径 |
| `AQA_ENTITY_CHROMA_PATH` | `./backend/data/agentic_qa/entity-knowledge` | 实体 ChromaDB 路径 |
| `AQA_APP_SECRET_KEY` | (必填) | JWT 签名密钥 |
| `AQA_APP_ENV` | `development` | 运行环境 |

---

## 目录结构

```
backend/
├── core/agentic_qa/                    # 核心基础设施
│   ├── config.py                       # Pydantic Settings（Provider 模式）
│   ├── llm.py                          # LLM 封装（OpenAI 兼容，3次重试）
│   ├── embeddings.py                   # 嵌入模型（bge-small-zh-v1.5 懒加载）
│   ├── graph_client.py                 # Neo4j 客户端（全文搜索 + 关系查询）
│   ├── graph_importer.py              # MySQL + YAML → Neo4j 图谱导入
│   ├── database.py                     # SQLAlchemy engine + 自动迁移
│   └── logger.py                       # 按天轮转日志
│
├── services/agentic_qa/                # 服务层
│   ├── master_loop.py                  # ReAct 主循环（工具调用编排 + 自我反思）
│   ├── master_prompt.py               # 系统提示词构建
│   ├── agent_state.py                  # AgentState 状态追踪
│   ├── base_tool.py                   # BaseTool ABC + ToolRegistry + ToolContext
│   ├── memory.py                       # MemoryHub 统一记忆门面
│   ├── preprocess.py                   # 预处理并行流水线
│   ├── blueprint.py                    # Neo4j BFS 查询蓝图生成
│   ├── state.py                        # LangGraph AgentState TypedDict
│   ├── batch_generator.py             # AI 批量训练生成
│   │
│   ├── agents/                         # 工具实现
│   │   ├── sql_agent.py               # NL2SQL + SQL 执行
│   │   ├── rag_agent.py               # RAGFlow 文档问答
│   │   ├── analysis_agent.py          # 数据分析 + 图表生成
│   │   ├── general_agent.py           # 通用/闲聊问答
│   │   ├── entity_resolver.py         # 实体消歧引擎
│   │   └── entity_config.py           # EntityConfig 模型
│   │
│   ├── tool_impls/                     # 工具注册
│   │   ├── sql_tools.py               # generate_sql, execute_sql, diagnose, typo_check
│   │   ├── entity_tools.py            # search_entities, get_schema
│   │   ├── clarify_tool.py            # ask_clarification
│   │   ├── rag_tool.py                # query_rag
│   │   ├── analysis_tool.py           # analyze_data
│   │   ├── general_tool.py            # answer_general
│   │   └── memory_tool.py             # read_memory
│   │
│   ├── vanna/                          # Vanna NL2SQL
│   │   ├── agent.py                   # VannaAgentManager（单例）
│   │   ├── deepseek_llm.py           # LlmServiceImpl
│   │   ├── enhancers.py              # SchemaContextEnhancer + MemoryRetrievalEnhancer
│   │   └── guard.py                   # SqlSecurityHook + validate_sql
│   │
│   ├── ragflow/
│   │   └── client.py                  # RAGFlow SSE 流式客户端
│   │
│   ├── db/
│   │   └── mysql.py                   # MySQL 连接池（pymysql）
│   │
│   └── models/
│       ├── user.py                    # User 模型
│       ├── session.py                 # ChatSession 模型
│       ├── message.py                 # ChatMessage 模型（20+ 字段）
│       └── entity_config.py           # EntityConfig 模型
│
├── routes/agentic_qa/                  # API 路由
│   ├── routes.py                       # 查询端点 + RAGFlow 代理
│   ├── websocket.py                   # WebSocket 实时推送
│   ├── sessions.py                     # 会话 CRUD
│   ├── admin.py                        # 管理后台
│   ├── auth.py                         # 认证
│   └── dependencies.py                # 依赖注入
│
├── data/agentic_qa/                    # 运行时数据
│   ├── vanna-knowledge/               # Vanna ChromaDB
│   ├── entity-knowledge/              # 实体 ChromaDB
│   └── system_data/                   # SQLite 数据库
│
├── config/
│   └── graph_mapping.yaml             # 知识图谱映射定义
│
└── app.py                              # 集成入口

frontend/src/
├── views/sql_qa/                       # 页面组件
│   ├── ChatPage.vue                    # 聊天页面
│   ├── SqlQaLayout.vue                # 布局
│   ├── AdminTraining.vue              # 训练管理
│   ├── AdminMonitor.vue               # 监控
│   ├── AdminEntities.vue              # 实体管理
│   ├── PdfPage.vue                    # PDF 查看
│   └── components/ (25+ 组件)
├── composables/sql_qa/
│   ├── useSqlQaChat.js                # 聊天逻辑
│   ├── useSqlQaSessions.js            # 会话管理
│   ├── useSqlQaAuth.js                # 认证
│   └── useSqlQaConfirm.js             # 确认对话框
└── api/
    └── sqlQaClient.js                 # API 客户端（60+ 函数）
```

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 前端 | Vue 3 + Vite 5 | SPA 单页应用 |
| 后端 | FastAPI (Python 3.13) | 异步 REST API + WebSocket |
| 认证 | JWT (python-jose) + bcrypt | 用户登录，24h 有效期 |
| ORM | SQLAlchemy 2.0 + PostgreSQL | 用户/会话/消息持久化 |
| Agent 框架 | 自研 ReAct Loop | LLM 工具调用循环，自主决策 + 自我修正 |
| NL2SQL | Vanna 2.0 + ChromaDB | 向量记忆检索 + SQL 生成 |
| LLM | 可配置 Provider（DeepSeek 默认） | SQL 生成/意图理解/实体消歧/结果总结 |
| 嵌入模型 | BAAI/bge-small-zh-v1.5 | 中文语义向量（512 维） |
| 知识图谱 | Neo4j | 实体消歧、关系发现、查询蓝图 |
| 向量数据库 | ChromaDB | 7 个持久化集合 |
| 文档问答 | RAGFlow | 设备手册/维修文档 SSE 流式检索 |
| 业务数据库 | MySQL | 工厂过程数据（pymysql + DictCursor） |
| 实时通信 | WebSocket | 思考流 + 步骤状态推送 |
| SQL 解析 | sqlglot | SQL 语法树分析与安全检查 |
| 图表 | 自定义 Chart 组件 | 数据分析可视化 |
| 包管理 | uv (Python), npm (前端) | 依赖管理 |
