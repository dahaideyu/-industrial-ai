# 知识库问答模块 — 开发者文档

基于 RAG 的工业知识库智能问答系统，通过 RAGFlow 对已发布的文档进行向量检索和回答生成，支持多知识库路由、会话管理、文档引用溯源。

---

## 目录

- [功能概述](#功能概述)
- [与 Agentic QA 的区别](#与-agentic-qa-的区别)
- [系统架构](#系统架构)
- [核心工作流](#核心工作流)
- [数据库模型](#数据库模型)
- [后端服务层](#后端服务层)
- [API 端点](#api-端点)
- [前端架构](#前端架构)
- [配置管理](#配置管理)
- [测试覆盖](#测试覆盖)
- [目录结构](#目录结构)
- [技术栈](#技术栈)

---

## 功能概述

| 功能 | 说明 |
|------|------|
| 知识库问答 | 基于 RAGFlow 对已发布文档进行向量检索，生成带引用的回答 |
| 多知识库路由 | LLM 自动判断问题涉及哪些知识库，精准检索 |
| 手动知识库选择 | 用户可手动指定搜索哪些知识库 |
| 会话管理 | 多轮对话、会话列表、会话删除 |
| 文档引用溯源 | 回答中标注引用来源（文档名、页码、相似度），支持预览和下载 |
| 上下文管理 | 最近 3 轮完整保留，更早的历史由 LLM 压缩摘要，Token 上限 6000 |
| Chat Assistant 懒加载 | 每用户一个 RAGFlow Chat Assistant，按需创建，LRU 自动清理 |
| 知识库列表 | 展示所有可用知识库及文档数量，按类型分组 |

---

## 与 Agentic QA 的区别

| 维度 | 知识库问答 (KBQA) | Agentic QA |
|------|-------------------|------------|
| 数据源 | RAGFlow 文档向量库 | MySQL 业务数据库 |
| 核心技术 | RAG（检索增强生成） | NL2SQL（自然语言转 SQL） |
| Agent 架构 | 无 Agent，单轮 RAG 调用 | ReAct Agent 循环（多工具编排） |
| 回答形式 | 文本 + 文档引用 | 文本 + SQL + 数据表格 + 图表 |
| 适用场景 | 设备手册、SOP、合规文档查询 | 设备状态、产线数据、维修记录查询 |
| 路由机制 | LLM 知识库路由 | 实体消歧 + 意图分类 |
| 前端路由 | `/knowledge-qa` | `/sql-qa` |

两个模块共享 RAGFlow 客户端（`backend/services/agentic_qa/ragflow/client.py`）和 LLM 配置（`backend/core/agentic_qa/config.py`），但功能完全独立。

---

## 系统架构

```
用户 Web 端 (Vue 3)
        │ HTTP REST
┌───────▼──────────────────────────────────────────┐
│           FastAPI 路由 (/api/kb-qa/*)             │
│   routes/knowledge_qa/routes.py                   │
└───────┬──────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────┐
│              KbQaService (核心服务)                │
│                                                    │
│  ① 加载最近消息 (最多 20 条)                       │
│  ② 构建上下文窗口 (MessageHistoryBuilder)          │
│     ├─ 最近 3 轮: 原样保留                         │
│     ├─ 更早轮次: LLM 压缩摘要                     │
│     └─ Token 上限 6000                            │
│  ③ 加载可用知识库列表                              │
│  ④ LLM 路由: 问题 → 相关知识库 (KbRouter)         │
│  ⑤ 获取/创建用户 Chat Assistant                    │
│  ⑥ 更新 Chat Assistant 绑定的数据集               │
│  ⑦ 调用 RAGFlow chat_sync() (SSE 流式)            │
│  ⑧ 持久化问答消息 + 引用                          │
│  ⑨ 返回: answer + references + used_kb_ids        │
└───────┬──────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────┐
│                    数据层                          │
│  ┌──────────┐  ┌──────────────────────────────┐  │
│  │PostgreSQL│  │         RAGFlow              │  │
│  │ 会话/消息│  │  Chat Assistant API           │  │
│  │ 助手映射 │  │  文档向量检索                  │  │
│  └──────────┘  └──────────────────────────────┘  │
│  ┌──────────────────┐                            │
│  │ 知识管理模块      │                            │
│  │ KnowledgeBase 表 │                            │
│  │ ragflow_dataset  │                            │
│  │ _id 字段         │                            │
│  └──────────────────┘                            │
└──────────────────────────────────────────────────┘
```

---

## 核心工作流

### 问答主流程

```
用户输入问题 + 可选手动选择知识库
  ↓
① 加载会话最近 20 条消息
  ↓
② MessageHistoryBuilder 构建上下文:
   ├─ 最近 3 轮: 原样保留
   ├─ 更早轮次: LLM 压缩为摘要系统消息
   └─ 超过 6000 Token 时截断
  ↓
③ 查询 KnowledgeBase 表获取可用知识库
   (JOIN DocumentCategory → PlanItem → Document → DocumentVersion,
    仅返回 document_count > 0 的知识库)
  ↓
④ KbRouter LLM 路由:
   ├─ 输入: 问题 + 历史 + 手动选择 + 可用知识库列表
   ├─ LLM 返回: JSON 数组 of KB IDs
   └─ 手动选择的知识库始终保留
  ↓
⑤ ChatAssistantManager 获取/创建用户 Chat Assistant:
   ├─ 查 kb_qa_user_chat_assistants 表
   ├─ 有 → 返回现有 ragflow_chat_id
   └─ 无 → 调用 RAGFlow API 创建 → 存储映射
  ↓
⑥ 更新 Chat Assistant 绑定的数据集:
   将选中 KB 的 ragflow_dataset_id 列表绑定
  ↓
⑦ 调用 RAGFlow chat_sync() (SSE 流式):
   ├─ 发送: 问题 + 历史消息
   └─ 接收: answer + references (文档块 + 相似度 + 页码)
  ↓
⑧ 持久化:
   ├─ 存储用户消息 (role=user)
   └─ 存储助手消息 (role=assistant, content, used_kb_ids, rag_references)
  ↓
⑨ 返回给前端:
   { answer, references, used_kb_ids, message_id, session_id }
```

### LLM 知识库路由

`backend/services/knowledge_qa/kb_router.py` 的 `KbRouter`：

```
输入:
  - question: 用户问题
  - history: 对话历史
  - manual_kb_ids: 手动选择的知识库 ID
  - available_kbs: 可用知识库列表 (id, name, type, description)

LLM Prompt:
  "根据以下问题和对话历史，判断应该搜索哪些知识库。
   返回 JSON 数组格式的知识库 ID 列表。"

输出: ["kb_id_1", "kb_id_2"]

降级策略:
  - LLM 返回空/解析失败 → 使用手动选择的 KB
  - 手动选择也为空 → 使用所有可用 KB
```

### 上下文窗口管理

`backend/services/knowledge_qa/message_history.py` 的 `MessageHistoryBuilder`：

```
策略:
  ┌─────────────────────────────────────────────┐
  │ 最近 N 轮 (默认 3): 原样保留                  │
  ├─────────────────────────────────────────────┤
  │ 更早轮次: LLM 压缩为摘要系统消息              │
  ├─────────────────────────────────────────────┤
  │ Token 上限: 6000 (超出时从最旧消息开始截断)   │
  └─────────────────────────────────────────────┘

Token 估算:
  - 中文字符: ~1.5 tokens/字符
  - 其他字符: ~0.5 tokens/字符
```

### Chat Assistant 生命周期

`backend/services/knowledge_qa/chat_assistant_mgr.py` 的 `ChatAssistantManager`：

```
创建:
  用户首次提问 → 查 DB 无记录 → 调用 RAGFlow POST /api/v1/chats
  → 存储映射到 kb_qa_user_chat_assistants

复用:
  用户再次提问 → 查 DB 有记录 → 直接使用 ragflow_chat_id

更新数据集:
  每次提问前 → PATCH /api/v1/chats/{chat_id} 更新绑定的数据集 ID

重名恢复:
  创建时名称已存在 → 搜索现有 chats 找到匹配 → 复用

LRU 清理:
  Celery Beat 定时任务 → 删除超过 7 天未使用的 Chat Assistant
  → DELETE /api/v1/chats/{chat_id} + 删除本地映射
```

---

## 数据库模型

所有表继承自知识管理模块的 SQLAlchemy Base，表名以 `kb_qa_` 为前缀。

### UserChatAssistant（用户 Chat Assistant 映射）

表名：`kb_qa_user_chat_assistants`

| 字段 | 类型 | 索引 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | 主键 |
| user_id | INTEGER | UNIQUE, INDEX | 用户 ID（无外键约束，跨 Base） |
| ragflow_chat_id | VARCHAR | - | RAGFlow Chat Assistant ID |
| created_at | TIMESTAMP | - | 创建时间 |
| last_used_at | TIMESTAMP | INDEX | 最后使用时间（LRU 清理依据） |

> `user_id` 有意不设外键约束，因为 `users` 表属于 `agentic_qa.database.Base`，跨 Base 无法建立 FK。

### KbQaSession（会话）

表名：`kb_qa_sessions`

| 字段 | 类型 | 索引 | 说明 |
|------|------|------|------|
| id | VARCHAR (UUID) | PK | 主键 |
| user_id | INTEGER | INDEX | 用户 ID |
| title | VARCHAR | - | 会话标题 |
| created_at | TIMESTAMP | - | 创建时间 |
| updated_at | TIMESTAMP | - | 更新时间 |

### KbQaMessage（消息）

表名：`kb_qa_messages`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| session_id | VARCHAR | FK → KbQaSession |
| role | VARCHAR | `user` / `assistant` |
| content | TEXT | 消息内容（回答文本） |
| used_kb_ids | JSON | 使用的知识库 ID 列表 |
| rag_references | JSON | RAGFlow 引用（文档块、相似度、页码） |
| created_at | TIMESTAMP | 创建时间 |

### 实体关系

```
KbQaSession (1) ──→ (N) KbQaMessage

UserChatAssistant: 独立表，user_id 1:1 映射到 RAGFlow Chat Assistant
```

---

## 后端服务层

### KbQaService（核心服务）

文件：`backend/services/knowledge_qa/kb_qa_service.py`

主入口 `chat()` 方法编排完整问答流程：

| 步骤 | 调用 | 说明 |
|------|------|------|
| 1 | `repository.get_recent_messages()` | 加载最近 20 条消息 |
| 2 | `MessageHistoryBuilder.build()` | 构建上下文窗口 |
| 3 | `repository.get_all_kbs()` | 获取可用知识库 |
| 4 | `KbRouter.route()` | LLM 路由到相关知识库 |
| 5 | `ChatAssistantManager.get_or_create()` | 获取/创建 Chat Assistant |
| 6 | `ChatAssistantManager.update_datasets()` | 更新绑定数据集 |
| 7 | `ragflow_client.chat_sync()` | 调用 RAGFlow 问答 |
| 8 | `repository.save_message()` | 持久化消息 |

### KbRouter（知识库路由器）

文件：`backend/services/knowledge_qa/kb_router.py`

LLM 驱动的知识库选择，返回 JSON 数组格式的知识库 ID 列表。手动选择的知识库始终保留。

### MessageHistoryBuilder（上下文管理器）

文件：`backend/services/knowledge_qa/message_history.py`

上下文窗口策略：最近 N 轮原样保留，更早轮次 LLM 压缩摘要，Token 上限截断。

### ChatAssistantManager（助手管理器）

文件：`backend/services/knowledge_qa/chat_assistant_mgr.py`

用户级 RAGFlow Chat Assistant 生命周期管理：懒创建、数据集更新、重名恢复、删除。

### KbQaRepository（数据访问层）

文件：`backend/services/knowledge_qa/repository.py`

三个表的 CRUD 操作，包括 `find_idle_chat_assistants()` 用于 LRU 清理。

### 清理任务

文件：`backend/services/knowledge_qa/tasks/cleanup_chat_assistants.py`

Celery Beat 定时任务，删除超过 `kbqa_session_idle_days`（默认 7 天）未使用的 Chat Assistant。

---

## API 端点

所有接口前缀为 `/api/kb-qa`，需要 Bearer Token 认证。

### 问答

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat` | POST | 主问答入口 |

**请求**：
```json
{
  "question": "808D数控系统的主轴驱动参数如何设置？",
  "session_id": "uuid-xxx",
  "manual_kb_ids": ["kb-1", "kb-2"]
}
```

**响应**：
```json
{
  "answer": "根据《808D操作手册》第5章...",
  "references": [
    {
      "document_id": "doc-xxx",
      "dataset_id": "ds-xxx",
      "document_name": "808D操作手册.pdf",
      "similarity": 0.87,
      "positions": [{"page": 42, "from": 0, "to": 150}],
      "content": "主轴参数设置..."
    }
  ],
  "used_kb_ids": ["kb-1"],
  "message_id": 123,
  "session_id": "uuid-xxx"
}
```

### 会话管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/sessions` | POST | 创建会话 |
| `/sessions` | GET | 会话列表 |
| `/sessions/{session_id}` | DELETE | 删除会话（级联删除消息） |
| `/sessions/{session_id}/messages` | GET | 消息列表（最多 200 条） |

### 知识库

| 端点 | 方法 | 说明 |
|------|------|------|
| `/kbs` | GET | 可用知识库列表（含文档数量） |

**响应**：
```json
[
  {
    "id": "kb-uuid",
    "name": "808D数控设备文档",
    "kb_type": "device_doc",
    "description": "...",
    "document_count": 42
  }
]
```

仅返回 `document_count > 0` 的知识库（通过 KnowledgeBase → DocumentCategory → PlanItem → Document → DocumentVersion JOIN 计算）。

### 文档代理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/ragflow/document-preview` | GET | 代理 RAGFlow 文档预览（Base64） |
| `/ragflow/document-download` | GET | 代理 RAGFlow 文档下载（PDF 流） |

参数：`dataset_id`, `document_id`。代理请求避免前端直接访问 RAGFlow 的跨域问题。

---

## 前端架构

### 路由

| 路由 | 组件 | 标题 |
|------|------|------|
| `/knowledge-qa` | `KnowledgeQaPage.vue` | 知识库问答 |

### 页面布局

三栏布局：

```
┌──────────────┬──────────────────────────┬──────────────┐
│              │                          │              │
│  SessionList │    消息区域               │ KbRightPanel │
│  (会话列表)  │    CitationMessage        │ (知识库面板) │
│              │    (问答消息+引用)         │              │
│  - 创建      │                          │ - AI匹配     │
│  - 选择      │    ┌──────────────────┐  │ - 手动选择   │
│  - 删除      │    │ 输入框            │  │              │
│              │    └──────────────────┘  │              │
└──────────────┴──────────────────────────┴──────────────┘
                                               │
                                        ┌──────▼──────┐
                                        │KbSelector   │
                                        │Modal        │
                                        │(知识库选择)  │
                                        └─────────────┘
```

### 组件

| 组件 | 说明 |
|------|------|
| `KnowledgeQaPage.vue` | 主页面，三栏布局 |
| `SessionList.vue` | 会话列表（创建/选择/删除，刷新记忆按钮） |
| `CitationMessage.vue` | 消息渲染（用户消息 + 助手消息 + 引用标记 + 引用卡片） |
| `KbRightPanel.vue` | 右侧面板（AI 匹配的知识库 + 手动选择的知识库） |
| `KbSelectorModal.vue` | 知识库选择弹窗（按类型分组：合规/设备/SOP/自定义，支持搜索，过滤空库） |

### 引用渲染

助手消息中 RAGFlow 返回的引用标记 `##N$$` 被渲染为可点击的上标徽章。点击弹出引用详情卡片：

```
┌─────────────────────────────────────┐
│ 📄 808D操作手册.pdf                   │
│ 相似度: 87% | 第 42 页               │
│                                      │
│ "主轴参数设置方法：进入参数菜单..."    │
│                                      │
│ [预览] [下载]                        │
└─────────────────────────────────────┘
```

复用 `sql_qa` 模块的 `SqlQaCitationPopup` 组件实现文档预览。

### 状态管理

`composables/knowledge_qa/useKbQa.js` — Vue Composable：

| 状态 | 说明 |
|------|------|
| `sessions` | 会话列表 |
| `currentSessionId` | 当前会话 ID |
| `messages` | 当前会话消息 |
| `availableKbs` | 可用知识库列表 |
| `manualKbIds` | 手动选择的知识库 ID |
| `loading` | 加载状态 |
| `error` | 错误信息 |

特性：
- 乐观 UI 更新（用户消息立即显示，不等 API 返回）
- 自动创建会话（首次使用时）

### API 客户端

`api/kbQaClient.js` — Axios 实例，方法：`listKbs()`, `listSessions()`, `createSession()`, `deleteSession()`, `listMessages()`, `chat()`, `previewDocument()`, `getDocumentDownloadUrl()`。

---

## 配置管理

KBQA 配置在 `backend/core/agentic_qa/config.py` 中，使用 `kbqa_` 前缀：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `kbqa_router_llm` | 主 LLM 配置 | 知识库路由使用的模型 |
| `kbqa_router_timeout` | `8.0` | 路由 LLM 超时（秒） |
| `kbqa_chat_timeout` | `30.0` | RAGFlow 问答超时（秒） |
| `kbqa_history_full_turns` | `3` | 完整保留的最近轮次 |
| `kbqa_max_context_tokens` | `6000` | 上下文窗口 Token 上限 |
| `kbqa_summary_model` | 主 LLM 配置 | 历史摘要使用的模型 |
| `kbqa_session_idle_days` | `7` | Chat Assistant LRU 清理阈值（天） |
| `kbqa_chat_assistant_name_prefix` | `"user-"` | RAGFlow Chat Assistant 名称前缀 |

共享配置（来自 agentic_qa）：

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` / `{PROVIDER}_API_KEY` | LLM API Key |
| `RAGFLOW_BASE_URL` | RAGFlow 服务地址 |
| `RAGFLOW_API_KEY` | RAGFlow API Key |

---

## 测试覆盖

| 测试文件 | 覆盖范围 |
|----------|----------|
| `tests/test_kb_qa_service.py` | `KbQaService.chat()` 正常流程、路由降级到手动 KB、降级到全部 KB |
| `tests/test_kb_qa_routes.py` | 路由模块可导入，暴露 `router`, `ChatRequest`, `ChatResponse`, `KbOut` |
| `tests/test_kb_qa_models.py` | 3 个 ORM 模型继承正确的 Base，包含必需字段 |
| `tests/test_kbqa_config.py` | 所有 `kbqa_*` 配置项存在且默认值正确 |
| `tests/test_kbqa_repository.py` | `KbQaRepository` 方法签名完整 |
| `tests/test_message_history.py` | 空历史、最近轮保留、旧轮摘要、Token 截断 |
| `tests/test_chat_assistant_mgr.py` | 复用已有 chat、创建新 chat、更新数据集 |
| `tests/test_cleanup_task.py` | 删除空闲 chat、跳过无空闲情况 |
| `tests/test_kb_router.py` | 保留手动 KB、处理 LLM 失败、解析 JSON 响应 |

---

## 目录结构

```
backend/
├── models/
│   └── knowledge_qa.py                  # 3 个 ORM 模型
│
├── services/knowledge_qa/               # 服务层
│   ├── __init__.py
│   ├── kb_qa_service.py                 # 核心问答服务
│   ├── kb_router.py                     # LLM 知识库路由器
│   ├── message_history.py               # 上下文窗口管理器
│   ├── chat_assistant_mgr.py            # Chat Assistant 生命周期
│   ├── repository.py                    # 数据访问层
│   └── tasks/
│       ├── __init__.py
│       └── cleanup_chat_assistants.py   # LRU 清理 Celery 任务
│
├── routes/knowledge_qa/                 # API 路由
│   ├── __init__.py
│   └── routes.py                        # REST API 端点
│
└── services/agentic_qa/ragflow/
    └── client.py                        # 共享 RAGFlow 客户端

frontend/src/
├── views/knowledge_qa/
│   ├── KnowledgeQaPage.vue              # 主页面（三栏布局）
│   └── components/
│       ├── SessionList.vue              # 会话列表
│       ├── CitationMessage.vue          # 消息 + 引用渲染
│       ├── KbRightPanel.vue             # 右侧知识库面板
│       └── KbSelectorModal.vue          # 知识库选择弹窗
├── composables/knowledge_qa/
│   └── useKbQa.js                       # 状态管理 Composable
└── api/
    └── kbQaClient.js                    # API 客户端

tests/
├── test_kb_qa_service.py
├── test_kb_qa_routes.py
├── test_kb_qa_models.py
├── test_kbqa_config.py
├── test_kbqa_repository.py
├── test_message_history.py
├── test_chat_assistant_mgr.py
├── test_cleanup_task.py
└── test_kb_router.py
```

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 前端 | Vue 3 (Composition API) | SPA |
| 后端 | FastAPI (Python 3.13) | REST API |
| ORM | SQLAlchemy 2.0 | 数据模型 |
| 数据库 | PostgreSQL | 会话/消息/助手映射 |
| RAG 平台 | RAGFlow | 文档向量检索 + Chat Assistant API |
| LLM | 可配置 Provider（DeepSeek 默认） | 知识库路由 + 历史摘要 |
| HTTP 客户端 | Axios | 前端 API 调用 |
| 任务队列 | Celery + Redis | Chat Assistant LRU 清理 |
| 认证 | JWT | Bearer Token |
