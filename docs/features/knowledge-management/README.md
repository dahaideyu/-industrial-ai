# 知识库管理模块

工业设备知识库管理系统，支持文档全生命周期管理：收集、审核、发布、切片、检索。

---

## 功能概述

| 功能 | 说明 |
|------|------|
| 知识库管理 | 创建和管理多个知识库，按业务主题组织文档 |
| 文档类别 | 对文档进行分类管理（操作手册、故障案例、PLC 图纸等） |
| 收集计划 | 定义文档收集任务的范围、对象和时间安排 |
| 文档上传 | 支持 PDF、Word、Excel 等多种格式 |
| 格式转换 | LibreOffice 自动转换 Office 文档格式 |
| 内容提取 | MarkItDown + Tesseract OCR 提取文档文本内容 |
| PLC 图纸解析 | AI 视觉模型解析 PLC 梯形图/流程图 PDF，生成分析报告 |
| AI 审核 | 基于 DeepSeek 大模型自动评估文档质量和相关性 |
| 人工审批 | 审核通过后需人工批准才能发布 |
| RAGFlow 同步 | 发布后自动同步到 RAGFlow 进行切片和向量化 |
| 切片查看 | 在线预览文档原文和 RAGFlow 切片结果 |
| 版本管理 | 文档支持多版本，可回滚到历史版本 |
| 进度看板 | 可视化展示知识库和收集计划的整体进度 |

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端 (Vue 3)                         │
│  知识库列表 → 详情 → 文档上传 → AI审核 → 人工审批 → 切片查看  │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API
┌──────────────────────────▼──────────────────────────────────┐
│                    后端 (FastAPI)                            │
│  路由层 → 服务层 → 核心层（模型/配置/数据库）                  │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ 知识库   │  │ 文档     │  │ 收集     │  │ 审核     │    │
│  │ 服务     │  │ 服务     │  │ 计划服务 │  │ 服务     │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└───────┬────────────┬────────────┬────────────┬──────────────┘
        │            │            │            │
   ┌────▼────┐  ┌────▼────┐  ┌───▼───┐  ┌────▼────┐
   │PostgreSQL│  │  MinIO  │  │ Redis │  │DeepSeek │
   │ 元数据   │  │ 文件存储│  │消息队列│  │ AI审核  │
   └─────────┘  └─────────┘  └───┬───┘  └─────────┘
                                  │
                           ┌──────▼──────┐
                           │Celery Worker│
                           │ 异步任务执行 │
                           └──────┬──────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
              ┌─────▼─────┐ ┌────▼────┐ ┌─────▼─────┐
              │ MarkItDown │ │LibreOffice│ │  RAGFlow  │
              │ 文本提取   │ │  转换    │ │ 切片+向量 │
              │ + Tesseract│ │         │ │           │
              │   OCR     │ │         │ │           │
              └───────────┘ └─────────┘ └───────────┘
```

---

## 快速开始

### 1. 启用模块

在 `.env` 中添加：

```bash
ENABLE_KNOWLEDGE_BASE=true
```

### 2. 启动基础设施

```bash
docker compose up -d knb-postgresql knb-redis knb-minio knb-libreoffice knb-celery-worker
```

### 3. 启动应用

```bash
ENABLE_KNOWLEDGE_BASE=true uv run uvicorn backend.app:app --host 0.0.0.0 --port 9300
```

访问 `http://localhost:9300`，进入「知识库管理」页面即可开始使用。

> 详细部署说明见 [DEPLOYMENT.md](./DEPLOYMENT.md)
> 用户操作手册见 [USER_GUIDE.md](./USER_GUIDE.md)

---

## 目录结构

