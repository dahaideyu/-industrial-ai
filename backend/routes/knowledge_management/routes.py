# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库管理 API 路由层

路由前缀: /api/knowledge-management
认证: Bearer Token (复用 auth 模块 verify_token)
"""
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from backend.core.knowledge_management.database import get_db
from backend.core.knowledge_management.exceptions import (
    NotFoundError,
    ValidationError,
    RAGFlowError,
)
from backend.core.knowledge_management.models import (
    CollectionPlan,
    CollectionTarget,
    Document,
    DocumentCategory,
    DocumentVersion,
    KnowledgeBase,
    PlanItem,
    PresetCategory,
    RAGDocumentMap,
)
from backend.core.response import success_response, error_response
from backend.modules.auth.service import verify_token
from services.knowledge_management.device_sync_svc import device_sync_svc
from services.knowledge_management.preset_category_svc import preset_category_svc
from services.knowledge_management.operation_log_svc import oplog_svc
from services.knowledge_management.user_svc import user_svc
from backend.services.knowledge_management.knowledge_overview_svc import KnowledgeOverviewService
from backend.core.knowledge_management.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-management", tags=["knowledge-management"])

# ============================================================
#  OnlyOffice 预览页面
# ============================================================

ONLYOFFICE_PREVIEW_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>文档预览</title>
<style>
  body { margin: 0; padding: 0; overflow: hidden; width: 100vw; height: 100vh; }
  #placeholder { display: flex; align-items: center; justify-content: center; height: 100%; color: #666; font-size: 14px; flex-direction: column; }
  #debug { margin-top: 10px; font-size: 11px; color: #999; max-width: 80%; word-break: break-all; }
</style>
</head>
<body>
<div id="placeholder">初始化中...</div>
<div id="editor"></div>
<script>
(function() {
  var params = new URLSearchParams(window.location.search);
  var fileUrl = params.get('url');
  var title = params.get('title') || '文档';
  var mode = params.get('mode') || 'view';
  if (!fileUrl) { document.getElementById('placeholder').innerHTML = '缺少文件URL'; return; }
  var lower = title.toLowerCase();
  var ext = lower.split('.').pop() || 'docx';
  var docType = 'word';
  if (ext === 'xlsx' || ext === 'xls' || ext === 'xlsm') docType = 'cell';
  else if (ext === 'pptx' || ext === 'ppt') docType = 'slide';

  document.getElementById('placeholder').innerHTML = '加载 OnlyOffice API...<div id="debug">文件: ' + title + '<br>扩展名: ' + ext + '<br>类型: ' + docType + '</div>';

  var config = {
    document: { fileType: ext, key: Date.now().toString(), title: title, url: fileUrl, permissions: { edit: false, download: true }},
    editorConfig: { mode: mode, lang: 'zh-CN', user: {id:'viewer',name:'预览用户'},
      callbackUrl: document.location.origin + '/callback',
      customization: { autosave: false, forcesave: false, compactHeader: true, toolbarNoTabs: true }
    },
    documentType: docType, height: '100%', width: '100%'
  };
  var s = document.createElement('script');
  s.src = 'http://localhost:9980/web-apps/apps/api/documents/api.js';
  s.onload = function() {
    document.getElementById('placeholder').style.display = 'none';
    try { new DocsAPI.DocEditor('editor', config); }
    catch(e) { document.getElementById('placeholder').style.display='flex'; document.getElementById('placeholder').innerHTML = 'OnlyOffice初始化失败: '+e.message; }
  };
  s.onerror = function() { document.getElementById('placeholder').innerHTML = '无法加载 OnlyOffice API (localhost:9980)，请确认服务已启动'; };
  document.head.appendChild(s);
})();
</script>
</body>
</html>"""


@router.get("/onlyoffice-preview")
def onlyoffice_preview_page():
    """OnlyOffice 预览页面"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=ONLYOFFICE_PREVIEW_HTML)


# ============================================================
#  认证依赖
# ============================================================

async def get_current_user(authorization: str = Header(None)):
    """从 Authorization 头提取 Bearer Token 并校验。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未认证")
    token = authorization.split(" ", 1)[1]
    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    return username


# ============================================================
#  序列化辅助
# ============================================================

def _serialize_kb(kb: KnowledgeBase) -> dict:
    # 计算各计划类型的进度
    doc_progress = None
    sop_progress = None
    doc_score = None
    sop_score = None
    doc_count = 0
    if hasattr(kb, 'plans') and kb.plans:
        for plan in kb.plans:
            total = 0
            completed = 0
            for item in plan.plan_items:
                if not item.not_applicable:
                    total += 1
                    if item.overall_status == 'completed':
                        completed += 1
                if item.documents:
                    doc_count += len(item.documents)
            p = round(completed / total * 100, 1) if total > 0 else 0
            if plan.plan_type == 'device_doc':
                doc_progress = p
                doc_score = plan.overall_score
            elif plan.plan_type == 'sop_doc':
                sop_progress = p
                sop_score = plan.overall_score
    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
        "rag_dataset_id": kb.rag_dataset_id,
        "vector_model": kb.vector_model,
        "chunk_method": kb.chunk_method,
        "parser_config": kb.parser_config,
        "device_type": kb.device_type,
        "status": kb.status,
        "tags": kb.tags,
        "sync_type": kb.sync_type,
        "kb_type": kb.kb_type,
        "enabled": kb.enabled if kb.enabled is not None else True,
        "overall_progress": kb.overall_progress or 0,
        "overall_score": kb.overall_score or 0,
        "doc_progress": doc_progress,
        "sop_progress": sop_progress,
        "doc_score": doc_score,
        "sop_score": sop_score,
        "doc_count": doc_count,
        "created_at": _dt(kb.created_at),
        "updated_at": _dt(kb.updated_at),
    }


def _serialize_category(cat: DocumentCategory) -> dict:
    return {
        "id": cat.id,
        "knowledge_base_id": cat.knowledge_base_id,
        "name": cat.name,
        "requirement_desc": cat.requirement_desc,
        "preset_category_id": cat.preset_category_id,
        "parent_id": cat.parent_id,
        "sort_order": cat.sort_order,
        "is_custom": cat.is_custom,
        "created_at": _dt(cat.created_at),
    }


def _serialize_target(target: CollectionTarget) -> dict:
    return {
        "id": target.id,
        "knowledge_base_id": target.knowledge_base_id,
        "name": target.name,
        "target_type": target.target_type,
        "attributes": target.attributes,
        "created_at": _dt(target.created_at),
    }


def _serialize_plan(plan: CollectionPlan) -> dict:
    return {
        "id": plan.id,
        "knowledge_base_id": plan.knowledge_base_id,
        "name": plan.name,
        "description": plan.description,
        "status": plan.status,
        "priority": plan.priority,
        "due_date": plan.due_date,
        "overall_progress": plan.overall_progress,
        "overall_score": plan.overall_score,
        "overall_analysis": plan.overall_analysis,
        "overall_stats": plan.overall_stats,
        "evaluated_at": _dt(plan.evaluated_at),
        "created_at": _dt(plan.created_at),
        "item_count": len(plan.plan_items) if plan.plan_items else 0,
    }


def _serialize_plan_detail(plan: CollectionPlan) -> dict:
    """序列化计划详情，含收集项及文档。"""
    data = _serialize_plan(plan)
    data["plan_items"] = [_serialize_plan_item_detail(item) for item in plan.plan_items]
    return data


def _serialize_plan_item(item: PlanItem) -> dict:
    data = {
        "id": item.id,
        "plan_id": item.plan_id,
        "category_id": item.category_id,
        "target_id": item.target_id,
        "requirement_override": item.requirement_override,
        "priority": item.priority,
        "due_date": _dt(item.due_date),
        "overall_completion": item.overall_completion,
        "overall_score": item.overall_score,
        "overall_status": item.overall_status,
        "evaluation_detail": item.evaluation_detail,
        "evaluated_at": _dt(item.evaluated_at),
        "not_applicable": item.not_applicable,
        "not_applicable_by": item.not_applicable_by,
        "not_applicable_at": _dt(item.not_applicable_at),
        "not_applicable_reason": item.not_applicable_reason,
        "is_custom": item.is_custom,
        # 类别信息（用于收集项页面展示要求）
        "category_name": item.category.name if item.category else None,
        "category_requirement": item.category.requirement_desc if item.category else None,
        "target_name": item.target.name if item.target else None,
    }
    return data


def _serialize_plan_item_detail(item: PlanItem) -> dict:
    """序列化收集项详情，含 category/target/documents 关联。"""
    data = _serialize_plan_item(item)
    data["category"] = _serialize_category(item.category) if item.category else None
    data["target"] = _serialize_target(item.target) if item.target else None
    data["documents"] = [_serialize_document(doc) for doc in item.documents]
    return data


