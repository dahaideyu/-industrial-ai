# cython: annotation_typing=False, infer_types=False, language_level=3
"""/api/kb-qa 路由。"""

import json
import logging
import mimetypes
import queue
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.knowledge_management.database import SessionLocal, get_db
from backend.core.knowledge_management.models import KnowledgeBase
from backend.routes.agentic_qa.dependencies import get_current_user
from backend.services.agentic_qa.models.user import User
from backend.services.agentic_qa.ragflow.client import ragflow_client
from backend.services.knowledge_qa.chat_assistant_mgr import ChatAssistantManager
from backend.services.knowledge_qa.kb_qa_service import KbQaService
from backend.services.knowledge_qa.kb_router import KbRouter
from backend.services.knowledge_qa.repository import KbQaRepository

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- Pydantic 模型 ----------

class ChatRequest(BaseModel):
    question: str
    session_id: str
    manual_kb_ids: Optional[List[str]] = None


class ChatResponse(BaseModel):
    answer: str
    references: Optional[dict] = None
    used_kb_ids: List[str]
    message_id: int
    session_id: str


class CreateSessionRequest(BaseModel):
    title: Optional[str] = "新会话"


class SessionOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    used_kb_ids: Optional[List[str]] = None
    rag_references: Optional[dict] = None
    created_at: str


class KbOut(BaseModel):
    id: str
    name: str
    kb_type: str
    rag_dataset_id: Optional[str] = None
    document_count: int = 0


# ---------- 内部依赖 ----------

class _KbRepoAdapter:
    """把 KnowledgeBase ORM 适配成 KbQaService 需要的 dict 接口。"""

    def list_accessible(self, db: Session, user_id: int) -> List[dict]:
        rows = db.query(KnowledgeBase).all()
        return [
            {
                "id": str(r.id),
                "name": r.name,
                "description": r.description or "",
                "rag_dataset_id": r.rag_dataset_id,
            }
            for r in rows
        ]


def _create_kbqa_service() -> KbQaService:
    """创建 KbQaService 实例（不含 LLM 注入）。"""
    repo = KbQaRepository()
    kb_repo = _KbRepoAdapter()
    router_obj = KbRouter()
    mgr = ChatAssistantManager(repo=repo, ragflow_client=ragflow_client)
    return KbQaService(
        repo=repo,
        kb_repo=kb_repo,
        kb_router=router_obj,
        chat_assistant_mgr=mgr,
        ragflow_client=ragflow_client,
    )


def get_kbqa_service(db: Session = Depends(get_db)) -> KbQaService:
    return _create_kbqa_service()


# ---------- 端点 ----------

@router.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """主对话端点。"""
    svc = get_kbqa_service(db)

    # 注入真实 LLM（chat_once_with_retry 支持单参调用，其他参数均有默认值）
    from backend.core.agentic_qa.llm import llm
    svc.set_llm_call(llm.chat_once_with_retry)

    result = svc.chat(
        db=db,
        user_id=current_user.id,
        session_id=req.session_id,
        question=req.question,
        manual_kb_ids=req.manual_kb_ids or [],
        user_name=getattr(current_user, 'username', None) or getattr(current_user, 'display_name', None),
    )
    return ChatResponse(**result)