```
backend/
├── core/knowledge_management/          # 核心层
│   ├── config.py                       # 配置（Pydantic Settings）
│   ├── database.py                     # PostgreSQL 连接和会话管理
│   ├── models.py                       # SQLAlchemy 数据模型
│   └── exceptions.py                   # 自定义异常
│
├── clients/knowledge_management/       # 外部服务客户端
│   ├── minio_client.py                 # MinIO 对象存储客户端
│   ├── ragflow_client.py              # RAGFlow API 客户端
│   ├── markitdown_client.py           # MarkItDown 文本提取客户端
│   └── libreoffice_client.py          # LibreOffice 转换客户端
│
├── services/knowledge_management/      # 服务层
│   ├── knowledge_base_svc.py           # 知识库 CRUD
│   ├── category_svc.py                # 文档类别管理
│   ├── target_svc.py                  # 收集对象管理
│   ├── document_svc.py                # 文档上传和管理
│   ├── plan_svc.py                    # 收集计划管理
│   ├── review_svc.py                  # AI 审核服务
│   ├── ragflow_sync_svc.py            # RAGFlow 同步服务
│   ├── evaluation_svc.py              # 评估服务
│   ├── plc_parser_svc.py              # PLC 程序解析
│   └── tasks/                          # Celery 异步任务
│       ├── celery_app.py              # Celery 应用配置
│       ├── convert_tasks.py           # 格式转换任务
│       ├── extract_tasks.py           # 内容提取任务
│       ├── review_tasks.py            # AI 审核任务
│       ├── sync_tasks.py              # RAGFlow 同步任务
│       ├── plc_tasks.py               # PLC 解析任务
│       └── evaluation_tasks.py        # 评估任务
│
├── routes/knowledge_management/        # API 路由层
│   └── routes.py                       # REST API 端点
│
└── app.py                              # 集成入口（ENABLE_KNOWLEDGE_BASE 控制）

frontend/src/views/knowledge_management/  # 前端组件
├── KnowledgeBaseList.vue               # 知识库列表页
├── KnowledgeBaseDetail.vue             # 知识库详情页
├── CollectionPlanDetail.vue            # 收集计划详情页
├── DocumentManagement.vue              # 文档管理页
└── components/
    ├── MultiSelect.vue                 # 多选组件（带搜索、全选、反选）
    ├── CustomSelect.vue                # 自定义下拉选择组件
    ├── FilePreview.vue                 # 文件预览组件
    └── ChunkViewer.vue                 # 切片查看组件
```

---

## UI 组件说明

### MultiSelect 多选组件

支持搜索、全选、反选、清空功能的多选列表组件。

**Props:**
| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| modelValue | Array | [] | 已选中的值（v-model） |
| options | Array | [] | 选项列表，格式：`[{ value, label, sub }]` |
| label | String | '选项' | 标签文本 |
| required | Boolean | false | 是否必填 |

**特性:**
- 搜索过滤：支持按 label 和 sub 字段搜索
- 全选/取消全选：基于当前搜索结果进行操作
- 反选：反转所有选项的选中状态
- 清空：清除所有已选项
- 搜索框清除按钮：一键清除搜索词

### 弹窗布局规范

| 弹窗 | 宽度 | 布局 |
|------|------|------|
| 新建收集计划 | max-w-4xl | 第一排：名称+时间+优先级；第二排：类别(左)+对象(右) |
| 新增收集项 | max-w-4xl | 第一排：优先级+截止时间；第二排：类别(左)+对象(右) |
| 文档提取内容 | 90vw | 超宽显示，方便查看长文本 |

---

## API 概览

所有接口前缀为 `/api/knowledge-management`，需要 Bearer Token 认证。

| 接口 | 方法 | 说明 |
|------|------|------|
| `/bases` | GET | 获取知识库列表 |
| `/bases` | POST | 创建知识库 |
| `/bases/{id}` | GET | 获取知识库详情 |
| `/bases/{id}` | PUT | 更新知识库 |
| `/bases/{id}` | DELETE | 删除知识库 |
| `/bases/{id}/categories` | GET | 获取文档类别列表 |
| `/bases/{id}/categories` | POST | 创建文档类别 |
| `/bases/{id}/targets` | GET | 获取收集对象列表 |
| `/bases/{id}/targets` | POST | 创建收集对象 |
| `/bases/{id}/plans` | GET | 获取收集计划列表 |
| `/bases/{id}/plans` | POST | 创建收集计划 |
| `/plans/{id}` | GET | 获取计划详情 |
| `/plans/{id}/items` | GET | 获取计划文档列表 |
| `/documents` | POST | 上传文档 |
| `/documents/{id}` | GET | 获取文档详情 |
| `/documents/{id}/review` | POST | 提交 AI 审核 |
| `/documents/{id}/approve` | POST | 人工审批 |
| `/documents/{id}/publish` | POST | 发布文档 |
| `/documents/{id}/chunks` | GET | 获取文档切片 |
| `/documents/{id}/versions` | GET | 获取版本历史 |
| `/documents/{id}/preview` | GET | 预览文档 |

> 完整 API 文档请访问 `http://localhost:9300/docs`（Swagger UI）。