def _serialize_document(doc: Document) -> dict:
    """序列化文档，包含当前版本和草稿版本的关键字段。"""
    versions = sorted(doc.versions, key=lambda v: v.created_at or datetime.min, reverse=True) if doc.versions else []
    current = next((v for v in versions if v.is_current), versions[0] if versions else None)
    # 查找最新草稿版本（非 current 且非 published/replaced）
    draft = next(
        (v for v in versions
         if not v.is_current and v.publish_status not in ("published", "replaced")),
        None,
    )

    data = {
        "id": doc.id,
        "plan_item_id": doc.plan_item_id,
        "display_name": doc.display_name,
        "created_at": _dt(doc.created_at),
        "version_count": len(versions),
    }
    if current:
        data.update({
            "current_version_id": current.id,
            "current_version_label": current.version_label,
            "original_filename": current.original_filename,
            "file_type": current.file_type,
            "status": current.status,
            "publish_status": current.publish_status,
            "ai_relevance_score": current.ai_relevance_score,
            "ai_quality_score": current.ai_quality_score,
            "ai_relevance_remark": current.ai_relevance_remark,
            "ai_quality_remark": current.ai_quality_remark,
            "rejected_reason": current.rejected_reason,
            "file_size": current.file_size,
            "convert_status": current.convert_status,
            "extract_status": current.extract_status,
            "extracted_text": current.extracted_text,
            "parse_status": current.parse_status,
            # 图纸解析进度
            "drawing_parse_status": current.drawing_parse_status,
            "drawing_parse_progress": current.drawing_parse_progress,
            "drawing_parse_step": current.drawing_parse_step,
            "drawing_parse_detail": current.drawing_parse_detail,
            # 合规性字段
            "has_stamp": current.has_stamp,
            "has_signature": current.has_signature,
            "valid_from": _dt(current.valid_from),
            "valid_until": _dt(current.valid_until),
            "compliance_score": current.compliance_score,
        })
        if current.rag_mapping:
            data["rag_document_id"] = current.rag_mapping.rag_document_id
            data["rag_dataset_id"] = current.rag_mapping.rag_dataset_id

    # 草稿版本信息（用于前端判断是否为「已发布 + 草稿审核中」状态）
    if draft:
        data.update({
            "draft_version_id": draft.id,
            "draft_version_label": draft.version_label,
            "draft_status": draft.status,
            "draft_original_filename": draft.original_filename,
            "draft_file_type": draft.file_type,
            "draft_rejected_reason": draft.rejected_reason,
            # 草稿版本的评分信息
            "draft_ai_relevance_score": draft.ai_relevance_score,
            "draft_ai_quality_score": draft.ai_quality_score,
            "draft_ai_relevance_remark": draft.ai_relevance_remark,
            "draft_ai_quality_remark": draft.ai_quality_remark,
            "draft_extracted_text": draft.extracted_text,
            "draft_created_at": _dt(draft.created_at),
            # 合规性字段
            "draft_has_stamp": draft.has_stamp,
            "draft_has_signature": draft.has_signature,
            "draft_valid_from": _dt(draft.valid_from),
            "draft_valid_until": _dt(draft.valid_until),
            "draft_compliance_score": draft.compliance_score,
        })

    # 版本列表（供前端展开查看）
    data["versions"] = [_serialize_version(v) for v in versions]

    return data


def _serialize_version(v: DocumentVersion) -> dict:
    return {
        "id": v.id,
        "document_id": v.document_id,
        "version_label": v.version_label,
        "original_filename": v.original_filename,
        "storage_path": v.storage_path,
        "file_size": v.file_size,
        "file_hash": v.file_hash,
        "status": v.status,
        "file_type": v.file_type,
        "chunk_method": v.chunk_method,
        "extracted_text": v.extracted_text,
        "pdf_preview_path": v.pdf_preview_path,
        "parent_document_id": v.parent_document_id,
        "auto_generated": v.auto_generated,
        "ai_relevance_score": v.ai_relevance_score,
        "ai_quality_score": v.ai_quality_score,
        "ai_relevance_remark": v.ai_relevance_remark,
        "ai_quality_remark": v.ai_quality_remark,
        "rejected_reason": v.rejected_reason,
        "is_current": v.is_current,
        "publish_status": v.publish_status,
        "uploaded_by": v.uploaded_by,
        "convert_status": v.convert_status,
        "extract_status": v.extract_status,
        "parse_status": v.parse_status,
        "has_stamp": v.has_stamp,
        "has_signature": v.has_signature,
        "valid_from": _dt(v.valid_from),
        "valid_until": _dt(v.valid_until),
        "compliance_score": v.compliance_score,
        "drawing_parse_status": v.drawing_parse_status,
        "drawing_parse_progress": v.drawing_parse_progress,
        "drawing_parse_step": v.drawing_parse_step,
        "drawing_parse_detail": v.drawing_parse_detail,
        "created_at": _dt(v.created_at),
    }


def _dt(val) -> Optional[str]:
    """将 datetime/date 转为 ISO 字符串。"""
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return str(val)


def _kb_type_enabled(kb_type: str, disabled_types: set[str]) -> bool:
    """判断一个 kb_type 是否有效启用（处理 device/compliance/custom_base/history 等）。"""
    if kb_type in disabled_types:
        return False
    # device 类型对应 device_doc + sop_doc 两种 plan_type
    if kb_type == 'device':
        return 'device_doc' not in disabled_types
    return True


def _trigger_item_evaluation(plan_item_id: str):
    """文档/版本删除后，异步触发收集项重新评估以更新进度。"""
    try:
        from backend.services.knowledge_management.tasks.evaluation_tasks import (
            evaluate_plan_item_task,
        )
        evaluate_plan_item_task.delay(plan_item_id)
        logger.info("已触发收集项评估: plan_item_id=%s", plan_item_id)
    except Exception:
        logger.warning("触发收集项评估失败: plan_item_id=%s", plan_item_id, exc_info=True)


# ============================================================
#  请求体模型
# ============================================================

class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., description="知识库名称")
    description: str = Field("", description="知识库描述")
    chunk_method: str = Field("naive", description="分块方法")
    parser_config: Optional[dict] = Field(None, description="解析器配置")
    vector_model: Optional[str] = Field(None, description="向量模型")
    kb_type: str = Field("device", description="知识库类型: device/compliance/custom_base/history")
    tags: Optional[dict] = Field(None, description="标签: {base, workshop}")
    sync_type: str = Field("manual", description="同步类型: auto/manual")
    device_type: Optional[str] = Field(None, description="设备类型名称")
    status: str = Field("active", description="状态: active/pending/disabled")


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    vector_model: Optional[str] = None
    chunk_method: Optional[str] = None
    parser_config: Optional[dict] = None
    enabled: Optional[bool] = None  # 启用/禁用（自动 KB 允许此字段）


class CategoryCreate(BaseModel):
    name: str = Field(..., description="类别名称")
    requirement_desc: str = Field("", description="收集要求描述")


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    requirement_desc: Optional[str] = None


class TargetCreate(BaseModel):
    name: str = Field(..., description="收集对象名称")
    target_type: str = Field(..., description="对象类型（如 设备、车间）")
    attributes: Optional[list] = Field(None, description="属性列表 [{label, value}]")


class TargetUpdate(BaseModel):
    name: Optional[str] = None
    target_type: Optional[str] = None
    attributes: Optional[list] = None


class PlanCreate(BaseModel):
    knowledge_base_id: str = Field(..., description="知识库 ID")
    name: str = Field(..., description="计划名称")
    description: str = Field("", description="计划描述")
    priority: str = Field("normal", description="优先级: urgent/normal/optional")
    due_date: Optional[str] = Field(None, description="要求完成时间")
    category_ids: list[str] = Field(default_factory=list, description="文档类别 ID 列表（自定义计划可为空）")
    target_ids: list[str] = Field(default_factory=list, description="收集对象 ID 列表（自定义计划可为空）")
    plan_type: str = Field("device_doc", description="计划类型: device_doc/sop_doc/custom/compliance")
    is_custom: bool = Field(False, description="是否为手动创建的收集计划")


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None


class PlanItemUpdate(BaseModel):
    requirement_override: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None


class PlanItemCreate(BaseModel):
    plan_id: str = Field(..., description="所属收集计划 ID")
    category_id: str = Field("", description="文档类别 ID（自定义项可为空）")
    target_id: str = Field("", description="收集对象 ID（自定义项可为空）")
    name: Optional[str] = Field(None, description="收集项名称（自定义项必填）")
    description: Optional[str] = Field(None, description="收集项描述")
    priority: str = Field("normal", description="优先级: urgent/normal/optional")
    requirement_override: Optional[str] = None
    due_date: Optional[str] = None
    is_custom: bool = Field(False, description="是否为手动创建的收集项")


class FileTypeUpdate(BaseModel):
    file_type: str = Field(..., description="文件类型: general/table/image/manual/plc")


class ApprovalRequest(BaseModel):
    action: str = Field(..., description="操作: approve/reject")
    reason: str = Field("", description="驳回原因（reject 时必填）")


# ============================================================
#  知识库管理
# ============================================================

