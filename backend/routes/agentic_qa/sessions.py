# cython: annotation_typing=False, infer_types=False, language_level=3
"""会话和消息 API"""
import json
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.core.agentic_qa.database import get_db
from backend.services.agentic_qa.models.user import User
from backend.services.agentic_qa.models.session import ChatSession
from backend.services.agentic_qa.models.message import ChatMessage
from backend.routes.agentic_qa.dependencies import get_current_user
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("api.sessions")

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── Pydantic models ──

class SessionCreate(BaseModel):
    id: str
    title: str = "新对话"

class SessionUpdate(BaseModel):
    title: str | None = None
    memory: str | None = None

class MessageCreate(BaseModel):
    id: str
    role: str
    content: str | None = None
    sql: str | None = None
    results: str | None = None
    steps: str | None = None
    intent: str | None = None
    source: str | None = None
    analysis_chart: str | None = None
    analysis_suggestions: str | None = None
    result_groups: str | None = None
    feedback_status: str | None = None
    feedback_text: str | None = None
    entity_candidates: str | None = None
    needs_clarification: bool = False
    clarification_options: str | None = None
    clarification_groups: str | None = None
    followups: str | None = None
    thinking: str | None = None
    rag_thinking: str | None = None
    rag_references: str | None = None
    timestamp: int = 0


# ── Session endpoints ──

@router.get("")
def list_sessions(
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * limit
    total = db.query(ChatSession).filter(ChatSession.user_id == current_user.id).count()
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "sessions": [s.to_dict() for s in sessions],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("")
def create_session(
    req: SessionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(ChatSession).filter(ChatSession.id == req.id).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="会话ID已存在")
    session = ChatSession(id=req.id, user_id=current_user.id, title=req.title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session.to_dict()


@router.get("/{session_id}")
def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.timestamp.asc())
        .all()
    )
    return {
        **session.to_dict(),
        "messages": [m.to_dict() for m in messages],
    }


@router.put("/{session_id}")
def update_session(
    session_id: str,
    req: SessionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    if req.title is not None:
        session.title = req.title
    if req.memory is not None:
        session.memory = req.memory
    db.commit()
    db.refresh(session)
    return session.to_dict()


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    db.delete(session)
    db.commit()
    return {"ok": True}


# ── Title generation ──

class GenerateTitleRequest(BaseModel):
    question: str


@router.post("/{session_id}/generate-title")
def generate_title(
    session_id: str,
    req: GenerateTitleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """根据用户首个问题自动生成会话标题"""
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    try:
        from backend.core.agentic_qa.llm import llm
        prompt = """你是一个会话标题生成器。请根据用户的问题生成一个非常简洁的标题（不超过15个字），直接返回标题文本，不要包含引号、标点或任何解释。

用户问题：{}

标题：""".format(req.question)
        response = llm.chat_once_with_retry(user_prompt=prompt, temperature=0.3, max_tokens=1024)
        title = response.strip().strip('"''「」『』《》')[:30]
        if not title:
            title = req.question[:30]
    except Exception as e:
        logger.warning(f"Title generation failed: {e}, using fallback")
        title = req.question[:30] if len(req.question) <= 30 else req.question[:27] + "..."

    session.title = title
    db.commit()
    return {"title": title}


# ── Message endpoints ──

@router.post("/{session_id}/messages")
def append_message(
    session_id: str,
    req: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    from sqlalchemy.exc import IntegrityError

    _UPDATE_FIELDS = ("content", "sql", "results", "steps", "intent", "source",
                      "analysis_chart", "analysis_suggestions", "result_groups",
                      "feedback_status", "feedback_text", "entity_candidates",
                      "needs_clarification", "clarification_options",
                      "clarification_groups", "followups", "thinking",
                      "rag_thinking", "rag_references", "timestamp")

    existing = db.query(ChatMessage).filter(ChatMessage.id == req.id).first()
    if existing:
        # 始终更新所有字段（包括 None），确保 feedback_status=null 等显式重置能生效
        for field in _UPDATE_FIELDS:
            setattr(existing, field, getattr(req, field, None))
    else:
        msg = ChatMessage(
            id=req.id,
            session_id=session_id,
            role=req.role,
            content=req.content,
            sql=req.sql,
            results=req.results,
            steps=req.steps,
            intent=req.intent,
            source=req.source,
            analysis_chart=req.analysis_chart,
            analysis_suggestions=req.analysis_suggestions,
            result_groups=req.result_groups,
            feedback_status=req.feedback_status,
            feedback_text=req.feedback_text,
            entity_candidates=req.entity_candidates,
            needs_clarification=req.needs_clarification,
            clarification_options=req.clarification_options,
            clarification_groups=req.clarification_groups,
            followups=req.followups,
            thinking=req.thinking,
            rag_thinking=req.rag_thinking,
            rag_references=req.rag_references,
            timestamp=req.timestamp,
        )
        db.add(msg)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # 并发写入导致主键冲突，改为更新
            existing = db.query(ChatMessage).filter(ChatMessage.id == req.id).first()
            if existing:
                for field in _UPDATE_FIELDS:
                    setattr(existing, field, getattr(req, field, None))
            db.commit()
        return {"ok": True, "id": req.id}
    db.commit()
    return {"ok": True, "id": req.id}
