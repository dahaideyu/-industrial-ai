# PLC 图纸智能解析模块 — 开发者文档

基于双模型（视觉 + 文本）流水线的 PLC 电气原理图自动解析工具，将 PDF 图纸转换为结构化 Markdown 分析报告。作为知识管理模块的子功能，通过文件上传自动触发。

---

## 目录

- [功能概述](#功能概述)
- [系统架构](#系统架构)
- [四步处理流水线](#四步处理流水线)
- [知识管理模块集成](#知识管理模块集成)
- [Celery 异步任务与进度追踪](#celery-异步任务与进度追踪)
- [前端 UI 交互](#前端-ui-交互)
- [配置管理](#配置管理)
- [目录结构](#目录结构)
- [技术栈](#技术栈)

---

## 功能概述

| 功能 | 说明 |
|------|------|
| PDF 图纸解析 | 输入 PLC 电气原理图 PDF，自动解析为结构化分析报告 |
| 双模型架构 | 视觉模型逐页微观分析 + 文本模型全局宏观整合 |
| 全品牌兼容 | 西门子、三菱、欧姆龙、罗克韦尔 AB、汇川、台达、信捷等 |
| 全图纸类型 | 主回路、控制回路、梯形图、功能块、IO 分配、通信拓扑、伺服/变频器 |
| 自动生成报告 | 6 章节 Markdown 报告：基本信息、宏观概览、微观详情、交叉引用、维护建议、总结 |
| 进度追踪 | 0%-100% 实时进度更新，前端可视化展示 |
| 子文档关联 | 解析报告自动作为子文档关联到原图纸文档 |
| 自动重生成 | 原图纸更新时自动清理旧报告并重新生成 |
| 验证机制 | 页数完整性检查 + 宏观微观一致性校验 |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     输入：PLC 电气原理图 PDF                   │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: PDF 预处理 (pdf_processor.py)                       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ pymupdf 打开 PDF → 逐页渲染为图片 (300 DPI)             │ │
│  │   ↓                                                    │ │
│  │ image_processor: 对比度/锐度增强 + 空白页检测            │ │
│  │   ↓                                                    │ │
│  │ 输出: List[PageMetadata] (base64 编码图片)              │ │
│  └────────────────────────────────────────────────────────┘ │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: 微观解析 (micro_parser.py) — 视觉模型               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 逐页调用视觉 LLM (DashScope OpenAI 兼容 API)            │ │
│  │   ↓                                                    │ │
│  │ 固定 5 章节提示词:                                      │ │
│  │   ① 页面信息 ② 元器件清单 ③ 回路逻辑                   │ │
│  │   ④ 保护回路 ⑤ 标注说明                                │ │
│  │   ↓                                                    │ │
│  │ 输出: 逐页 Markdown 文本（拼接）                        │ │
│  └────────────────────────────────────────────────────────┘ │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: 宏观分析 (macro_parser.py) — 文本模型               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 将 Step 2 全部结果一次性输入文本 LLM                     │ │
│  │   ↓                                                    │ │
│  │ 固定 4 章节提示词:                                      │ │
│  │   ① 系统架构 ② 信号流向 ③ 系统层级 ④ 设计洞察          │ │
│  │   ↓                                                    │ │
│  │ 输出: 系统级架构分析 Markdown                           │ │
│  └────────────────────────────────────────────────────────┘ │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: 报告生成 (report_generator.py)                      │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 组装 6 章节 Markdown 报告:                              │ │
│  │   ① 基本信息 ② 宏观概览 ③ 微观详情                     │ │
│  │   ④ 交叉引用 ⑤ 维护建议 ⑥ 总结                         │ │
│  │   ↓                                                    │ │
│  │ 辅助函数:                                               │ │
│  │   - extract_cross_references: 提取交叉引用              │ │
│  │   - extract_maintenance_suggestions: 提取维护建议       │ │
│  │   - count_sections: 统计章节数                          │ │
│  └────────────────────────────────────────────────────────┘ │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  验证层 (validators.py)                                      │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 页数完整性: 实际解析页数 vs 预期页数                      │ │
│  │ 一致性检查: 宏观引用的页码是否在微观结果中存在            │ │
│  └────────────────────────────────────────────────────────┘ │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     输出：Markdown 分析报告                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 四步处理流水线

### Step 1: PDF 预处理

**文件**：`pdf_processor.py`

| 操作 | 说明 |
|------|------|
| PDF 打开 | 使用 pymupdf 打开 PDF 文件 |
| 页面渲染 | 逐页渲染为图片，DPI 默认 300 |
| 图片增强 | `image_processor.py` 执行对比度增强、锐度提升 |
| 空白页检测 | 自动识别并跳过空白页 |
| Base64 编码 | 将图片编码为 base64 供视觉模型调用 |

**输出**：`List[PageMetadata]`，每页包含 base64 图片、页码、是否空白等元数据。

### Step 2: 微观解析（视觉模型）

**文件**：`micro_parser.py`

逐页顺序调用视觉 LLM，每页使用固定 5 章节提示词：

```
请分析此 PLC 电气原理图页面，按以下章节输出：

1. 页面信息：页面标题、图纸编号、所属系统
2. 元器件清单：所有电气元器件（型号、规格、位置）
3. 回路逻辑：主回路/控制回路的连接关系和工作原理
4. 保护回路：过载、短路、接地等保护回路分析
5. 标注说明：技术参数、线号、端子号等标注信息
```

**提示词文件**：`utils/prompts.py`

### Step 3: 宏观分析（文本模型）

**文件**：`macro_parser.py`

将 Step 2 的全部微观结果一次性输入文本 LLM，使用固定 4 章节提示词：

```
基于以下逐页分析结果，请从系统层面进行整体分析：

1. 系统架构：整体电气系统结构和组成
2. 信号流向：主要信号/能量传递路径
3. 系统层级：各子系统之间的层级关系和交互
4. 设计洞察：设计特点、潜在问题、优化建议
```

### Step 4: 报告生成

**文件**：`report_generator.py`

组装最终 6 章节 Markdown 报告：

| 章节 | 内容来源 | 说明 |
|------|----------|------|
| 基本信息 | 输入参数 | 文件名、页数、解析时间 |
| 宏观概览 | Step 3 输出 | 系统架构、信号流向、层级关系 |
| 微观详情 | Step 2 输出 | 逐页详细分析 |
| 交叉引用 | 辅助函数提取 | 跨页面引用关系 |
| 维护建议 | 辅助函数提取 | 维护保养建议 |
| 总结 | 综合 | 整体评估和关键发现 |

---

## 知识管理模块集成

PLC 解析模块通过知识管理模块的文件上传流程触发。

### 触发流程

```
用户在 CollectionPlanDetail.vue 上传文件
  ↓
选择 file_type="plc"，上传 PDF 文件
  ↓
document_svc.py 检测到 file_type == "plc"
  ↓
触发 parse_plc_task.delay(version_id)
  ↓
Celery 异步执行完整流水线
```

### 调用接口

```python
from backend.services.plc_analysis_report import plc_service

# 执行完整分析
result = plc_service.analyze(
    pdf_path="/path/to/drawing.pdf",
    micro_progress_callback=lambda pct, detail: update_progress(pct, detail)
)

# result 包含:
# - markdown_report: str (Markdown 报告内容)
# - page_count: int (页数)
# - micro_results: str (微观解析结果)
# - macro_result: str (宏观分析结果)
```

### 关键文件

| 文件 | 角色 |
|------|------|
| `backend/services/knowledge_management/plc_parser_svc.py` | `DrawingParserService` 门面，委托 `plc_service.analyze()` |
| `backend/services/knowledge_management/tasks/plc_tasks.py` | Celery 任务：`parse_plc_task` + `update_child_documents` |
| `backend/services/knowledge_management/document_svc.py` | 上传处理器，触发 PLC 解析 |
| `backend/core/knowledge_management/models.py` | `DocumentVersion` 模型中的 `drawing_parse_*` 字段 |

### 数据模型扩展

`DocumentVersion` 模型中与 PLC 解析相关的字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `file_type` | VARCHAR | `plc` 标识 PLC 文件 |
| `drawing_parse_status` | VARCHAR | 解析状态：`pending` / `processing` / `done` / `failed` |
| `drawing_parse_progress` | FLOAT | 进度百分比（0-100） |
| `drawing_parse_step` | VARCHAR | 当前步骤描述 |
| `drawing_parse_detail` | VARCHAR | 步骤详情 |
| `parent_document_id` | UUID | 父文档关联（报告→原图） |
| `auto_generated` | BOOLEAN | 自动生成标识 |

---

## Celery 异步任务与进度追踪

### parse_plc_task

位于 `backend/services/knowledge_management/tasks/plc_tasks.py`。

**执行流程**：

```
① 从 MinIO 下载 PDF 到临时目录
    ↓ 进度: 5%
② 设置进度回调，实时更新 DocumentVersion.drawing_parse_progress
    ↓
③ 调用 plc_parser_svc.parse_drawing_file(local_path, callback)
    ↓ 进度: 10%-80%
   ├─ 微观解析: 20%-60%（逐页递增）
   ├─ 宏观分析: 70%
   └─ 报告生成: 80%
    ↓
④ 上传生成的 Markdown 报告到 MinIO
    ↓ 进度: 95%
   文件名: {原始文件名}_说明文档.md
    ↓
⑤ 创建子文档:
   - 新建 Document + DocumentVersion
   - auto_generated=True
   - parent_document_id 关联原图纸文档
   - 放在同一计划项下
    ↓
⑥ 更新父文档状态为 done
    ↓ 进度: 100%
```

**错误处理**：`max_retries=3`，重试间隔 60 秒。

### update_child_documents

当父图纸文档更新时触发：
1. 删除旧的自动生成报告（MinIO + 数据库）
2. 重置父文档解析进度
3. 重新触发 `parse_plc_task`

### 进度追踪

前端通过轮询 `GET /versions/{version_id}/progress` 获取实时进度。后端在 Celery 任务中通过回调函数更新 `DocumentVersion` 的 `drawing_parse_progress` 字段。

---

## 前端 UI 交互

### 上传入口

**组件**：`CollectionPlanDetail.vue`

- 上传对话框中选择文件类型 "图纸"
- 蓝色提示框说明视觉 AI 将自动解析 PDF 图纸
- 拖拽上传支持（`DocumentUpload.vue`）

### 进度卡片

当 `drawing_parse_status === 'processing'` 时显示：

```
┌─────────────────────────────────────────┐
│ 🔄 正在解析 PLC 图纸...                  │
│                                          │
│ 📄 文件名: SIEMENS_808D_电器原理图.pdf    │
│                                          │
│ ████████████░░░░░░░░  65%               │
│                                          │
│ 当前步骤: 微观解析 - 第 12/20 页          │
│ 详情: 正在分析主回路控制逻辑...            │
│                                          │
│ ⚠️ 解析过程中请勿进行其他操作             │
└─────────────────────────────────────────┘
```

- 渐变蓝色卡片
- 旋转动画
- 进度条 + 百分比
- 当前步骤描述 + 详情文本
- 操作警告提示

### 失败卡片

当 `drawing_parse_status === 'failed'` 时显示红色错误卡片，展示错误信息。

### 文件类型标识

- PLC 文档在列表中显示琥珀色 "图纸" 徽章
- `DocumentReview.vue` 审核组件下拉包含 "PLC程序" 选项

### 自动生成的子文档

- 解析报告作为子文档显示在同一计划项下
- 标记为 `auto_generated`，与手动上传文档区分
- 通过 `parent_document_id` 关联到原图纸

---

## 配置管理

由 `backend/services/plc_analysis_report/config.py` 管理：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PLC_DASHSCOPE_API_KEY` | (必填) | DashScope API Key |
| `PLC_VISION_MODEL` | `qwen-vl-plus` | 视觉模型 |
| `PLC_TEXT_MODEL` | `qwen3.6-plus` | 文本模型 |
| `PLC_DPI` | `300` | PDF 渲染 DPI |
| `PLC_MAX_RETRIES` | `3` | API 调用重试次数 |
| `PLC_REQUEST_TIMEOUT` | `120` | 请求超时（秒） |

---

## 目录结构

```
backend/services/plc_analysis_report/    # PLC 解析核心服务
├── __init__.py                          # 导出 plc_service 单例
├── main.py                              # PLCAnalysisService 类
├── config.py                            # 配置（DashScope）
├── pdf_processor.py                     # PDF 预处理
├── micro_parser.py                      # 微观解析（视觉模型）
├── macro_parser.py                      # 宏观分析（文本模型）
├── report_generator.py                  # 报告生成
└── utils/
    ├── __init__.py
    ├── prompts.py                       # 提示词模板
    ├── image_processor.py              # 图片增强 + 空白页检测
    ├── validators.py                   # 页数完整性 + 一致性验证
    └── logger.py                       # 生产级日志（轮转 + 错误分离）

# 知识管理集成文件
backend/services/knowledge_management/
├── plc_parser_svc.py                    # DrawingParserService 门面
├── tasks/plc_tasks.py                   # Celery 任务
├── tasks/compliance_vision_tasks.py     # 复用 PLC 配置做合规视觉检测
└── document_svc.py                      # 上传触发逻辑

backend/core/knowledge_management/
└── models.py                            # DocumentVersion 的 drawing_parse_* 字段

backend/routes/knowledge_management/
└── routes.py                            # 暴露解析进度字段的 API
```

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| PDF 处理 | PyMuPDF (>= 1.26) | PDF 解析、页面渲染为图片 |
| 图片处理 | Pillow (PIL) | 对比度/锐度增强、空白页检测 |
| 视觉模型 | Qwen-VL-Plus (DashScope) | 逐页视觉解析 |
| 文本模型 | Qwen3.6-Plus (DashScope) | 宏观架构分析 |
| API 客户端 | OpenAI Python SDK | DashScope OpenAI 兼容接口调用 |
| 配置管理 | pydantic-settings | 环境变量自动加载 |
| 任务队列 | Celery + Redis | 异步 PLC 解析任务（`kb_plc` 队列） |
| 对象存储 | MinIO | PDF 输入 + Markdown 报告输出 |
| 数据库 | PostgreSQL | 解析进度持久化 |
| 前端 | Vue 3 + Tailwind CSS | 进度卡片 UI |
| 容器化 | Docker Compose | celery worker 消费 kb_plc 队列 |
| 日志 | Python logging + TimedRotatingFileHandler | 30 天轮转，Windows 兼容 |