@router.post("/bases")
def create_knowledge_base(
    body: KnowledgeBaseCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """创建知识库"""
    try:
        from backend.services.knowledge_management.knowledge_base_svc import kb_svc
        kb = kb_svc.create(db, body.model_dump(exclude_none=True))
        return success_response(data=_serialize_kb(kb))
    except RAGFlowError as e:
        return error_response(msg=str(e), code=500)
    except Exception as e:
        logger.exception("创建知识库失败")
        return error_response(msg=f"创建知识库失败: {e}", code=500)


@router.get("/bases")
def list_knowledge_bases(sort_by: str = "progress", sort_order: str = "asc",
                          kb_type: str = None, workshop: str = None,
                          device_type: str = None, db: Session = Depends(get_db)):
    q = db.query(KnowledgeBase).options(
        joinedload(KnowledgeBase.plans)
    )
    if kb_type: q = q.filter(KnowledgeBase.kb_type == kb_type)
    if workshop: q = q.filter(KnowledgeBase.tags['workshop'].astext == workshop)
    if device_type: q = q.filter(KnowledgeBase.device_type == device_type)
    kbs = q.all()
    # sort by overall_progress (ascending = lowest first)
    kbs.sort(key=lambda k: k.overall_progress or 0, reverse=(sort_order == "desc"))
    return success_response(data=[_serialize_kb(kb) for kb in kbs])


@router.get("/bases/{kb_id}")
def get_knowledge_base(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """知识库详情"""
    try:
        kb = db.query(KnowledgeBase).options(
            joinedload(KnowledgeBase.plans).joinedload(CollectionPlan.plan_items)
        ).filter(KnowledgeBase.id == kb_id).first()
        if not kb:
            raise NotFoundError(f"知识库不存在: {kb_id}")
        return success_response(data=_serialize_kb(kb))
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


# ========== 知识库类型启用/禁用状态 ==========

@router.get("/kb-type-states")
def get_kb_type_states(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    """获取所有预置 KB 类型的启用/禁用状态。"""
    from backend.services.knowledge_management.kb_type_state_svc import kb_type_state_svc
    return success_response(data=kb_type_state_svc.list_states(db))


@router.put("/kb-type-states/{kb_type}")
def set_kb_type_state(
    kb_type: str,
    body: dict,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """切换预置 KB 类型的启用/禁用状态。"""
    from backend.services.knowledge_management.kb_type_state_svc import kb_type_state_svc
    enabled = body.get("enabled", True)
    try:
        result = kb_type_state_svc.set_enabled(db, kb_type, enabled, updated_by=current_user)
        return success_response(data=result, msg=f"已{'启用' if enabled else '禁用'} {kb_type}")
    except ValueError as e:
        return error_response(msg=str(e), code=400, status_code=400)


@router.put("/bases/{kb_id}")
def update_knowledge_base(
    kb_id: str,
    body: KnowledgeBaseUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """更新知识库"""
    try:
        from backend.services.knowledge_management.knowledge_base_svc import kb_svc
        existing = db.get(KnowledgeBase, kb_id)
        body_dict = body.model_dump(exclude_none=True)
        # 自动生成的KB只允许修改 enabled 字段（启用/禁用）
        if existing and existing.sync_type == 'auto':
            non_enabled_keys = [k for k in body_dict.keys() if k != 'enabled']
            if non_enabled_keys:
                return error_response(
                    msg=f"自动生成的知识库仅允许启用/禁用，不能修改 {', '.join(non_enabled_keys)}",
                    code=403, status_code=403,
                )
        kb = kb_svc.update(db, kb_id, body_dict)
        return success_response(data=_serialize_kb(kb))
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.delete("/bases/{kb_id}")
def delete_knowledge_base(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """删除知识库"""
    try:
        from backend.services.knowledge_management.knowledge_base_svc import kb_svc
        kb_svc.delete(db, kb_id)
        return success_response(msg="知识库已删除")
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.get("/bases/{kb_id}/rag-documents")
def list_rag_documents(
    kb_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(30, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """RAGFlow 已发布文档列表"""
    try:
        from backend.services.knowledge_management.knowledge_base_svc import kb_svc
        result = kb_svc.get_rag_documents(db, kb_id, page=page, page_size=page_size)
        return success_response(data=result)
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except ValidationError as e:
        return error_response(msg=str(e), code=400, status_code=400)
    except RAGFlowError as e:
        return error_response(msg=str(e), code=500)


@router.get("/bases/{kb_id}/documents-tree")
def get_kb_documents_tree(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取知识库下的文档列表（供左侧树状结构展开使用）。

    查询该 KB 所有收集计划→收集项→文档→当前版本，返回轻量文档信息。
    """
    # 校验 KB 存在
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    docs = (
        db.query(Document)
        .join(PlanItem, Document.plan_item_id == PlanItem.id)
        .join(CollectionPlan, PlanItem.plan_id == CollectionPlan.id)
        .filter(CollectionPlan.knowledge_base_id == kb_id)
        .options(
            joinedload(Document.versions),
            joinedload(Document.plan_item).joinedload(PlanItem.category),
        )
        .all()
    )

    result = []
    for doc in docs:
        current_ver = next((v for v in doc.versions if v.is_current), None)
        category_name = doc.plan_item.category.name if doc.plan_item and doc.plan_item.category else ""
        result.append({
            "id": doc.id,
            "name": doc.display_name or (current_ver.original_filename if current_ver else "未命名"),
            "status": current_ver.status if current_ver else "pending",
            "file_type": current_ver.file_type if current_ver else None,
            "quality_score": current_ver.ai_quality_score if current_ver else None,
            "category_name": category_name,
        })

    return result


# ============================================================
#  文档搜索
# ============================================================

@router.get("/documents/search")
def search_documents(
    q: str = Query(..., min_length=2, description="搜索关键词（≥2字符）"),
    mode: str = Query("keyword", description="搜索模式：keyword / semantic"),
    kb_type: Optional[str] = Query(None, description="知识库类型过滤"),
    workshop: Optional[str] = Query(None, description="车间名称过滤"),
    file_type: Optional[str] = Query(None, description="文件类型过滤"),
    status: Optional[str] = Query(None, description="文档状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=50, description="每页条目数"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """跨所有知识库搜索文档。

    支持两种模式：
    - keyword（默认）：在文档名称和提取文本中做 ILIKE 模糊匹配，覆盖所有文档
    - semantic：通过 RAGFlow retrieval 做语义检索，仅覆盖已发布且已解析的文档
      语义搜索不可用时自动降级为 keyword 模式
    """
    # 转义 ILIKE 通配符，防止用户输入 % 和 _ 干扰
    q_escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    if mode == "semantic":
        result, degraded = _search_semantic(db, q, q_escaped, kb_type, workshop, file_type, status, page, page_size)
        if degraded:
            # 降级到 keyword 模式
            result = _search_keyword(db, q_escaped, kb_type, workshop, file_type, status, page, page_size)
            result["degraded"] = True
            return result
        result["degraded"] = False
        return result

    return _search_keyword(db, q_escaped, kb_type, workshop, file_type, status, page, page_size)


def _apply_filters(query, kb_type, workshop, file_type, status):
    """应用通用过滤条件到搜索查询。"""
    if kb_type:
        # device 类型同时匹配 device_doc 和 sop_doc 的 plan
        if kb_type == "device":
            query = query.filter(KnowledgeBase.kb_type.in_(["device", "device_doc", "sop_doc"]))
        else:
            query = query.filter(KnowledgeBase.kb_type == kb_type)
    if workshop:
        query = query.filter(KnowledgeBase.tags["workshop"].astext == workshop)
    if file_type:
        query = query.filter(DocumentVersion.file_type == file_type)
    if status:
        query = query.filter(DocumentVersion.status == status)
    return query


def _extract_match_context(text: str | None, keyword: str, context_radius: int = 80) -> str:
    """从文本中提取匹配关键词前后的上下文片段。"""
    if not text:
        return ""
    lower_text = text.lower()
    lower_keyword = keyword.lower()
    pos = lower_text.find(lower_keyword)
    if pos < 0:
        return text[:context_radius * 2] + "..." if len(text) > context_radius * 2 else text
    start = max(0, pos - context_radius)
    end = min(len(text), pos + len(keyword) + context_radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end] + suffix


def _build_search_item(doc, ver, kb, category_name: str, match_context: str, rag_doc_id: str | None = None) -> dict:
    """构建搜索结果项的统一结构。"""
    return {
        "document_id": doc.id,
        "version_id": ver.id if ver else None,
        "display_name": doc.display_name or (ver.original_filename if ver else "未命名"),
        "original_filename": ver.original_filename if ver else None,
        "file_type": ver.file_type if ver else None,
        "file_size": ver.file_size if ver else None,
        "status": ver.status if ver else "pending",
        "ai_quality_score": ver.ai_quality_score if ver else None,
        "match_context": match_context,
        "knowledge_base": {
            "id": kb.id,
            "name": kb.name,
            "kb_type": kb.kb_type,
            "device_type": kb.device_type,
            "workshop": (kb.tags or {}).get("workshop", ""),
        },
        "category_name": category_name,
        "rag_dataset_id": kb.rag_dataset_id,
        "rag_document_id": rag_doc_id,
        "created_at": ver.created_at.isoformat() if ver and ver.created_at else None,
    }


def _search_keyword(db, q_escaped, kb_type, workshop, file_type, status, page, page_size):
    """关键词搜索：基于 ILIKE 的模糊匹配。"""
    q_pattern = f"%{q_escaped}%"

    query = (
        db.query(DocumentVersion)
        .join(Document, DocumentVersion.document_id == Document.id)
        .join(PlanItem, Document.plan_item_id == PlanItem.id)
        .join(CollectionPlan, PlanItem.plan_id == CollectionPlan.id)
        .join(KnowledgeBase, CollectionPlan.knowledge_base_id == KnowledgeBase.id)
        .outerjoin(DocumentCategory, PlanItem.category_id == DocumentCategory.id)
        .filter(DocumentVersion.is_current == True)
        .filter(
            or_(
                DocumentVersion.original_filename.ilike(q_pattern),
                Document.display_name.ilike(q_pattern),
                DocumentVersion.extracted_text.ilike(q_pattern),
            )
        )
    )
    query = _apply_filters(query, kb_type, workshop, file_type, status)

    total = query.count()
    items_query = (
        query.order_by(DocumentVersion.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .options(
            joinedload(DocumentVersion.document).joinedload(Document.plan_item).joinedload(PlanItem.category),
        )
    )
    versions = items_query.all()

    # 批量加载 RAG 文档映射，用于预览
    version_ids = [v.id for v in versions]
    rag_maps_by_version: dict = {}
    if version_ids:
        maps = db.query(RAGDocumentMap).filter(RAGDocumentMap.version_id.in_(version_ids)).all()
        rag_maps_by_version = {m.version_id: m.rag_document_id for m in maps}

    items = []
    # 用原始关键词（非转义）提取上下文
    raw_q = q_escaped.replace("\\%", "%").replace("\\_", "_").replace("\\\\", "\\")
    for ver in versions:
        doc = ver.document
        plan_item = doc.plan_item if doc else None
        cat_name = plan_item.category.name if plan_item and plan_item.category else ""
        kb = plan_item.plan.knowledge_base if plan_item and plan_item.plan else None
        if not kb:
            continue

        # 提取匹配上下文：优先用文件名匹配，否则用文本内容
        if doc.display_name and raw_q.lower() in doc.display_name.lower():
            ctx = doc.display_name
        elif ver.original_filename and raw_q.lower() in ver.original_filename.lower():
            ctx = ver.original_filename
        else:
            ctx = _extract_match_context(ver.extracted_text, raw_q)

        rag_doc_id = rag_maps_by_version.get(ver.id)
        items.append(_build_search_item(doc, ver, kb, cat_name, ctx, rag_doc_id))

    return {
        "mode": "keyword",
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


def _search_semantic(db, q, q_escaped, kb_type, workshop, file_type, status, page, page_size):
    """语义搜索：基于 RAGFlow retrieval。返回 (result_dict, degraded_bool)。"""
    try:
        from backend.clients.knowledge_management.ragflow_client import KnowledgeRAGFlowClient
        ragflow = KnowledgeRAGFlowClient()
    except Exception:
        logger.warning("RAGFlow 客户端初始化失败，降级为 keyword 搜索")
        return None, True

    # 收集所有启用 KB 的 rag_dataset_id
    kb_query = db.query(KnowledgeBase).filter(
        KnowledgeBase.status == "active",
        KnowledgeBase.enabled == True,
        KnowledgeBase.rag_dataset_id.isnot(None),
    )
    if kb_type:
        if kb_type == "device":
            kb_query = kb_query.filter(KnowledgeBase.kb_type.in_(["device", "device_doc", "sop_doc"]))
        else:
            kb_query = kb_query.filter(KnowledgeBase.kb_type == kb_type)
    if workshop:
        kb_query = kb_query.filter(KnowledgeBase.tags["workshop"].astext == workshop)

    active_kbs = kb_query.all()
    if not active_kbs:
        return {
            "mode": "semantic", "degraded": False,
            "total": 0, "page": page, "page_size": page_size, "items": [],
        }, False

    dataset_ids = [kb.rag_dataset_id for kb in active_kbs if kb.rag_dataset_id]
    if not dataset_ids:
        return {
            "mode": "semantic", "degraded": False,
            "total": 0, "page": page, "page_size": page_size, "items": [],
        }, False

    # 调用 RAGFlow retrieval
    try:
        retrieval_result = ragflow.retrieval(
            dataset_ids=dataset_ids,
            question=q,
            page=page,
            page_size=page_size,
            keyword=True,
        )
    except Exception as e:
        logger.warning("RAGFlow retrieval 调用失败，降级为 keyword 搜索: %s", e)
        return None, True

    chunks = retrieval_result.get("chunks", [])
    total = retrieval_result.get("total", len(chunks))

    # 按 rag_document_id 反查文档映射
    rag_doc_ids = [c.get("document_id", "") for c in chunks if c.get("document_id")]
    rag_maps = {}
    if rag_doc_ids:
        maps = db.query(RAGDocumentMap).filter(
            RAGDocumentMap.rag_document_id.in_(rag_doc_ids)
        ).all()
        rag_maps = {m.rag_document_id: m for m in maps}

    # 构建 KB 缓存（避免重复查询）
    kb_cache = {kb.id: kb for kb in active_kbs}

    items = []
    for chunk in chunks:
        rag_doc_id = chunk.get("document_id", "")
        chunk_content = chunk.get("content", "")
        similarity = chunk.get("similarity", 0)

        rag_map = rag_maps.get(rag_doc_id)
        if not rag_map:
            continue

        ver = db.query(DocumentVersion).options(
            joinedload(DocumentVersion.document).joinedload(Document.plan_item).joinedload(PlanItem.category),
        ).filter(DocumentVersion.id == rag_map.version_id).first()
        if not ver:
            continue

        doc = ver.document
        plan_item = doc.plan_item if doc else None
        cat_name = plan_item.category.name if plan_item and plan_item.category else ""
        plan = plan_item.plan if plan_item else None
        kb = plan.knowledge_base if plan else None
        if not kb:
            # 从缓存中查找
            kb = kb_cache.get(plan.knowledge_base_id) if plan else None
        if not kb:
            continue

        # 应用额外的过滤条件（file_type, status）
        if file_type and ver.file_type != file_type:
            continue
        if status and ver.status != status:
            continue

        item = _build_search_item(doc, ver, kb, cat_name, chunk_content, rag_doc_id)
        item["similarity"] = round(similarity, 4)
        items.append(item)

    return {
        "mode": "semantic",
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }, False


# ============================================================
#  文档类别
# ============================================================

@router.post("/bases/{kb_id}/categories")
def create_category(
    kb_id: str,
    body: CategoryCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """创建文档类别"""
    from backend.services.knowledge_management.category_svc import category_svc
    cat = category_svc.create(db, kb_id, body.model_dump())
    return success_response(data=_serialize_category(cat))


@router.get("/bases/{kb_id}/categories")
def list_categories(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """文档类别列表"""
    from backend.services.knowledge_management.category_svc import category_svc
    items = category_svc.list(db, kb_id)
    return success_response(data=[_serialize_category(c) for c in items])


@router.put("/categories/{cat_id}")
def update_category(
    cat_id: str,
    body: CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """更新文档类别（预置类别不允许修改，应使用预设类别管理接口）"""
    try:
        from backend.core.knowledge_management.models import DocumentCategory
        existing = db.get(DocumentCategory, cat_id)
        if existing and existing.preset_category_id:
            return error_response(
                msg="预置类别不允许直接修改，请在「管理文档类别」中编辑预设类别",
                code=403, status_code=403
            )
        from backend.services.knowledge_management.category_svc import category_svc
        cat = category_svc.update(db, cat_id, body.model_dump(exclude_none=True))
        return success_response(data=_serialize_category(cat))
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.delete("/categories/{cat_id}")
def delete_category(
    cat_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """删除文档类别（预置类别不允许删除，应使用预设类别管理接口）"""
    try:
        from backend.core.knowledge_management.models import DocumentCategory
        existing = db.get(DocumentCategory, cat_id)
        if existing and existing.preset_category_id:
            return error_response(
                msg="预置类别不允许直接删除，请在「管理文档类别」中停用预设类别",
                code=403, status_code=403
            )
        from backend.services.knowledge_management.category_svc import category_svc
        category_svc.delete(db, cat_id)
        return success_response(msg="文档类别已删除")
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except ValidationError as e:
        return error_response(msg=str(e), code=400, status_code=400)


# ============================================================
#  收集对象
# ============================================================

@router.post("/bases/{kb_id}/targets")
def create_target(
    kb_id: str,
    body: TargetCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """创建收集对象"""
    from backend.services.knowledge_management.target_svc import target_svc
    target = target_svc.create(db, kb_id, body.model_dump(exclude_none=True))
    return success_response(data=_serialize_target(target))


@router.get("/bases/{kb_id}/targets")
def list_targets(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """收集对象列表"""
    from backend.services.knowledge_management.target_svc import target_svc
    items = target_svc.list(db, kb_id)
    return success_response(data=[_serialize_target(t) for t in items])


@router.put("/targets/{target_id}")
def update_target(
    target_id: str,
    body: TargetUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """更新收集对象"""
    try:
        from backend.services.knowledge_management.target_svc import target_svc
        target = target_svc.update(db, target_id, body.model_dump(exclude_none=True))
        return success_response(data=_serialize_target(target))
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.delete("/targets/{target_id}")
def delete_target(
    target_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """删除收集对象"""
    try:
        from backend.services.knowledge_management.target_svc import target_svc
        target_svc.delete(db, target_id)
        return success_response(msg="收集对象已删除")
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except ValidationError as e:
        return error_response(msg=str(e), code=400, status_code=400)


# ============================================================
#  收集计划
# ============================================================

@router.post("/plans")
def create_plan(
    body: PlanCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """创建收集计划"""
    try:
        from backend.services.knowledge_management.plan_svc import plan_svc
        plan = plan_svc.create(db, body.model_dump())
        return success_response(data=_serialize_plan_detail(plan))
    except ValidationError as e:
        return error_response(msg=str(e), code=400, status_code=400)


@router.get("/bases/{kb_id}/plans")
def list_plans(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """收集计划列表（含收集项 + 文档版本信息）"""
    from backend.services.knowledge_management.plan_svc import plan_svc
    from backend.core.knowledge_management.models import PlanItem, Document
    from sqlalchemy.orm import joinedload
    # 用 eager load 一次性加载 documents.versions
    plans = db.query(CollectionPlan).options(
        joinedload(CollectionPlan.plan_items).joinedload(PlanItem.documents).joinedload(Document.versions)
    ).filter(CollectionPlan.knowledge_base_id == kb_id).all()
    result = []
    for p in plans:
        data = _serialize_plan(p)
        # 兜底：若 overall_stats 为空（自动创建的计划），根据 plan_items 实时计算
        if not p.overall_stats and p.plan_items:
            item_count = len(p.plan_items)
            data["overall_stats"] = {
                "completed": 0,
                "improving": 0,
                "missing": item_count,
                "overdue": 0,
            }
        # 计算已上传文档数（聚合所有收集项下的 documents 数量）
        uploaded_doc_count = 0
        for item in (p.plan_items or []):
            if item.documents:
                uploaded_doc_count += len(item.documents)
        data["uploaded_doc_count"] = uploaded_doc_count
        data["plan_items"] = []
        for item in (p.plan_items or []):
            item_data = _serialize_plan_item(item)
            # 关键：每个 item 附带 documents（含 versions），以便合规性KB能拿到 valid_until 等字段
            item_data["documents"] = [_serialize_document(doc) for doc in (item.documents or [])]
            data["plan_items"].append(item_data)
        result.append(data)
    return success_response(data=result)


@router.get("/plans/{plan_id}")
def get_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """收集计划详情（含收集项及文档）"""
    try:
        from backend.services.knowledge_management.plan_svc import plan_svc
        plan = plan_svc.get(db, plan_id)
        return success_response(data=_serialize_plan_detail(plan))
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.put("/plans/{plan_id}")
def update_plan(
    plan_id: str,
    body: PlanUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """更新收集计划"""
    try:
        from backend.services.knowledge_management.plan_svc import plan_svc
        plan = plan_svc.update(db, plan_id, body.model_dump(exclude_none=True))
        return success_response(data=_serialize_plan(plan))
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.delete("/plans/{plan_id}")
def delete_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """删除收集计划"""
    try:
        from backend.services.knowledge_management.plan_svc import plan_svc
        plan_svc.delete(db, plan_id)
        return success_response(msg="收集计划已删除")
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except ValidationError as e:
        return error_response(msg=str(e), code=400, status_code=400)


@router.post("/plan-items")
def create_plan_item(
    body: PlanItemCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """新增单个收集项"""
    try:
        from backend.services.knowledge_management.plan_svc import plan_svc
        item = plan_svc.create_plan_item(db, body.model_dump())
        return success_response(data=_serialize_plan_item(item), msg="收集项已创建")
    except ValidationError as e:
        return error_response(msg=str(e), code=400, status_code=400)
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.put("/plan-items/{item_id}")
def update_plan_item(
    item_id: str,
    body: PlanItemUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """更新收集项"""
    try:
        from backend.services.knowledge_management.plan_svc import plan_svc
        item = plan_svc.update_plan_item(db, item_id, body.model_dump(exclude_none=True))
        return success_response(data=_serialize_plan_item(item))
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.delete("/plan-items/{item_id}")
def delete_plan_item(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """删除收集项"""
    try:
        from backend.services.knowledge_management.plan_svc import plan_svc
        plan_svc.delete_plan_item(db, item_id)
        return success_response(msg="收集项已删除")
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


# ============================================================
#  文档操作
# ============================================================

@router.post("/plan-items/{item_id}/upload")
async def upload_files(
    item_id: str,
    files: list[UploadFile] = File(..., description="上传文件列表"),
    document_id: str = Form(None, description="可选：已有文档 ID（更新场景，新版本加到已有文档下）"),
    force_ocr: bool = Form(False, description="手动开启 OCR（用于扫描件）"),
    file_type: str = Form(None, description="文件类型：general/table/image/manual/plc"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """多文件上传到收集项。提供 document_id 时为更新已有文档（创建新版本）。"""
    try:
        from backend.services.knowledge_management.document_svc import document_svc
        docs = document_svc.upload_files(db, item_id, files, uploaded_by=current_user, document_id=document_id, force_ocr=force_ocr, file_type=file_type)
        return success_response(
            data=[_serialize_document(doc) for doc in docs],
            msg=f"成功上传 {len(docs)} 个文件",
        )
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except Exception as e:
        logger.exception("文件上传失败")
        return error_response(msg=f"文件上传失败: {e}", code=500)


@router.get("/versions/{version_id}/progress")
def get_version_progress(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取版本后台任务进度"""
    try:
        from backend.services.knowledge_management.document_svc import document_svc
        progress = document_svc.get_version_progress(db, version_id)
        return success_response(data=progress)
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.put("/documents/{version_id}/filetype")
def set_file_type(
    version_id: str,
    body: FileTypeUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """更新文件类型"""
    try:
        from backend.services.knowledge_management.document_svc import document_svc
        version = document_svc.set_file_type(db, version_id, body.file_type)
        return success_response(data=_serialize_version(version))
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except ValidationError as e:
        return error_response(msg=str(e), code=400, status_code=400)


@router.post("/versions/{version_id}/ai-review")
def trigger_ai_review(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """触发 AI 审核"""
    try:
        from backend.services.knowledge_management.review_svc import review_svc
        review_svc.trigger_ai_review(db, version_id)
        return success_response(msg="AI 审核任务已触发")
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except ValidationError as e:
        return error_response(msg=str(e), code=400, status_code=400)


@router.post("/versions/{version_id}/approval")
def approve_or_reject(
    version_id: str,
    body: ApprovalRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """人工审批（通过/驳回）"""
    try:
        from backend.services.knowledge_management.review_svc import review_svc
        if body.action == "approve":
            version = review_svc.approve(db, version_id, username=current_user)
            return success_response(data=_serialize_version(version), msg="审批通过")
        elif body.action == "reject":
            if not body.reason:
                return error_response(msg="驳回时必须填写原因", code=400, status_code=400)
            version = review_svc.reject(db, version_id, reason=body.reason)
            return success_response(data=_serialize_version(version), msg="已驳回")
        else:
            return error_response(msg="action 必须是 approve 或 reject", code=400, status_code=400)
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except ValidationError as e:
        return error_response(msg=str(e), code=400, status_code=400)


@router.post("/versions/{version_id}/publish")
def publish_version(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """发布文档到 RAGFlow"""
    try:
        from backend.services.knowledge_management.ragflow_sync_svc import ragflow_sync_svc
        ragflow_sync_svc.publish_to_ragflow(db, version_id)
        return success_response(msg="文档已发布到 RAGFlow")
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except (ValidationError, RAGFlowError) as e:
        return error_response(msg=str(e), code=400, status_code=400)


@router.get("/versions/{version_id}/parse-status")
def get_parse_status(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """查询 RAGFlow 文档解析状态（实时从 RAGFlow 拉取并更新本地记录）。

    返回字段:
    - parse_status: unstart / running / done / fail / cancel
    - progress: 解析进度 0.0 ~ 1.0
    - progress_msg: 解析过程日志
    - process_begin_at / process_duration: 解析时间信息
    - chunk_count / token_count: 分块/Token 统计
    """
    try:
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        # 未发布到 RAGFlow
        if not version.publish_status or version.publish_status != "published":
            return success_response(data={
                "parse_status": None,
                "message": "文档尚未发布到 RAGFlow",
            })

        # 获取 RAGFlow 映射
        rag_map = version.rag_mapping
        if rag_map is None:
            return success_response(data={
                "parse_status": version.parse_status,
                "message": "RAGFlow 映射不存在",
            })

        # 从 RAGFlow 实时查询文档状态
        from backend.clients.knowledge_management.ragflow_client import KnowledgeRAGFlowClient
        ragflow = KnowledgeRAGFlowClient()
        try:
            doc_info = ragflow.get_document_info(
                dataset_id=rag_map.rag_dataset_id,
                doc_id=rag_map.rag_document_id,
            )
        except RAGFlowError:
            # RAGFlow 不可达时返回本地记录的状态
            return success_response(data={
                "parse_status": version.parse_status,
                "progress": None,
                "message": "无法连接 RAGFlow，显示本地缓存状态",
            })

        # 映射 RAGFlow 状态到本地状态
        rag_run = doc_info.get("run", "UNSTART")
        status_map = {
            "UNSTART": "unstart",
            "RUNNING": "running",
            "CANCEL": "cancel",
            "DONE": "done",
            "FAIL": "fail",
        }
        local_status = status_map.get(rag_run, "unstart")

        # 状态变化时更新数据库
        if local_status != version.parse_status:
            version.parse_status = local_status
            db.commit()

        return success_response(data={
            "parse_status": local_status,
            "progress": doc_info.get("progress"),
            "progress_msg": doc_info.get("progress_msg"),
            "process_begin_at": doc_info.get("process_begin_at"),
            "process_duration": doc_info.get("process_duration"),
            "chunk_count": doc_info.get("chunk_count"),
            "token_count": doc_info.get("token_count"),
            "run": rag_run,  # RAGFlow 原生状态值，方便调试
        })
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.post("/versions/{version_id}/reparse")
def reparse_document(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """重新触发 RAGFlow 文档解析（用于解析失败后重试）。

    仅允许在 parse_status 为 fail/cancel/unstart 时触发。
    """
    try:
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        # 校验状态
        if version.parse_status in (None, "running", "done"):
            status_text = {"running": "解析中", "done": "已解析完成"}.get(
                version.parse_status or "", version.parse_status
            )
            return error_response(
                msg=f"当前解析状态为 '{status_text}'，不允许重新解析",
                code=400,
                status_code=400,
            )

        # 获取 RAGFlow 映射
        rag_map = version.rag_mapping
        if rag_map is None:
            return error_response(
                msg="RAGFlow 映射不存在，请先发布文档",
                code=400,
                status_code=400,
            )

        # 触发 RAGFlow 重新解析
        from backend.clients.knowledge_management.ragflow_client import KnowledgeRAGFlowClient
        ragflow = KnowledgeRAGFlowClient()
        ragflow.run_parse(
            dataset_id=rag_map.rag_dataset_id,
            doc_ids=[rag_map.rag_document_id],
        )

        # 更新本地状态
        version.parse_status = "running"
        db.commit()

        logger.info(
            "已触发 RAGFlow 文档重新解析: version_id=%s, rag_doc_id=%s",
            version_id, rag_map.rag_document_id,
        )
        return success_response(msg="已触发重新解析")
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except RAGFlowError as e:
        return error_response(msg=f"RAGFlow 解析触发失败: {e}", code=500)


@router.post("/versions/{version_id}/stop-parse")
def stop_parse_document(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """停止 RAGFlow 文档解析（仅 parse_status=running 时可调用）。"""
    try:
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        if version.parse_status != "running":
            return error_response(
                msg=f"当前解析状态为 '{version.parse_status}'，无需停止",
                code=400,
                status_code=400,
            )

        rag_map = version.rag_mapping
        if rag_map is None:
            return error_response(msg="RAGFlow 映射不存在", code=400, status_code=400)

        from backend.clients.knowledge_management.ragflow_client import KnowledgeRAGFlowClient
        ragflow = KnowledgeRAGFlowClient()
        ragflow.stop_parse(
            dataset_id=rag_map.rag_dataset_id,
            doc_ids=[rag_map.rag_document_id],
        )

        version.parse_status = "cancel"
        db.commit()

        logger.info("已停止 RAGFlow 文档解析: version_id=%s", version_id)
        return success_response(msg="已停止解析")
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except RAGFlowError as e:
        return error_response(msg=f"RAGFlow 停止解析失败: {e}", code=500)


@router.get("/documents/{document_id}/versions")
def list_versions(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取文档的所有版本"""
    try:
        from backend.services.knowledge_management.document_svc import document_svc
        versions = document_svc.get_versions(db, document_id)
        return success_response(data=[_serialize_version(v) for v in versions])
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.delete("/versions/{version_id}")
def delete_version(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """删除单个文档版本"""
    try:
        from backend.services.knowledge_management.document_svc import document_svc
        # 删除前获取 plan_item_id 用于后续评估
        v = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
        plan_item_id = None
        if v and v.document:
            plan_item_id = v.document.plan_item_id
        document_svc.delete_version(db, version_id)
        # 触发收集项重新评估
        if plan_item_id:
            _trigger_item_evaluation(plan_item_id)
        return success_response(msg="版本已删除")
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except ValidationError as e:
        return error_response(msg=str(e), code=400, status_code=400)


@router.get("/versions/{version_id}/preview")
def get_version_preview(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取版本预览 URL（同源代理）。

    MinIO 预签名 URL 的 host 是容器内部名（minio:9000），浏览器解析不了；
    改为返回同源流式代理地址，token 模式与 raw-file 一致。
    同时返回 convert_status，便于前端区分"转换中"/"转换失败"/"已完成"三种状态。
    """
    try:
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        # 转换中的文件：返回友好提示，前端可据此展示"转换中"而非报错
        if version.convert_status == "processing":
            return success_response(data={
                "preview_url": None,
                "convert_status": "processing",
                "msg": "文件正在转换中，请稍后刷新重试",
            })
        if version.convert_status == "failed":
            return success_response(data={
                "preview_url": None,
                "convert_status": "failed",
                "msg": "文件转换失败，请联系管理员",
            })

        # pdf_preview_path 为空时回退到 storage_path（兼容旧数据）
        preview_path = version.pdf_preview_path or version.storage_path
        if not preview_path:
            return error_response(msg="该版本暂无预览内容", code=404, status_code=404)

        import hashlib
        token = hashlib.md5(f"knb_preview_{version_id}".encode()).hexdigest()[:12]
        return success_response(data={
            "preview_url": f"/api/knowledge-management/versions/{version_id}/preview-file?token={token}",
            "convert_status": "done" if version.pdf_preview_path else None,
        })
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.get("/versions/{version_id}/preview-file")
def get_version_preview_file(
    version_id: str,
    token: str = Query(..., description="临时访问令牌"),
    db: Session = Depends(get_db),
):
    """流式返回版本预览内容（同源，供 pdf.js/iframe fetch；token 验证，不依赖 Bearer）。
    根据 pdf_preview_path 的扩展名自动识别 MIME 类型（PDF/HTML/图片等）。"""
    import hashlib
    from fastapi.responses import StreamingResponse

    expected = hashlib.md5(f"knb_preview_{version_id}".encode()).hexdigest()[:12]
    if token != expected:
        return error_response(msg="无效的访问令牌", code=403, status_code=403)

    import tempfile, os, shutil
    tmp_dir = None
    try:
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")
        if not version.pdf_preview_path and not version.storage_path:
            return error_response(msg="该版本暂无预览内容", code=404, status_code=404)

        from backend.clients.knowledge_management.minio_client import minio_client

        # pdf_preview_path 为空时回退到原始文件路径（兼容旧数据）
        preview_path = version.pdf_preview_path or version.storage_path
        preview_lower = preview_path.lower()
        if preview_lower.endswith(".html"):
            media_type = "text/html"
            ext = ".html"
        elif preview_lower.endswith(".pdf"):
            media_type = "application/pdf"
            ext = ".pdf"
        elif any(preview_lower.endswith(e) for e in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif")):
            from mimetypes import guess_type
            media_type, _ = guess_type(preview_lower)
            if not media_type:
                media_type = "application/octet-stream"
            ext = os.path.splitext(preview_lower)[1]
        else:
            media_type = "application/octet-stream"
            ext = os.path.splitext(preview_lower)[1] or ".bin"

        tmp_dir = tempfile.mkdtemp(prefix="knb_preview_")
        local_path = os.path.join(tmp_dir, f"preview{ext}")
        minio_client.download_file(preview_path, local_path)

        from urllib.parse import quote

        raw_filename = version.original_filename or f"preview{ext}"
        # HTTP 头仅支持 ASCII/Latin-1，中文等非 ASCII 字符需用 RFC 5987 编码
        try:
            raw_filename.encode("latin-1")
            content_disposition = f"inline; filename=\"{raw_filename}\""
        except UnicodeEncodeError:
            safe_name = raw_filename.encode("utf-8", errors="replace").decode("utf-8")
            encoded = quote(safe_name, safe="")
            content_disposition = f"inline; filename*=UTF-8''{encoded}"

        file_obj = open(local_path, "rb")
        return StreamingResponse(
            file_obj,
            media_type=media_type,
            headers={
                "Content-Disposition": content_disposition,
            },
        )
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    finally:
        if tmp_dir:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


@router.get("/versions/{version_id}/download")
def get_version_download(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取版本原文件的预签名下载 URL 和 raw_file_url"""
    try:
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        import hashlib

        # 预签名 URL 浏览器不可达（host 为容器内部名），download_url 同样改走 raw-file 同源代理
        raw_token = hashlib.md5(f"knb_raw_{version_id}".encode()).hexdigest()[:12]
        raw_url = f"/api/knowledge-management/versions/{version_id}/raw-file?token={raw_token}"
        return success_response(data={
            "download_url": raw_url,
            "raw_file_url": raw_url,
            "filename": version.original_filename,
        })
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.get("/versions/{version_id}/raw-file")
def get_version_raw_file(
    version_id: str,
    token: str = Query(..., description="临时访问令牌"),
    db: Session = Depends(get_db),
):
    """获取版本原文件内容（供 OnlyOffice 等外部服务访问）。

    使用临时 token 验证，不依赖 Bearer Token。
    """
    import hashlib
    from fastapi.responses import StreamingResponse

    expected = hashlib.md5(f"knb_raw_{version_id}".encode()).hexdigest()[:12]
    if token != expected:
        return error_response(msg="无效的访问令牌", code=403, status_code=403)

    try:
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        from backend.clients.knowledge_management.minio_client import minio_client
        import tempfile, os
        tmp_dir = tempfile.mkdtemp(prefix="knb_raw_")
        local_path = os.path.join(tmp_dir, version.original_filename or "file")
        minio_client.download_file(version.storage_path, local_path)

        file_obj = open(local_path, "rb")
        return StreamingResponse(
            file_obj,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"inline; filename={version.original_filename}",
            },
        )
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


class DocumentUpdate(BaseModel):
    display_name: Optional[str] = Field(None, description="文档显示名称")


@router.put("/documents/{document_id}")
def update_document(
    document_id: str,
    body: DocumentUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """更新文档信息（如显示名称）。已发布文档仅允许通过「更新」上传新版本时修改。"""
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            raise NotFoundError(f"文档不存在: {document_id}")
        # 已发布文档不允许直接修改名称（需走更新流程）
        current = next((v for v in doc.versions if v.is_current), None)
        if current and current.publish_status == "published":
            return error_response(msg="已发布文档不允许直接修改，请通过「更新」上传新版本", code=400, status_code=400)
        if body.display_name is not None:
            doc.display_name = body.display_name
        db.commit()
        return success_response(data=_serialize_document(doc))
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """删除文档"""
    try:
        from backend.services.knowledge_management.document_svc import document_svc
        # 删除前获取 plan_item_id 用于后续评估
        doc = db.query(Document).filter(Document.id == document_id).first()
        plan_item_id = doc.plan_item_id if doc else None
        document_svc.delete_document(db, document_id)
        # 触发收集项重新评估
        if plan_item_id:
            _trigger_item_evaluation(plan_item_id)
        return success_response(msg="文档已删除")
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


# ============================================================
#  评估
# ============================================================

@router.get("/plans/{plan_id}/progress")
def get_plan_progress(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取计划进度"""
    try:
        plan = db.get(CollectionPlan, plan_id)
        if plan is None:
            raise NotFoundError(f"收集计划不存在: {plan_id}")
        return success_response(data={
            "overall_progress": plan.overall_progress,
            "overall_score": plan.overall_score,
            "overall_analysis": plan.overall_analysis,
            "overall_stats": plan.overall_stats,
            "evaluated_at": _dt(plan.evaluated_at),
        })
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.post("/plan-items/{item_id}/evaluate")
def trigger_plan_item_evaluation(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """触发收集项评估（同步执行并返回更新后的结果）"""
    try:
        from backend.services.knowledge_management.evaluation_svc import evaluation_svc
        evaluation_svc.evaluate_plan_item(db, item_id)
        # 重新查询获取最新结果
        item = db.get(PlanItem, item_id)
        if item is None:
            raise NotFoundError(f"收集项不存在: {item_id}")
        return success_response(data={
            "overall_completion": item.overall_completion,
            "overall_score": item.overall_score,
            "overall_status": item.overall_status,
            "evaluation_detail": item.evaluation_detail,
            "evaluated_at": _dt(item.evaluated_at),
        })
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.get("/plan-items/{item_id}/evaluation")
def get_plan_item_evaluation(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取收集项评估结果"""
    try:
        item = db.get(PlanItem, item_id)
        if item is None:
            raise NotFoundError(f"收集项不存在: {item_id}")
        return success_response(data={
            "overall_completion": item.overall_completion,
            "overall_score": item.overall_score,
            "overall_status": item.overall_status,
            "evaluation_detail": item.evaluation_detail,
            "evaluated_at": _dt(item.evaluated_at),
        })
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


# ============================================================
#  RAGFlow 文档查看
# ============================================================

@router.get("/rag-documents/{rag_doc_id}/chunks")
def get_rag_document_chunks(
    rag_doc_id: str,
    keywords: str = Query("", description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(30, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取 RAGFlow 文档的切片列表"""
    try:
        rag_map = (
            db.query(RAGDocumentMap)
            .filter(RAGDocumentMap.rag_document_id == rag_doc_id)
            .first()
        )
        if rag_map is None:
            raise NotFoundError(f"RAGFlow 文档映射不存在: {rag_doc_id}")

        # 获取 dataset_id
        version = db.get(DocumentVersion, rag_map.version_id)
        if version is None:
            raise NotFoundError("关联的文档版本不存在")

        doc = version.document
        plan_item = doc.plan_item
        kb = plan_item.plan.knowledge_base

        if not kb.rag_dataset_id:
            raise ValidationError("知识库未关联 RAGFlow 数据集")

        from backend.clients.knowledge_management.ragflow_client import KnowledgeRAGFlowClient
        ragflow = KnowledgeRAGFlowClient()
        result = ragflow.get_document_chunks(
            dataset_id=kb.rag_dataset_id,
            doc_id=rag_doc_id,
            keywords=keywords,
            page=page,
            page_size=page_size,
        )
        return success_response(data=result)
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)
    except (ValidationError, RAGFlowError) as e:
        return error_response(msg=str(e), code=400, status_code=400)


@router.get("/rag-documents/{rag_doc_id}/preview")
def get_rag_document_preview(
    rag_doc_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取已发布文档的 PDF 预览 URL（通过 RAGDocumentMap → MinIO）"""
    try:
        rag_map = (
            db.query(RAGDocumentMap)
            .filter(RAGDocumentMap.rag_document_id == rag_doc_id)
            .first()
        )
        if rag_map is None:
            raise NotFoundError(f"RAGFlow 文档映射不存在: {rag_doc_id}")

        version = db.get(DocumentVersion, rag_map.version_id)
        if version is None:
            raise NotFoundError("关联的文档版本不存在")

        if not version.pdf_preview_path:
            return error_response(msg="该版本暂无 PDF 预览", code=404, status_code=404)

        # 同上：预签名 URL 浏览器不可达，复用 preview-file 同源代理
        import hashlib
        token = hashlib.md5(f"knb_preview_{version.id}".encode()).hexdigest()[:12]
        return success_response(data={
            "preview_url": f"/api/knowledge-management/versions/{version.id}/preview-file?token={token}"
        })
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


@router.get("/rag-documents/{rag_doc_id}/download")
def get_rag_document_download(
    rag_doc_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取已发布文档的原文件下载 URL（通过 RAGDocumentMap → MinIO）"""
    try:
        rag_map = (
            db.query(RAGDocumentMap)
            .filter(RAGDocumentMap.rag_document_id == rag_doc_id)
            .first()
        )
        if rag_map is None:
            raise NotFoundError(f"RAGFlow 文档映射不存在: {rag_doc_id}")

        version = db.get(DocumentVersion, rag_map.version_id)
        if version is None:
            raise NotFoundError("关联的文档版本不存在")

        # 同上：预签名 URL 浏览器不可达，复用 raw-file 同源代理
        import hashlib
        raw_token = hashlib.md5(f"knb_raw_{version.id}".encode()).hexdigest()[:12]
        return success_response(data={
            "download_url": f"/api/knowledge-management/versions/{version.id}/raw-file?token={raw_token}",
            "filename": version.original_filename,
        })
    except NotFoundError as e:
        return error_response(msg=str(e), code=404, status_code=404)


# ========== 设备类型同步 ==========

@router.post("/sync/device-types")
def sync_device_types(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    """手动触发全量设备类型同步"""
    result = device_sync_svc.sync_device_types(db)
    oplog_svc.log(db, username=current_user or "unknown",
                  operation="sync_device_types", target_type="kb",
                  remark=f"新增{result['created']}个KB，停用{result['disabled']}个KB")
    return {"success": True, **result}


@router.get("/sync/device-types/status")
def get_sync_status(db: Session = Depends(get_db)):
    """查询上次同步状态"""
    last = db.query(KnowledgeBase).filter(KnowledgeBase.sync_type == 'auto') \
        .order_by(KnowledgeBase.synced_at.desc()).first()
    kb_count = db.query(KnowledgeBase).filter(KnowledgeBase.status == 'active').count()
    return {
        "last_sync": last.synced_at.isoformat() if last and last.synced_at else None,
        "active_kb_count": kb_count,
    }


@router.get("/debug/preset-status")
def debug_preset_status(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    """诊断预设类别和合规性KB的完整状态"""
    from backend.core.knowledge_management.models import (
        PresetCategory, DocumentCategory, CollectionPlan, CollectionTarget, PlanItem,
    )
    from backend.core.knowledge_management.config import settings

    base_name = settings.knb_base_name
    # 预设类别统计
    preset_total = db.query(PresetCategory).count()
    preset_active = db.query(PresetCategory).filter(PresetCategory.is_active == True).count()
    by_type = {}
    for pt in ['device_doc', 'sop_doc', 'compliance']:
        by_type[pt] = db.query(PresetCategory).filter(
            PresetCategory.category_type == pt, PresetCategory.is_active == True
        ).count()

    # 合规性KB
    comp_kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.kb_type == 'compliance',
        KnowledgeBase.tags['base'].astext == base_name,
    ).first()
    comp_kb_info = None
    if comp_kb:
        cat_count = db.query(DocumentCategory).filter(DocumentCategory.knowledge_base_id == comp_kb.id).count()
        target_count = db.query(CollectionTarget).filter(CollectionTarget.knowledge_base_id == comp_kb.id).count()
        plan = db.query(CollectionPlan).filter(
            CollectionPlan.knowledge_base_id == comp_kb.id, CollectionPlan.plan_type == 'compliance'
        ).first()
        item_count = 0
        if plan:
            item_count = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).count()
        comp_kb_info = {
            "id": comp_kb.id, "name": comp_kb.name, "rag_dataset_id": comp_kb.rag_dataset_id,
            "category_count": cat_count, "target_count": target_count,
            "plan_id": plan.id if plan else None,
            "plan_item_count": item_count,
        }

    # 设备KB统计 — 同时包含新旧设备类型KB
    device_kbs = db.query(KnowledgeBase).filter(
        KnowledgeBase.kb_type.in_(['device', 'device_doc', 'sop_doc'])
    ).all()
    device_kb_summary = []
    for kb in device_kbs:
        cat_count = db.query(DocumentCategory).filter(DocumentCategory.knowledge_base_id == kb.id).count()
        device_kb_summary.append({"id": kb.id, "name": kb.name, "device_type": kb.device_type,
                                   "category_count": cat_count, "rag_dataset_id": kb.rag_dataset_id})

    return {
        "base_name": base_name,
        "preset": {
            "total": preset_total, "active": preset_active, "by_type": by_type,
        },
        "compliance_kb": comp_kb_info,
        "device_kbs_count": len(device_kbs),
        "device_kbs_summary": device_kb_summary[:5],
    }


@router.post("/debug/fix-compliance")
def debug_fix_compliance(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    """诊断后修复：补全合规性KB结构"""
    from backend.core.knowledge_management.database import _ensure_compliance_kb
    try:
        _ensure_compliance_kb()
        return {"success": True, "message": "合规性KB结构已修复"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/sync/device-type")
def sync_single_device_type(data: dict, request: Request, db: Session = Depends(get_db)):
    """外部系统触发单个设备类型同步（API Key 认证）"""
    api_key = request.headers.get("X-API-Key", "")
    if api_key != settings.knb_sync_api_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    device_type = data.get("device_type")
    workshop = data.get("workshop")
    if not device_type or not workshop:
        raise HTTPException(status_code=400, detail="device_type and workshop are required")
    result = device_sync_svc.create_single_kb(db, device_type, workshop)
    if result is None:
        raise HTTPException(status_code=409, detail={"error": "device_type_exists", "message": f"设备类型「{device_type}」已存在"})
    oplog_svc.log(db, username="外部系统", operation="sync_device_types",
                  target_type="kb", remark=f"外部触发创建: {device_type}")
    return {"success": True, "kb_ids": result, "kb_count": len(result)}


# ========== 预设类别管理 ==========

@router.get("/preset-categories")
def get_preset_categories(flat: bool = False, db: Session = Depends(get_db),
                           current_user: str = Depends(get_current_user)):
    """获取预设类别。flat=true 返回平铺列表，否则返回树结构。"""
    items = db.query(PresetCategory).filter(PresetCategory.is_active == True) \
        .order_by(PresetCategory.sort_order).all()
    if flat:
        return [{
            "id": item.id, "name": item.name,
            "category_type": item.category_type,
            "level": item.level, "is_leaf": item.is_leaf,
            "requirement_desc": item.requirement_desc,
            "sort_order": item.sort_order,
            "parent_id": item.parent_id,
            "parent_name": None,  # 前端自行关联
            "version": item.version,
            "is_active": item.is_active,
        } for item in items]
    # 默认 tree 模式：构建前端期望的结构
    return preset_category_svc.get_tree(db)


@router.post("/admin/preset-categories")
def create_preset_category(data: dict, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    preset_category_svc.create(db, data)
    return {"success": True}


@router.put("/admin/preset-categories/{preset_id}")
def update_preset_category(preset_id: str, data: dict, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    preset_category_svc.update(db, preset_id, data)
    return {"success": True}


@router.delete("/admin/preset-categories/{preset_id}")
def delete_preset_category(preset_id: str, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    preset_category_svc.delete(db, preset_id)
    return {"success": True}


@router.post("/admin/preset-categories/sync")
def sync_preset_to_all_kb(data: dict, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    category_type = data.get("category_type")
    result = preset_category_svc.sync_to_all_kb(db, category_type)
    oplog_svc.log(db, username=current_user or "unknown",
                  operation="sync_preset_categories", target_type="preset_category",
                  remark=f"同步{result['added_categories']}个类别到{result['synced_kb_count']}个KB")
    return {"success": True, **result}


@router.post("/admin/preset-categories/reseed")
def reseed_preset_categories(force: bool = False, db: Session = Depends(get_db),
                             current_user: str = Depends(get_current_user)):
    """重新加载预设类别种子数据。
    force=True 时清空表重建（修复数据污染）。"""
    from backend.core.knowledge_management.preset_seed import seed_preset_categories
    result = seed_preset_categories(db, force=force)
    # 同步到所有知识库
    sync_results = {}
    for ct in ['device_doc', 'sop_doc', 'compliance']:
        sync_results[ct] = preset_category_svc.sync_to_all_kb(db, ct)
    return {"success": True, "force": force, "seed": result, "sync": sync_results}


# ========== 不适用标记 ==========

@router.put("/plan-items/{item_id}/not-applicable")
def mark_not_applicable(item_id: str, data: dict, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    item = db.query(PlanItem).filter(PlanItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Plan item not found")
    item.not_applicable = True
    item.not_applicable_by = current_user
    item.not_applicable_at = datetime.now(timezone.utc)
    item.not_applicable_reason = data.get("reason", "")
    db.commit()
    return {"success": True}


@router.delete("/plan-items/{item_id}/not-applicable")
def unmark_not_applicable(item_id: str, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    item = db.query(PlanItem).filter(PlanItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Plan item not found")
    item.not_applicable = False
    item.not_applicable_by = None
    item.not_applicable_at = None
    item.not_applicable_reason = None
    db.commit()
    return {"success": True}


# ========== 合规性审核 ==========

@router.put("/versions/{version_id}/compliance-dates")
def update_compliance_dates(version_id: str, data: dict, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    v = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    if data.get("valid_from"): v.valid_from = data["valid_from"]
    if data.get("valid_until"): v.valid_until = data["valid_until"]
    if "has_stamp" in data: v.has_stamp = data["has_stamp"]
    if "has_signature" in data: v.has_signature = data["has_signature"]
    db.commit()
    return success_response(msg="合规性日期已更新")


@router.post("/versions/{version_id}/retry-review")
def retry_ai_review(version_id: str, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    from services.knowledge_management.tasks.review_tasks import ai_review_task
    v = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    if v.status not in ['compliance_date_missing', 'ai_completed_manual_pending']:
        raise HTTPException(status_code=400, detail=f"Invalid status: {v.status}")
    v.status = 'ai_processing'
    db.commit()
    ai_review_task.delay(version_id)
    return success_response(data={"new_status": "ai_processing"}, msg="AI 审核已重新触发")


# ========== 看板 API ==========

@router.get("/dashboard/base")
def dashboard_base(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    base_name = settings.knb_base_name
    # 获取被禁用的 KB 类型
    from backend.services.knowledge_management.kb_type_state_svc import kb_type_state_svc
    disabled_types = kb_type_state_svc.get_disabled_types(db)

    # 类型禁用 → 该类型下所有 device/ compliance KB 都不参与统计
    all_kbs = db.query(KnowledgeBase).options(
        joinedload(KnowledgeBase.plans).joinedload(CollectionPlan.plan_items)
    ).filter(
        KnowledgeBase.status == 'active',
        KnowledgeBase.kb_type.in_(['device', 'compliance']),
    ).all()
    # 过滤：KB 类型被禁用 OR KB 自身 enabled=False → 排除
    kbs = [
        kb for kb in all_kbs
        if kb.enabled and _kb_type_enabled(kb.kb_type, disabled_types)
    ]
    workshops = set()
    device_types = set()
    # plan_type -> {score_sum, progress_sum, count, device_types set, doc_count, plan_count}
    plan_type_stats = {}
    for kb in kbs:
        if kb.tags:
            w = kb.tags.get("workshop", "")
            if w: workshops.add(w)
            d = kb.device_type
            if d: device_types.add(d)

        if kb.kb_type == 'compliance':
            # 合规性KB：整体统计
            total_items = 0
            completed_items = 0
            item_docs = 0
            for plan in kb.plans:
                for item in plan.plan_items:
                    if not item.not_applicable:
                        total_items += 1
                        if item.overall_status == 'completed':
                            completed_items += 1
                    if item.documents:
                        item_docs += len(item.documents)
            progress = round(completed_items / total_items * 100, 1) if total_items > 0 else 0
            key = 'compliance'
            if key not in plan_type_stats:
                plan_type_stats[key] = {"score_sum": 0, "progress_sum": 0.0, "count": 0,
                                        "device_types": set(), "doc_count": 0, "plan_count": 0}
            st = plan_type_stats[key]
            st["score_sum"] += kb.overall_score or 0
            st["progress_sum"] += progress
            st["count"] += 1
            st["doc_count"] += item_docs
            st["plan_count"] += len(kb.plans)
        else:
            # device KB：按 plan_type 分别统计
            for plan in kb.plans:
                pt = plan.plan_type or 'device_doc'
                if pt not in ('device_doc', 'sop_doc'):
                    continue
                total_items = 0
                completed_items = 0
                item_docs = 0
                for item in plan.plan_items:
                    if not item.not_applicable:
                        total_items += 1
                        if item.overall_status == 'completed':
                            completed_items += 1
                    if item.documents:
                        item_docs += len(item.documents)
                progress = round(completed_items / total_items * 100, 1) if total_items > 0 else 0
                if pt not in plan_type_stats:
                    plan_type_stats[pt] = {"score_sum": 0, "progress_sum": 0.0, "count": 0,
                                           "device_types": set(), "doc_count": 0, "plan_count": 0}
                st = plan_type_stats[pt]
                st["score_sum"] += plan.overall_score or 0
                st["progress_sum"] += progress
                st["count"] += 1
                st["doc_count"] += item_docs
                st["plan_count"] += 1
                if kb.device_type:
                    st["device_types"].add(kb.device_type)

    # 聚合 plan_type_stats
    plan_type_stats_agg = {}
    for ptype, st in plan_type_stats.items():
        n = st["count"]
        plan_type_stats_agg[ptype] = {
            "name": {"device_doc": "设备说明知识库", "sop_doc": "设备SOP知识库",
                     "compliance": "合规性知识库"}.get(ptype, ptype),
            "kb_type": ptype,
            "progress": round(st["progress_sum"] / n, 1) if n > 0 else 0,
            "score": round(st["score_sum"] / n, 1) if n > 0 else 0,
            "plan_count": st["plan_count"],
            "device_type_count": len(st["device_types"]),
            "doc_count": st["doc_count"],
        }

    # Base score: (compliance + avg(device_doc, sop_doc)) / 2
    compliance_score = plan_type_stats_agg.get('compliance', {}).get('score')
    device_scores = []
    if 'device_doc' in plan_type_stats_agg:
        device_scores.append(plan_type_stats_agg['device_doc']['score'])
    if 'sop_doc' in plan_type_stats_agg:
        device_scores.append(plan_type_stats_agg['sop_doc']['score'])
    device_avg = sum(device_scores) / len(device_scores) if device_scores else 0
    if compliance_score is not None and device_scores:
        base_score = round((compliance_score + device_avg) / 2, 1)
    elif compliance_score is not None:
        base_score = compliance_score
    elif device_scores:
        base_score = round(device_avg, 1)
    else:
        base_score = 0

    progresses = [s['progress'] for s in plan_type_stats_agg.values()
                  if isinstance(s.get('progress'), (int, float))]
    base_progress = round(sum(progresses) / len(progresses), 1) if progresses else 0

    # Total docs
    total_docs = sum(st.get("doc_count", 0) for st in plan_type_stats.values())

    # Workshop list (from device KBs only, not compliance)
    workshop_kbs = [kb for kb in kbs if kb.kb_type == 'device']
    workshop_list = []
    for ws_name in sorted(workshops):
        ws_dev_kbs = [kb for kb in workshop_kbs if kb.tags and kb.tags.get("workshop") == ws_name]
        ws_device_types = set(kb.device_type for kb in ws_dev_kbs if kb.device_type)
        # 设备类型详情（含progress和kb_id，供侧边栏使用）
        device_type_items = []
        for dt_name in sorted(ws_device_types):
            dt_kb = next((kb for kb in ws_dev_kbs if kb.device_type == dt_name), None)
            if dt_kb:
                # 计算该KB的设备说明+SOP平均进度
                dt_progress = dt_kb.overall_progress or 0
                device_type_items.append({
                    "name": dt_name,
                    "kb_id": dt_kb.id,
                    "progress": dt_progress,
                })
        workshop_list.append({
            "name": ws_name,
            "device_count": len(ws_device_types),
            "device_types": device_type_items,
        })

    # Custom KBs
    custom_kbs = db.query(KnowledgeBase).filter(
        KnowledgeBase.kb_type == 'custom_base',
        KnowledgeBase.status == 'active'
    ).all()
    custom_kbs_list = [{
        "id": kb.id, "name": kb.name,
        "overall_progress": kb.overall_progress or 0,
        "overall_score": kb.overall_score or 0,
        "doc_count": 0,
        "plan_count": len(kb.plans) if kb.plans else 0,
    } for kb in custom_kbs]

    last_sync_time = ""

    return {
        "base_name": base_name,
        "base_score": base_score,
        "base_progress": base_progress,
        "workshop_count": len(workshops),
        "device_type_count": len(device_types),
        "kb_types": plan_type_stats_agg,
        "kb_type_states": kb_type_state_svc.list_states(db),
        "total_docs": total_docs,
        "workshops": workshop_list,
        "custom_kbs": custom_kbs_list,
        "last_sync": last_sync_time,
    }


@router.get("/dashboard/knowledge-overview")
def dashboard_knowledge_overview(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """首页 AI 知识库健康度评估报告：4 维度诊断（进度/质量/合规/缺失）。"""
    svc = KnowledgeOverviewService()
    return success_response(data=svc.diagnose(db))


@router.get("/dashboard/knowledge-overview/summary")
def dashboard_knowledge_overview_summary(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """调用 LLM 生成 ≤400 字中文总结；失败返回降级文案。"""
    svc = KnowledgeOverviewService()
    diag = svc.diagnose(db)
    summary = svc.build_summary(diag)
    return success_response(data={"summary": summary})


@router.get("/dashboard/workshop")
def dashboard_workshop(kb_type: str = "device_doc", db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    """车间视图：按 plan_type（device_doc/sop_doc）统计各车间进度"""
    # 同时查新 device 类型和旧的 device_doc/sop_doc 类型KB，保证数据完整
    if kb_type == 'device_doc':
        kb_types = ['device', 'device_doc']
    elif kb_type == 'sop_doc':
        kb_types = ['device', 'sop_doc']
    else:
        kb_types = [kb_type]
    # 类型被禁用 → 直接返回空
    from backend.services.knowledge_management.kb_type_state_svc import kb_type_state_svc
    from backend.core.knowledge_management.database import SessionLocal
    _tmp = SessionLocal()
    try:
        disabled_types = kb_type_state_svc.get_disabled_types(_tmp)
    finally:
        _tmp.close()
    if kb_type in disabled_types:
        return {"kb_type": kb_type, "workshops": []}
    all_kbs = db.query(KnowledgeBase).options(
        joinedload(KnowledgeBase.plans).joinedload(CollectionPlan.plan_items)
    ).filter(
        KnowledgeBase.status == 'active',
        KnowledgeBase.kb_type.in_(kb_types),
    ).all()
    # 过滤 enabled=False 的 KB
    kbs = [kb for kb in all_kbs if kb.enabled]
    ws_data = {}
    for kb in kbs:
        ws_name = kb.tags.get("workshop", "") if kb.tags else ""
        if not ws_name:
            continue  # 跳过无车间的KB
        # 找到对应 plan_type 的收集计划
        matching_plan = None
        for plan in kb.plans:
            if plan.plan_type == kb_type:
                matching_plan = plan
                break
        if not matching_plan:
            continue

        # 计算该计划的进度
        total_items = 0
        completed_items = 0
        item_docs = 0
        for item in matching_plan.plan_items:
            if not item.not_applicable:
                total_items += 1
                if item.overall_status == 'completed':
                    completed_items += 1
            if item.documents:
                item_docs += len(item.documents)
        progress = round(completed_items / total_items * 100, 1) if total_items > 0 else 0
        score = matching_plan.overall_score or 0

        if ws_name not in ws_data:
            ws_data[ws_name] = {
                "name": ws_name,
                "kb_count": 0,  # 实际是设备类型数（去重后的 device_type）
                "total_progress": 0.0,
                "total_score": 0.0,
                "total_docs": 0,
                "_device_types": set(),  # 用于去重
            }
        # 按 device_type 去重（device + device_doc 是同一个设备类型）
        device_type_name = kb.device_type or kb.name
        if device_type_name in ws_data[ws_name]["_device_types"]:
            continue
        ws_data[ws_name]["_device_types"].add(device_type_name)
        ws_data[ws_name]["kb_count"] += 1
        ws_data[ws_name]["total_progress"] += progress
        ws_data[ws_name]["total_score"] += score
        ws_data[ws_name]["total_docs"] += item_docs

    result = []
    for name, data in ws_data.items():
        n = data["kb_count"]
        result.append({
            "name": name, "kb_count": n,
            "progress": round(data["total_progress"] / n, 1) if n > 0 else 0,
            "score": round(data["total_score"] / n, 1) if n > 0 else 0,
            "docs": data["total_docs"],
        })
    result.sort(key=lambda x: (x["progress"], x["name"]))
    return {"kb_type": kb_type, "workshops": result}


# ========== 操作日志 ==========

@router.get("/operation-logs")
def list_operation_logs(kb_id: str = None, operation: str = None, page: int = 1, page_size: int = 50,
                         db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    return oplog_svc.list(db, kb_id=kb_id, operation=operation, page=page, page_size=page_size)
