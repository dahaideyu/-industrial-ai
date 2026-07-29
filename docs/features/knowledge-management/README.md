# 知识库管理模块 — 开发者文档

工业设备知识库全生命周期管理平台，覆盖文档收集、AI 审核、人工审批、RAGFlow 向量化检索的完整链路。

---

## 目录

- [功能概述](#功能概述)
- [技术架构](#技术架构)
- [数据库模型](#数据库模型)
- [API 端点](#api-端点)
- [Celery 异步任务体系](#celery-异步任务体系)
- [前端组件与路由](#前端组件与路由)
- [核心工作流](#核心工作流)
- [外部服务客户端](#外部服务客户端)
- [配置管理](#配置管理)
- [目录结构](#目录结构)
- [技术栈](#技术栈)

---

## 功能概述

| 功能 | 说明 |
|------|------|
| 知识库管理 | 创建和管理多个知识库，按设备类型/合规/自定义分类组织 |
| 文档类别 | 三级预设类别树（设备文档、SOP 文档、合规文档），支持自定义扩展 |
| 收集计划 | 按类别 × 对象笛卡尔积自动生成收集项，追踪完成进度 |
| 文档上传 | 支持 PDF、Word、Excel、图片等格式，拖拽上传 |
| 格式转换 | LibreOffice 自动将 Office 文档转换为 PDF |
| 内容提取 | MarkItDown + RapidOCR 提取文档文本（含扫描件 OCR） |
| PLC 图纸解析 | 视觉 AI 解析 PLC 电气原理图 PDF，自动生成 Markdown 分析报告 |
| 合规检测 | 视觉模型检测印章、签名、有效期，合规评分体系 |
| AI 审核 | DeepSeek 大模型自动评估文档相关性（0-100）和质量（0-100） |
| 人工审批 | 审核通过后需人工批准/驳回 |
| RAGFlow 同步 | 发布后自动上传到 RAGFlow 进行切片和向量化 |
| 切片查看 | 在线预览 RAGFlow 切片结果和文档原文 |
| 版本管理 | 文档支持多版本，可回滚，删除已发布版本自动清理 RAGFlow |
| 进度看板 | 四维 AI 健康诊断（进度/质量/合规/缺失） |
| 设备同步 | 从 AQA MySQL 自动同步设备类型，自动创建知识库结构 |
| 操作日志 | 全链路审计日志 |

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         前端 (Vue 3 + Tailwind CSS)                  │
│  Dashboard → Workshop → DeviceType → KB Detail → Plan → Documents   │
│  ComplianceView / CategoryAdmin / KnowledgeOverview / ChunkViewer   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ REST API (/api/knowledge-management/*)
┌───────────────────────────────▼─────────────────────────────────────┐
│                        FastAPI 后端                                  │
│                                                                      │
│  路由层 (routes/knowledge_management/routes.py, ~2100行)             │
│    │                                                                 │
│    ▼                                                                 │
│  服务层                                                               │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐           │
│  │ knowledge_base │ │ document_svc   │ │ plan_svc       │           │
│  │ _svc           │ │ 文档上传/版本  │ │ 收集计划CRUD   │           │
│  │ KB CRUD +      │ │ MinIO 交互     │ │ 笛卡尔积生成   │           │
│  │ RAGFlow 同步   │ │ PLC 触发       │ │                │           │
│  └────────────────┘ └────────────────┘ └────────────────┘           │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐           │
│  │ review_svc     │ │ evaluation_svc │ │ ragflow_sync   │           │
│  │ AI审核触发     │ │ LLM 评估打分   │ │ _svc           │           │
│  │ 人工审批       │ │ 计划项/计划    │ │ 发布到RAGFlow  │           │
│  └────────────────┘ └────────────────┘ └────────────────┘           │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐           │
│  │ category_svc   │ │ preset_category│ │ device_sync    │           │
│  │ 类别CRUD       │ │ _svc           │ │ _svc           │           │
│  │                │ │ 预设类别树管理 │ │ 设备类型同步   │           │
│  └────────────────┘ └────────────────┘ └────────────────┘           │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐           │
│  │ knowledge_     │ │ plc_parser_svc │ │ operation_log  │           │
│  │ overview_svc   │ │ PLC图纸解析    │ │ _svc           │           │
│  │ 四维健康诊断   │ │                │ │ 审计日志       │           │
│  └────────────────┘ └────────────────┘ └────────────────┘           │
│    │                                                                 │
│    ▼                                                                 │
│  核心层 (core/knowledge_management/)                                 │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐       │
│  │ models.py  │ │ config.py  │ │ database.py│ │exceptions.py│       │
│  │ 11个ORM    │ │ Pydantic   │ │ SQLAlchemy │ │ 自定义异常  │       │
│  │ 数据模型   │ │ Settings   │ │ engine     │ │            │       │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘       │
└───────┬──────────────┬──────────────┬──────────────┬────────────────┘
        │              │              │              │
   ┌────▼────┐   ┌─────▼─────┐  ┌────▼────┐  ┌─────▼─────┐
   │PostgreSQL│   │   MinIO   │  │  Redis  │  │ DeepSeek  │
   │ 元数据   │   │ 文件存储  │  │ 消息队列│  │ LLM 评估  │
   └────┬────┘   └───────────┘  └────┬────┘  └───────────┘
        │                            │
        │                      ┌─────▼──────┐
        │                      │Celery Worker│
        │                      │ 7个专用队列 │
        │                      └─────┬──────┘
        │                            │
        │         ┌──────────┬───────┼────────┬──────────┐
        │         │          │       │        │          │
        │   ┌─────▼────┐ ┌──▼───┐ ┌─▼──┐ ┌──▼───┐ ┌───▼────┐
        │   │MarkItDown│ │Libre │ │RAG │ │Vision│ │  PLC   │
        │   │+RapidOCR │ │Office│ │Flow│ │Model │ │Parser  │
        │   │ 文本提取 │ │ 转换 │ │同步│ │合规  │ │图纸解析│
        │   └──────────┘ └──────┘ └────┘ └──────┘ └────────┘
        │
   ┌────▼─────┐
   │ RAGFlow  │
   │ 切片+向量│
   │ 检索     │
   └──────────┘
```

---

## 数据库模型

所有表名以 `knb_` 为前缀，使用 PostgreSQL，主键为 UUID。

### 1. KnowledgeBase（知识库）

表名：`knb_knowledge_bases`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| name | VARCHAR | 知识库名称 |
| kb_type | VARCHAR | 类型：`device_doc` / `sop_doc` / `compliance` / `history` / `custom` |
| description | TEXT | 描述 |
| workshop | VARCHAR | 所属车间 |
| device_type | VARCHAR | 设备类型（设备文档 KB 关联） |
| ragflow_dataset_id | VARCHAR | RAGFlow 数据集 ID |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

### 2. DocumentCategory（文档类别）

表名：`knb_document_categories`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| kb_id | UUID | FK → KnowledgeBase |
| name | VARCHAR | 类别名称 |
| parent_id | UUID | 父类别（支持三级树形结构） |
| preset_category_id | UUID | FK → PresetCategory（关联预设类别） |
| sort_order | INT | 排序序号 |

### 3. CollectionTarget（收集对象）

表名：`knb_collection_targets`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| kb_id | UUID | FK → KnowledgeBase |
| name | VARCHAR | 对象名称（设备型号、车间、基地等） |
| description | TEXT | 描述 |

### 4. CollectionPlan（收集计划）

表名：`knb_collection_plans`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| kb_id | UUID | FK → KnowledgeBase |
| name | VARCHAR | 计划名称 |
| plan_type | VARCHAR | 类型：`device_doc` / `sop_doc` / `compliance` / `history` / `custom` |
| priority | INT | 优先级 |
| deadline | DATE | 截止日期 |
| status | VARCHAR | 状态 |

### 5. PlanItem（收集计划项）

表名：`knb_plan_items`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| plan_id | UUID | FK → CollectionPlan |
| category_id | UUID | FK → DocumentCategory |
| target_id | UUID | FK → CollectionTarget |
| not_applicable | BOOLEAN | 是否标记为不适用 |
| relevance_score | FLOAT | AI 评估相关性分数 |
| quality_score | FLOAT | AI 评估质量分数 |
| evaluation_text | TEXT | AI 评估文本 |

唯一约束：`(plan_id, category_id, target_id)` — 每个计划中类别×对象的笛卡尔积唯一。

### 6. Document（文档）

表名：`knb_documents`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| plan_item_id | UUID | FK → PlanItem |
| name | VARCHAR | 文档名称 |
| created_at | TIMESTAMP | 创建时间 |

### 7. DocumentVersion（文档版本）

表名：`knb_document_versions`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| document_id | UUID | FK → Document |
| version_number | INT | 版本号 |
| file_type | VARCHAR | 文件类型：`general` / `table` / `image` / `manual` / `plc` |
| file_name | VARCHAR | 原始文件名 |
| file_path | VARCHAR | MinIO 存储路径 |
| file_size | BIGINT | 文件大小 |
| content | TEXT | 提取的文本内容 |
| status | VARCHAR | 状态：`pending` / `extracting` / `reviewing` / `approved` / `rejected` / `published` |
| relevance_score | FLOAT | AI 相关性分数（0-100） |
| quality_score | FLOAT | AI 质量分数（0-100） |
| review_text | TEXT | AI 审核评语 |
| extract_status | VARCHAR | 提取状态 |
| extract_progress | FLOAT | 提取进度（0-100） |
| drawing_parse_status | VARCHAR | PLC 图纸解析状态 |
| drawing_parse_progress | FLOAT | PLC 解析进度（0-100） |
| drawing_parse_step | VARCHAR | PLC 当前解析步骤 |
| drawing_parse_detail | VARCHAR | PLC 解析详情 |
| parent_document_id | UUID | 父文档（PLC 自动生成的报告关联原图） |
| auto_generated | BOOLEAN | 是否自动生成 |
| compliance_stamp | BOOLEAN | 合规印章检测 |
| compliance_signature | BOOLEAN | 合规签名检测 |
| compliance_valid_from | DATE | 有效期起始 |
| compliance_valid_to | DATE | 有效期截止 |
| published_at | TIMESTAMP | 发布时间 |
| created_at | TIMESTAMP | 创建时间 |

### 8. RAGDocumentMap（RAGFlow 文档映射）

表名：`knb_rag_document_map`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| version_id | UUID | FK → DocumentVersion (1:1) |
| ragflow_document_id | VARCHAR | RAGFlow 文档 ID |
| ragflow_dataset_id | VARCHAR | RAGFlow 数据集 ID |
| parse_status | VARCHAR | RAGFlow 解析状态 |
| chunk_count | INT | 切片数量 |

### 9. PresetCategory（预设类别）

表名：`knb_preset_categories`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| name | VARCHAR | 类别名称 |
| parent_id | UUID | 父类别 |
| kb_type | VARCHAR | 适用的 KB 类型 |
| sort_order | INT | 排序 |
| is_active | BOOLEAN | 是否启用 |

种子数据包含 70+ 预设叶子类别，覆盖设备文档（电气图纸、机械图纸、PLC 程序等）和 SOP 文档（操作规程、质量标准等）。

### 10. OperationLog（操作日志）

表名：`knb_operation_logs`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| user_id | VARCHAR | 操作用户 |
| action | VARCHAR | 操作类型 |
| target_type | VARCHAR | 操作对象类型 |
| target_id | UUID | 操作对象 ID |
| detail | JSONB | 操作详情 |
| created_at | TIMESTAMP | 操作时间 |

### 11. KbTypeState（知识库类型状态）

表名：`knb_kb_type_states`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| kb_type | VARCHAR | KB 类型 |
| enabled | BOOLEAN | 是否启用 |

### 实体关系图

```
KnowledgeBase (1) ──→ (N) DocumentCategory
KnowledgeBase (1) ──→ (N) CollectionTarget
KnowledgeBase (1) ──→ (N) CollectionPlan

CollectionPlan (1) ──→ (N) PlanItem [unique: plan + category + target]
PlanItem (1) ──→ (N) Document
Document (1) ──→ (N) DocumentVersion
DocumentVersion (1) ──→ (1) RAGDocumentMap

PresetCategory (1) ──→ (N) DocumentCategory [preset_category_id FK]
```

---

## API 端点

所有接口前缀为 `/api/knowledge-management`，需要 Bearer Token 认证。

### 知识库 CRUD

| 端点 | 方法 | 说明 |
|------|------|------|
| `/bases` | POST | 创建知识库（同时创建 RAGFlow 数据集） |
| `/bases` | GET | 列表（支持 kb_type/workshop/device_type 过滤） |
| `/bases/{kb_id}` | GET | 详情 |
| `/bases/{kb_id}` | PUT | 更新 |
| `/bases/{kb_id}` | DELETE | 删除（级联删除 RAGFlow 数据集） |
| `/bases/{kb_id}/rag-documents` | GET | RAGFlow 数据集中的文档列表 |

### KB 类型状态

| 端点 | 方法 | 说明 |
|------|------|------|
| `/kb-type-states` | GET | 所有 KB 类型的启用状态 |
| `/kb-type-states/{kb_type}` | PUT | 切换启用/禁用 |

### 文档类别

| 端点 | 方法 | 说明 |
|------|------|------|
| `/bases/{kb_id}/categories` | POST | 创建类别 |
| `/bases/{kb_id}/categories` | GET | 列表 |
| `/categories/{cat_id}` | PUT | 更新 |
| `/categories/{cat_id}` | DELETE | 删除 |

### 收集对象

| 端点 | 方法 | 说明 |
|------|------|------|
| `/bases/{kb_id}/targets` | POST | 创建对象 |
| `/bases/{kb_id}/targets` | GET | 列表 |
| `/targets/{target_id}` | PUT | 更新 |
| `/targets/{target_id}` | DELETE | 删除 |

### 收集计划

| 端点 | 方法 | 说明 |
|------|------|------|
| `/plans` | POST | 创建计划（自动生成类别×对象笛卡尔积 PlanItem） |
| `/bases/{kb_id}/plans` | GET | 某 KB 下的计划列表 |
| `/plans/{plan_id}` | GET | 计划详情（含 items 和 documents） |
| `/plans/{plan_id}` | PUT | 更新 |
| `/plans/{plan_id}` | DELETE | 删除 |

### 计划项

| 端点 | 方法 | 说明 |
|------|------|------|
| `/plan-items` | POST | 创建单个计划项 |
| `/plan-items/{item_id}` | PUT | 更新 |
| `/plan-items/{item_id}` | DELETE | 删除 |
| `/plan-items/{item_id}/not-applicable` | PUT | 标记为不适用 |
| `/plan-items/{item_id}/not-applicable` | DELETE | 取消不适用标记 |

### 文档操作

| 端点 | 方法 | 说明 |
|------|------|------|
| `/plan-items/{item_id}/upload` | POST | 多文件上传（multipart/form-data） |
| `/documents/{document_id}` | PUT | 更新文档名称 |
| `/documents/{document_id}` | DELETE | 删除文档 |
| `/documents/{document_id}/versions` | GET | 版本列表 |
| `/versions/{version_id}` | DELETE | 删除版本 |

### 版本处理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/versions/{version_id}/progress` | GET | 后台任务进度 |
| `/documents/{version_id}/filetype` | PUT | 设置文件类型 |
| `/versions/{version_id}/ai-review` | POST | 触发 AI 审核 |
| `/versions/{version_id}/approval` | POST | 人工审批（approve/reject） |
| `/versions/{version_id}/publish` | POST | 发布到 RAGFlow |
| `/versions/{version_id}/parse-status` | GET | RAGFlow 解析状态 |
| `/versions/{version_id}/reparse` | POST | 重试 RAGFlow 解析 |
| `/versions/{version_id}/stop-parse` | POST | 停止 RAGFlow 解析 |
| `/versions/{version_id}/preview` | GET | PDF 预览 URL |
| `/versions/{version_id}/preview-file` | GET | 流式 PDF 预览 |
| `/versions/{version_id}/download` | GET | 下载 URL |
| `/versions/{version_id}/raw-file` | GET | 流式原始文件 |

### RAGFlow 文档查看

| 端点 | 方法 | 说明 |
|------|------|------|
| `/rag-documents/{rag_doc_id}/chunks` | GET | 切片列表 |
| `/rag-documents/{rag_doc_id}/preview` | GET | 预览 URL |
| `/rag-documents/{rag_doc_id}/download` | GET | 下载 URL |

### 评估

| 端点 | 方法 | 说明 |
|------|------|------|
| `/plans/{plan_id}/progress` | GET | 计划进度 |
| `/plan-items/{item_id}/evaluate` | POST | 触发计划项评估 |
| `/plan-items/{item_id}/evaluation` | GET | 获取评估结果 |

### Dashboard

| 端点 | 方法 | 说明 |
|------|------|------|
| `/dashboard/base` | GET | 基地维度看板（分数、进度、车间、KB 类型） |
| `/dashboard/workshop` | GET | 车间维度看板 |
| `/dashboard/knowledge-overview` | GET | 四维 AI 健康诊断 |
| `/dashboard/knowledge-overview/summary` | GET | LLM 生成的中文总结 |

### 预设类别管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/preset-categories` | GET | 获取预设类别（flat 或 tree） |
| `/admin/preset-categories` | POST | 创建预设 |
| `/admin/preset-categories/{id}` | PUT | 更新 |
| `/admin/preset-categories/{id}` | DELETE | 软删除 |
| `/admin/preset-categories/sync` | POST | 同步预设到所有 KB |
| `/admin/preset-categories/reseed` | POST | 重新加载种子数据 |

### 设备类型同步

| 端点 | 方法 | 说明 |
|------|------|------|
| `/sync/device-types` | POST | 手动全量同步 |
| `/sync/device-types/status` | GET | 上次同步状态 |
| `/sync/device-type` | POST | 外部 API 触发单设备类型同步（X-API-Key 认证） |

### 合规文档

| 端点 | 方法 | 说明 |
|------|------|------|
| `/versions/{version_id}/compliance-dates` | PUT | 更新有效期和印章/签名 |
| `/versions/{version_id}/retry-review` | POST | 重试合规 AI 审核 |

### 其他

| 端点 | 方法 | 说明 |
|------|------|------|
| `/operation-logs` | GET | 审计日志查询 |
| `/onlyoffice-preview` | GET | OnlyOffice 预览 HTML |
| `/debug/preset-status` | GET | 诊断端点 |
| `/debug/fix-compliance` | POST | 修复合规 KB 结构 |

---

## Celery 异步任务体系

使用 Celery + Redis，配置 7 个专用队列，每个队列可独立扩缩容。

### 队列分配

| 队列名 | 任务 | 说明 |
|--------|------|------|
| `kb_convert` | `convert_to_pdf_task` | Office → PDF 转换 |
| `kb_extract` | `extract_content_task` | 文本提取（MarkItDown + RapidOCR） |
| `kb_review` | `ai_review_task` | AI 文档审核（DeepSeek LLM 打分） |
| `kb_sync` | `publish_to_ragflow_task` | 发布到 RAGFlow |
| `kb_plc` | `parse_plc_task` | PLC 图纸解析 |
| `kb_eval` | `evaluate_item_task` / `evaluate_plan_task` | 计划项/计划评估 |
| `kb_compliance` | `compliance_vision_task` | 合规视觉检测（印章、签名、有效期） |

### 任务流程

```
文件上传 → [kb_convert] 格式转换
               ↓
         [kb_extract] 文本提取
               ↓
         [kb_compliance] 合规视觉检测（仅合规文档）
               ↓
         [kb_review] AI 审核评分
               ↓
         人工审批
               ↓
         [kb_sync] 发布到 RAGFlow
               ↓
         [kb_eval] 自动评估计划项 → 评估计划
```

### Beat 定时任务

| 任务 | 调度 | 说明 |
|------|------|------|
| 设备类型同步 | 每天 03:00 | 从 AQA MySQL 自动同步设备类型 |

---

## 前端组件与路由

### 页面组件

| 组件 | 路由 | 说明 |
|------|------|------|
| `KnowledgeDashboard.vue` | `/knowledge-management` | 主 Dashboard，展示基地维度看板 |
| `WorkshopView.vue` | `/knowledge-management/kb-type/:type` | 车间视图（device_doc / sop_doc） |
| `DeviceTypeView.vue` | `/knowledge-management/kb-type/:type/workshop/:name` | 设备类型钻取视图 |
| `ComplianceView.vue` | `/knowledge-management/compliance` | 合规知识库视图 |
| `KnowledgeBaseDetail.vue` | `/knowledge-management/:id` | 知识库详情 |
| `CollectionPlanDetail.vue` | `/knowledge-management/plans/:id` | 收集计划详情（含文档上传、PLC 进度） |
| `DocumentManagement.vue` | `/knowledge-management/items/:itemId/documents` | 文档管理 |
| `CategoryAdminView.vue` | `/knowledge-management/admin/categories` | 预设类别管理 |
| `CustomDocumentsView.vue` | `/knowledge-management/custom` | 自定义知识库 |
| `KnowledgeOverview.vue` | `/knowledge-overview` | AI 四维健康报告 |

### 子组件

| 组件 | 说明 |
|------|------|
| `DocumentUpload.vue` | 拖拽上传，支持 PLC 文件类型提示 |
| `DocumentReview.vue` | 文档审核（AI + 人工），文件类型下拉 |
| `EvaluationPanel.vue` | 评估面板 |
| `ProgressDashboard.vue` | 进度看板 |
| `ChunkViewer.vue` | RAGFlow 切片查看器 |
| `FilePreview.vue` | 文件预览（PDF/图片） |
| `KbCard.vue` | 知识库卡片 |
| `KbTypeSwitch.vue` | KB 类型切换开关 |
| `HierarchyTree.vue` | 层级树组件 |
| `CustomSelect.vue` | 自定义下拉选择 |
| `MultiSelect.vue` | 多选组件（搜索/全选/反选） |

### 状态管理

`composables/knowledge_management/useKnowledgeManagement.js` — 模块级单例模式，提供：
- 知识库 CRUD 操作
- 文档上传和版本管理
- 收集计划管理
- 评估触发和结果获取
- Dashboard 数据获取

### API 客户端

`api/knowledgeManagementClient.js` — Axios 实例，JWT 拦截器自动附加 Bearer Token。

---

## 核心工作流

### 1. 文档全生命周期

```
上传文件 → MinIO 存储
    ↓
[kb_convert] LibreOffice 转 PDF（Office 文件）
    ↓
[kb_extract] MarkItDown + RapidOCR 提取文本
    ↓
[kb_compliance] 视觉模型检测印章/签名/有效期（仅合规文档）
    ↓
[kb_review] DeepSeek LLM 评分（相关性 0-100 + 质量 0-100）
    ↓
人工审批（通过/驳回）
    ↓
[kb_sync] 上传到 RAGFlow → 触发切片和向量化
    ↓
[kb_eval] 自动评估计划项 → 更新计划进度
```

### 2. 设备类型自动同步

```
定时任务 / 手动触发
    ↓
查询 AQA MySQL 获取所有设备类型
    ↓
对每个新设备类型自动创建：
  ├── 1 个统一知识库
  ├── 1 个 RAGFlow 数据集
  ├── 预设类别（device_doc + sop_doc）
  ├── 收集对象
  ├── 2 个收集计划（设备文档 + SOP）
  └── 笛卡尔积计划项（类别 × 对象）
    ↓
创建合规知识库（独立预设类别）
```

### 3. 合规文档特殊处理

- 上传后自动触发视觉模型检测（印章 + 签名 + 有效期）
- 合规评分体系：印章 (+40) + 签名 (+30) + 有效日期 (+30)
- 过期文档直接给 0 分
- 必须填写有效期后才能触发 AI 审核

### 4. PLC 图纸解析集成

```
上传 PDF 文件，file_type="plc"
    ↓
[kb_plc] parse_plc_task 异步执行
    ↓
Step 1: PDF 预处理（PyMuPDF 渲染为图片）
    ↓
Step 2: 微观解析（视觉模型逐页分析）
    ↓
Step 3: 宏观分析（文本模型整体架构分析）
    ↓
Step 4: 生成 Markdown 报告
    ↓
上传报告到 MinIO
创建子文档（auto_generated=True, parent_document_id 关联原图）
更新父文档状态为 done
```

前端实时显示进度卡片（进度条 + 当前步骤 + 详情）。

### 5. AI 四维健康诊断

| 维度 | 评估内容 |
|------|----------|
| 进度维度 | 收集计划完成率、各类型文档覆盖率 |
| 质量维度 | AI 审核平均分、低分文档占比 |
| 合规维度 | 合规文档有效期状态、印章/签名覆盖率 |
| 缺失维度 | 缺失文档类型识别、关键文档空缺 |

最终由 LLM 生成中文总结报告。

---

## 外部服务客户端

| 客户端 | 文件 | 说明 |
|--------|------|------|
| MinIO | `clients/knowledge_management/minio_client.py` | S3 兼容对象存储，文件上传/下载/删除/预签名 URL |
| RAGFlow | `clients/knowledge_management/ragflow_client.py` | RAGFlow API（数据集/文档/切片/检索操作） |
| MarkItDown | `clients/knowledge_management/markitdown_client.py` | 文本提取，集成 RapidOCR 处理扫描件 |
| LibreOffice | `clients/knowledge_management/libreoffice_client.py` | 文档→PDF 转换，调用镜像内置的 libreoffice 命令 |

---

## 配置管理

由 `backend/core/knowledge_management/config.py` 的 Pydantic Settings 管理：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_KNOWLEDGE_BASE` | `false` | 启用知识库模块 |
| `KNB_POSTGRES_URL` | (必填) | PostgreSQL 连接串 |
| `KNB_REDIS_URL` | `redis://localhost:6379/1` | Redis（Celery broker） |
| `KNB_MINIO_ENDPOINT` | (必填) | MinIO 地址 |
| `KNB_MINIO_ACCESS_KEY` | (必填) | MinIO Access Key |
| `KNB_MINIO_SECRET_KEY` | (必填) | MinIO Secret Key |
| `KNB_MINIO_BUCKET` | `knowledge-base` | MinIO Bucket |
| `KNB_RAGFLOW_BASE_URL` | (必填) | RAGFlow 地址 |
| `KNB_RAGFLOW_API_KEY` | (必填) | RAGFlow API Key |
| `KNB_LLM_API_KEY` | (必填) | DeepSeek API Key |
| `KNB_LLM_BASE_URL` | `https://api.deepseek.com/v1` | LLM API 地址 |
| `KNB_LLM_MODEL` | `deepseek-chat` | LLM 模型 |
| `KNB_VISION_API_KEY` | (必填) | 视觉模型 API Key（DashScope） |
| `KNB_VISION_BASE_URL` | (必填) | 视觉模型 API 地址 |
| `KNB_VISION_MODEL` | `qwen-vl-plus` | 视觉模型名称 |
| `KNB_AQA_MYSQL_HOST` | (必填) | AQA MySQL 主机（设备同步用） |

---

## 目录结构

```
backend/
├── core/knowledge_management/          # 核心层
│   ├── config.py                       # Pydantic Settings 配置
│   ├── database.py                     # SQLAlchemy engine + 会话管理 + 迁移
│   ├── models.py                       # 11 个 ORM 数据模型
│   ├── exceptions.py                   # 自定义异常体系
│   └── preset_seed.py                  # 70+ 预设类别种子数据
│
├── clients/knowledge_management/       # 外部服务客户端
│   ├── minio_client.py                 # MinIO 对象存储
│   ├── ragflow_client.py              # RAGFlow API
│   ├── markitdown_client.py           # MarkItDown + RapidOCR 文本提取
│   └── libreoffice_client.py          # LibreOffice 文档转换
│
├── services/knowledge_management/      # 服务层
│   ├── knowledge_base_svc.py           # 知识库 CRUD + RAGFlow 同步
│   ├── document_svc.py                # 文档上传/版本管理/MinIO 交互
│   ├── plan_svc.py                    # 收集计划 CRUD + 笛卡尔积生成
│   ├── evaluation_svc.py              # LLM 评估（计划项/计划）
│   ├── review_svc.py                  # AI 审核触发 + 人工审批
│   ├── ragflow_sync_svc.py            # RAGFlow 发布同步
│   ├── category_svc.py                # 文档类别 CRUD
│   ├── preset_category_svc.py         # 预设类别树管理 + 同步
│   ├── device_sync_svc.py             # AQA MySQL 设备类型自动同步
│   ├── kb_type_state_svc.py           # KB 类型启用/禁用
│   ├── operation_log_svc.py           # 审计日志
│   ├── user_svc.py                    # 用户查询
│   ├── target_svc.py                  # 收集对象 CRUD
│   ├── plc_parser_svc.py              # PLC 图纸解析（委托 plc_analysis_report）
│   ├── knowledge_overview_svc.py      # 四维健康诊断
│   └── tasks/                          # Celery 异步任务
│       ├── celery_app.py              # Celery 配置 + Beat 调度 + 7 个队列
│       ├── convert_tasks.py           # Office → PDF 转换
│       ├── extract_tasks.py           # 文本提取（MarkItDown + RapidOCR）
│       ├── review_tasks.py            # AI 审核（DeepSeek LLM 评分）
│       ├── sync_tasks.py              # RAGFlow 发布
│       ├── plc_tasks.py               # PLC 图纸解析
│       ├── evaluation_tasks.py        # 计划项/计划评估
│       └── compliance_vision_tasks.py # 合规视觉检测
│
├── routes/knowledge_management/        # API 路由层
│   └── routes.py                       # REST API 端点 (~2100行)
│
└── app.py                              # 集成入口（ENABLE_KNOWLEDGE_BASE 控制）

frontend/src/
├── views/knowledge_management/         # 页面组件
│   ├── KnowledgeDashboard.vue          # 主 Dashboard
│   ├── WorkshopView.vue               # 车间视图
│   ├── DeviceTypeView.vue             # 设备类型视图
│   ├── ComplianceView.vue             # 合规视图
│   ├── KnowledgeBaseList.vue          # 知识库列表
│   ├── KnowledgeBaseDetail.vue        # 知识库详情
│   ├── CollectionPlanDetail.vue       # 收集计划详情
│   ├── DocumentManagement.vue         # 文档管理
│   ├── CategoryAdminView.vue          # 预设类别管理
│   ├── CustomDocumentsView.vue        # 自定义知识库
│   ├── KnowledgeOverview.vue          # AI 健康报告
│   └── components/                     # 子组件
│       ├── DocumentUpload.vue          # 拖拽上传
│       ├── DocumentReview.vue          # 文档审核
│       ├── EvaluationPanel.vue         # 评估面板
│       ├── ProgressDashboard.vue       # 进度看板
│       ├── ChunkViewer.vue             # 切片查看
│       ├── FilePreview.vue             # 文件预览
│       ├── KbCard.vue                  # 知识库卡片
│       ├── KbTypeSwitch.vue            # KB 类型开关
│       ├── HierarchyTree.vue           # 层级树
│       ├── CustomSelect.vue            # 下拉选择
│       └── MultiSelect.vue             # 多选组件
├── composables/knowledge_management/
│   └── useKnowledgeManagement.js       # 状态管理（模块级单例）
└── api/
    └── knowledgeManagementClient.js    # Axios API 客户端

deploy/docker/
├── init-sql/schemas/
│   └── 02_schema_knowledge_base.sql    # 数据库 Schema
└── docker-compose.yml                  # knb-celery-worker 服务
```

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 后端框架 | FastAPI (Python 3.13) | 异步 REST API |
| ORM | SQLAlchemy 2.0 | 数据库模型和查询 |
| 数据库 | PostgreSQL | 元数据存储（UUID PK, JSONB） |
| 任务队列 | Celery + Redis | 异步任务（7 个专用队列） |
| 对象存储 | MinIO | 文档文件存储 |
| RAG 平台 | RAGFlow | 文档切片、向量化、检索 |
| LLM | DeepSeek（可配置） | 文档评估、计划分析 |
| 视觉模型 | Qwen-VL-Plus (DashScope) | 合规检测、PLC 图纸解析 |
| 文本提取 | MarkItDown + RapidOCR | 文档内容提取（含 OCR） |
| 文档转换 | LibreOffice | Office → PDF |
| 前端框架 | Vue 3 (Composition API) | SPA |
| CSS | Tailwind CSS | 样式 |
| HTTP 客户端 | Axios | API 调用（JWT 拦截器） |
| 容器化 | Docker Compose | 部署 |