@router.post("/chat/stream")
def chat_stream(
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """流式对话端点 (SSE)。

    事件格式：
      data: {"type":"chunk","content":"增量文本"}
      data: {"type":"done","answer":"...","references":{...},"message_id":123,...}
      data: {"type":"error","message":"错误描述"}
    """
    q: queue.Queue = queue.Queue()
    user_name = getattr(current_user, 'username', None) or getattr(current_user, 'display_name', None)

    def _run_in_thread() -> None:
        """在独立线程中执行对话逻辑，通过 Queue 将结果传回主线程。"""
        db = SessionLocal()
        try:
            svc = _create_kbqa_service()

            # 注入真实 LLM
            from backend.core.agentic_qa.llm import llm
            svc.set_llm_call(llm.chat_once_with_retry)

            def on_chunk(delta: str) -> None:
                q.put(("chunk", delta))

            result = svc.chat(
                db=db,
                user_id=current_user.id,
                session_id=req.session_id,
                question=req.question,
                manual_kb_ids=req.manual_kb_ids or [],
                user_name=user_name,
                on_chunk=on_chunk,
            )
            q.put(("done", result))
        except Exception as e:
            logger.exception(f"流式对话异常: {e}")
            q.put(("error", str(e)))
        finally:
            db.close()

    threading.Thread(target=_run_in_thread, daemon=True).start()

    def generate():
        while True:
            try:
                event_type, data = q.get(timeout=130)  # 略大于 RAGFlow 120s 超时
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'error', 'message': '请求超时'}, ensure_ascii=False)}\n\n"
                break

            if event_type == "chunk":
                yield f"data: {json.dumps({'type': 'chunk', 'content': data}, ensure_ascii=False)}\n\n"
            elif event_type == "done":
                # 构建 done 事件（只传递前端需要的字段）
                done_payload = {
                    "type": "done",
                    "answer": data.get("answer", ""),
                    "thinking": data.get("thinking", ""),
                    "references": data.get("references"),
                    "message_id": data.get("message_id"),
                    "used_kb_ids": data.get("used_kb_ids", []),
                    "session_id": data.get("session_id", ""),
                }
                yield f"data: {json.dumps(done_payload, ensure_ascii=False, default=str)}\n\n"
                break
            elif event_type == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': data}, ensure_ascii=False)}\n\n"
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions", response_model=SessionOut)
def create_session(
    req: CreateSessionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = KbQaRepository()
    s = repo.create_session(db, current_user.id, req.title or "新会话")
    return SessionOut(
        id=s.id,
        title=s.title,
        created_at=s.created_at.isoformat(),
        updated_at=s.updated_at.isoformat(),
    )


@router.get("/sessions", response_model=List[SessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = KbQaRepository()
    sessions = repo.list_sessions(db, current_user.id)
    return [
        SessionOut(
            id=s.id,
            title=s.title,
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
        )
        for s in sessions
    ]


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除会话及其所有消息。"""
    repo = KbQaRepository()
    success = repo.delete_session(db, session_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.get("/sessions/{session_id}/messages", response_model=List[MessageOut])
def list_messages(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = KbQaRepository()
    msgs = repo.get_recent_messages(db, session_id, limit=200)
    out = []
    for m in msgs:
        used_kb_ids = json.loads(m.used_kb_ids) if m.used_kb_ids else None
        rag_refs = json.loads(m.rag_references) if m.rag_references else None
        out.append(
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                used_kb_ids=used_kb_ids,
                rag_references=rag_refs,
                created_at=m.created_at.isoformat(),
            )
        )
    return out


@router.get("/kbs", response_model=List[KbOut])
def list_kbs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出所有可用的知识库。

    返回每个 KB 的实际文档数（document_count），供前端过滤无文档的 KB。
    链路：KB → DocumentCategory → PlanItem → Document → DocumentVersion
    """
    from sqlalchemy import func, select

    from backend.core.knowledge_management.models import (
        Document,
        DocumentCategory,
        DocumentVersion,
        PlanItem,
    )

    # 子查询：每个 KB 的已发布文档版本数
    doc_count_subq = (
        select(
            DocumentCategory.knowledge_base_id.label("kb_id"),
            func.count(DocumentVersion.id.distinct()).label("doc_count"),
        )
        .join(PlanItem, PlanItem.category_id == DocumentCategory.id)
        .join(Document, Document.plan_item_id == PlanItem.id)
        .join(
            DocumentVersion,
            (DocumentVersion.document_id == Document.id)
            & (DocumentVersion.is_current == True),
        )
        .group_by(DocumentCategory.knowledge_base_id)
        .subquery()
    )

    rows = (
        db.query(KnowledgeBase, doc_count_subq.c.doc_count)
        .outerjoin(doc_count_subq, doc_count_subq.c.kb_id == KnowledgeBase.id)
        .all()
    )

    return [
        KbOut(
            id=str(r.id),
            name=r.name,
            kb_type=r.kb_type or "custom",
            rag_dataset_id=r.rag_dataset_id,
            document_count=int(doc_count or 0),
        )
        for r, doc_count in rows
    ]


# ---------- RAGFlow 文档代理 ----------

@router.get("/ragflow/document-preview")
def document_preview(
    dataset_id: str,
    document_id: str,
):
    """代理下载 RAGFlow 文档内容（base64），供前端引用预览。

    不强制应用层认证：实际文档权限由 RAGFlow 控制，与 SQL QA 行为一致。
    """
    content, err = ragflow_client.download_document(dataset_id, document_id)
    if err:
        raise HTTPException(status_code=502, detail=err)
    import base64
    return {"content": base64.b64encode(content).decode("utf-8")}


@router.get("/ragflow/document-download")
def document_download(
    dataset_id: str,
    document_id: str,
    filename: Optional[str] = None,
) -> Response:
    """代理下载 RAGFlow 原始文档，保留文件格式和 MIME 类型。"""
    content, err = ragflow_client.download_document(dataset_id, document_id)
    if err:
        raise HTTPException(status_code=502, detail=err)

    safe_name = Path(filename or f"{document_id}.bin").name
    media_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    encoded_name = quote(safe_name)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@router.get("/ragflow/document-preview-pdf")
def document_preview_pdf(
    dataset_id: str,
    document_id: str,
    filename: Optional[str] = None,
) -> Response:
    """返回适合 PDF.js 展示的 PDF；Office 文档会临时转换且不修改原文件。"""
    content, err = ragflow_client.download_document(dataset_id, document_id)
    if err:
        raise HTTPException(status_code=502, detail=err)

    if content.startswith(b"%PDF"):
        return Response(content=content, media_type="application/pdf")

    safe_name = Path(filename or "").name
    extension = Path(safe_name).suffix.lower()
    supported_extensions = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp"}
    if extension not in supported_extensions:
        raise HTTPException(status_code=415, detail=f"暂不支持预览此文件格式: {extension or '未知'}")

    try:
        with tempfile.TemporaryDirectory(prefix="kbqa-preview-") as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / f"source{extension}"
            user_profile_path = temp_path / "libreoffice-profile"
            user_profile_path.mkdir()
            source_path.write_bytes(content)
            subprocess.run(
                [
                    "libreoffice",
                    "--headless",
                    f"-env:UserInstallation={user_profile_path.as_uri()}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(temp_path),
                    str(source_path),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
            pdf_path = temp_path / "source.pdf"
            if not pdf_path.exists():
                raise RuntimeError("LibreOffice 未生成 PDF 文件")
            pdf_content = pdf_path.read_bytes()
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        logger.exception("文档预览转换失败: %s", exc)
        raise HTTPException(status_code=502, detail="文档转换为 PDF 失败") from exc

    return Response(content=pdf_content, media_type="application/pdf")
