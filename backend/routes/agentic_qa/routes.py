# cython: annotation_typing=False, infer_types=False, language_level=3
"""Agentic QA + Vanna 2.0 + RAGFlow API 路由"""
import json
import time
import traceback
from fastapi import APIRouter, Depends, HTTPException
from backend.routes.agentic_qa.dependencies import get_current_user
from backend.services.agentic_qa.models.user import User
from backend.services.agentic_qa.models.session import ChatSession
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from backend.core.agentic_qa.logger import get_logger
from backend.core.agentic_qa.database import get_db
from sqlalchemy.orm import Session

logger = get_logger("api.routes")
router = APIRouter()


class QueryRequest(BaseModel):
    question: str
    use_rag: Optional[bool] = False
    session_id: Optional[str] = None
    user_role: Optional[str] = "admin"
    session_memory: Optional[Dict[str, Any]] = None
    history: Optional[List[Dict[str, Any]]] = None


class QueryResponse(BaseModel):
    success: bool = True
    answer: str
    sql: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = None
    steps: Optional[List[Dict[str, Any]]] = None
    intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    needs_clarification: bool = False
    clarification_questions: Optional[List[str]] = None
    clarification_options: Optional[List[Any]] = None
    clarification_groups: Optional[List[Dict[str, Any]]] = None
    entity_candidates: Optional[List[Dict[str, Any]]] = None
    auto_completions: Optional[List[Dict[str, Any]]] = None
    session_memory: Optional[Dict[str, Any]] = None
    source: str = "agentic_qa"
    analysis_chart: Optional[Dict[str, Any]] = None
    result_groups: Optional[List[Dict[str, Any]]] = None
    analysis_suggestions: Optional[List[str]] = None
    followups: Optional[List[str]] = None
    rag_thinking: Optional[str] = None
    rag_references: Optional[Dict[str, Any]] = None
    thinking: Optional[str] = None  # agentic mode thinking log
    elapsed_ms: Optional[int] = None

def _load_session_memory(request: QueryRequest, db: Session) -> dict:
    """加载 session_memory，优先使用前端传递的，否则从数据库恢复。"""
    sm = request.session_memory
    if sm and isinstance(sm, dict):
        return sm
    # 前端未传或类型错误时，从数据库恢复
    if request.session_id:
        session = db.query(ChatSession).filter(ChatSession.id == request.session_id).first()
        if session and session.memory:
            try:
                parsed = json.loads(session.memory)
                if isinstance(parsed, dict):
                    logger.info(f"[query] loaded session_memory from db for session={request.session_id}")
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
    return {}


class ComposeRequest(BaseModel):
    question: str
    selections: List[Dict[str, Any]] = []  # [{field: "entity", values: ["所有设备"]}, ...]


@router.post("/query/compose")
async def compose_question(request: ComposeRequest):
    """将用户澄清选择拼接为自然语言问题"""
    if not request.selections:
        return {"question": request.question}

    parts = []
    for s in request.selections:
        field = s.get("field", "")
        vals = s.get("values", [])
        if not vals: continue
        text = "、".join(vals)
        if field == "entity": parts.append(f"查询对象: {text}")
        elif field == "metric": parts.append(f"查询指标: {text}")
        elif field == "time_range": parts.append(f"时间范围: {text}")
        else: parts.append(text)

    try:
        from backend.core.agentic_qa.llm import llm
        prompt = """将以下查询条件拼接成一句自然流畅的提问，像是用户直接说出来的。

原始问题: {}
条件: {}

要求: 自然口语化，不要机械拼接，不要用"查询""筛选"等SQL术语。
示例: "所有设备最近30天的故障次数" 而不是 "查询所有设备，故障次数，最近30天"
只输出问题文本，不要任何解释。""".format(request.question, '; '.join(parts))
        response = llm.chat_once_with_retry(user_prompt=prompt, temperature=0.3, max_tokens=2048)
        return {"question": response.strip().strip('"''""')}
    except Exception:
        # LLM 不可用时回退到简单拼接
        simple = "，".join(p.split(": ")[1] for p in parts)
        return {"question": simple or request.question}


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """智能问答接口 — agentic 多 Agent 引擎"""
    t0 = time.time()
    session_id = request.session_id or "default"
    logger.info(f"[query] session={session_id} use_rag={request.use_rag} question='{request.question[:80]}'")

    import asyncio as _asyncio
    from backend.services.agentic_qa.master_loop import run_master_loop
    from backend.routes.agentic_qa.websocket import push_step

    sm = _load_session_memory(request, db)
    history_text = ""
    history_list = request.history or []
    if history_list:
        parts = []
        for h in history_list[-5:]:
            q = h.get("question", "")
            a = h.get("answer", "")[:200]
            parts.append(f"用户: {q}\n助手: {a}")
        history_text = "\n".join(parts)

    async def on_step(event):
        try:
            await push_step(session_id, event)
        except Exception:
            pass

    result = await run_master_loop(
        question=request.question,
        session_id=session_id,
        step_callback=on_step,
        conversation_history=history_text,
        conversation_history_list=history_list,
        session_memory=sm,
    )

    elapsed = round((time.time() - t0) * 1000)
    answer = result.get("answer", "")
    sql = result.get("sql")
    logger.info(f"[query] response session={session_id} elapsed={elapsed}ms "
                f"answer_len={len(answer)} sql={'yes' if sql else 'no'} "
                f"needs_clarification={result.get('needs_clarification', False)}")

    return QueryResponse(
        success=True,
        answer=result.get("answer", ""),
        sql=result.get("sql"),
        results=result.get("results"),
        result_groups=result.get("result_groups"),
        steps=None,
        needs_clarification=result.get("needs_clarification", False),
        clarification_questions=(
            [result.get("clarification_message")] if result.get("needs_clarification") else None
        ),
        clarification_options=result.get("clarification_options"),
        clarification_groups=result.get("clarification_groups"),
        source="agentic_qa",
        analysis_chart=result.get("chart"),
        analysis_suggestions=result.get("analysis_suggestions") or None,
        followups=result.get("followups") or None,
        session_memory={},
        elapsed_ms=result.get("elapsed_ms"),
    )


class ConfirmRequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    user_role: Optional[str] = "admin"
    confirmed_entities: List[Dict[str, Any]] = []
    session_memory: Optional[Dict[str, Any]] = None
    history: Optional[List[Dict[str, Any]]] = None


@router.post("/query/confirm", response_model=QueryResponse)
async def query_confirm(request: ConfirmRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """实体确认接口 — 用户选择实体后，继续执行意图→SQL→执行流水线"""
    t0 = time.time()
    session_id = request.session_id or "default"
    logger.info(f"[confirm] session={session_id} entities={len(request.confirmed_entities)} "
                f"question='{request.question[:80]}'")

    sm = request.session_memory
    if not sm or not isinstance(sm, dict):
        sm = {}
    if not sm and request.session_id:
        session = db.query(ChatSession).filter(ChatSession.id == request.session_id).first()
        if session and session.memory:
            try:
                parsed = json.loads(session.memory)
                if isinstance(parsed, dict):
                    sm = parsed
            except (json.JSONDecodeError, TypeError):
                pass
    if request.history:
        sm["history"] = request.history

    # Inject confirmed entities into session memory
    if request.confirmed_entities:
        sm["confirmed_entities"] = request.confirmed_entities

    from backend.services.agentic_qa.master_loop import run_master_loop
    from backend.routes.agentic_qa.websocket import push_step

    async def on_step(event):
        try:
            await push_step(session_id, event)
        except Exception:
            pass

    result = await run_master_loop(
        question=request.question,
        session_id=session_id,
        step_callback=on_step,
        session_memory=sm,
    )

    elapsed = round((time.time() - t0) * 1000)
    answer = result.get("answer", "")
    sql = result.get("sql")
    logger.info(f"[confirm] response session={session_id} elapsed={elapsed}ms "
                f"answer_len={len(answer)} sql={'yes' if sql else 'no'} "
                f"needs_clarification={result.get('needs_clarification', False)}")

    return QueryResponse(
        success=True,
        answer=result.get("answer", ""),
        sql=result.get("sql"),
        results=result.get("results"),
        result_groups=result.get("result_groups"),
        steps=None,
        needs_clarification=result.get("needs_clarification", False),
        clarification_questions=(
            [result.get("clarification_message")] if result.get("needs_clarification") else None
        ),
        clarification_options=result.get("clarification_options"),
        clarification_groups=result.get("clarification_groups"),
        source="agentic_qa",
        analysis_chart=result.get("chart"),
        analysis_suggestions=result.get("analysis_suggestions") or None,
        followups=result.get("followups") or None,
        session_memory={},
        elapsed_ms=result.get("elapsed_ms"),
    )


class FeedbackRequest(BaseModel):
    question: str
    sql: str
    feedback: str  # "correct" | "wrong: <用户反馈内容>"
    session_id: Optional[str] = None


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest, current_user: User = Depends(get_current_user)):
    """用户反馈：正确→加入审核队列；错误→用反馈重新生成SQL"""
    t0 = time.time()
    logger.info(f"[feedback] question='{req.question[:60]}' feedback='{req.feedback[:60]}'")

    if req.feedback == "correct":
        # 分析触发词（无实际问题和SQL）不保存到训练审核
        if not req.sql and req.question.strip() in ("分析", "分析一下", "分析数据"):
            return {"success": True, "message": "分析反馈已记录", "action": "skipped"}

        # 无 SQL 的回复（通用问答、RAG等）无需存入训练记忆库
        if not req.sql:
            logger.info(f"[feedback] skipped (no SQL): '{req.question[:60]}'")
            return {"success": True, "message": "反馈已记录", "action": "skipped"}

        # 直接存入 Vanna 记忆库（标记为待审核）
        from backend.services.agentic_qa.vanna.agent import get_vanna_manager, _make_context
        manager = get_vanna_manager()
        ctx = _make_context(manager._memory, "admin")

        try:
            await manager._memory.save_tool_usage(
                question=f"[待审核] {req.question}",
                tool_name="run_sql",
                args={"sql": req.sql},
                context=ctx,
                success=True
            )
        except Exception as e:
            logger.error(f"[feedback] save failed: {e}")
            raise HTTPException(500, f"保存反馈失败: {e}")

        logger.info(f"[feedback] saved to Vanna memory: {req.question[:60]}")
        return {"success": True, "message": "已保存到记忆库", "action": "saved"}

    elif req.feedback.startswith("wrong:"):
        # 用户标记错误 → 记录反馈到审核队列（不再重新生成）
        correction = req.feedback[6:].strip()
        return await _record_error_feedback(
            question=req.question,
            sql=req.sql,
            answer="",
            user_feedback=correction,
            session_id=req.session_id,
        )

    raise HTTPException(400, "feedback 参数格式错误，应为 'correct' 或 'wrong: <内容>'")


class ErrorFeedbackRequest(BaseModel):
    question: str
    answer: Optional[str] = ""
    sql: Optional[str] = ""
    user_feedback: str
    session_id: Optional[str] = None


async def _record_error_feedback(
    question: str, sql: str, answer: str, user_feedback: str, session_id: str = None
) -> dict:
    """将错误反馈存入 Vanna 记忆库，带 [待审核-反馈] 标记"""
    from backend.services.agentic_qa.vanna.agent import get_vanna_manager, _make_context
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")

    try:
        await manager._memory.save_tool_usage(
            question=f"[待审核-反馈] {question}",
            tool_name="run_sql",
            args={
                "sql": sql,
                "answer": answer,
                "user_feedback": user_feedback,
            },
            context=ctx,
            success=True,
        )
    except Exception as e:
        logger.error(f"[feedback] error save failed: {e}")
        raise HTTPException(500, f"保存错误反馈失败: {e}")

    logger.info(
        f"[feedback] error recorded: question='{question[:60]}' "
        f"feedback='{user_feedback[:80]}'"
    )
    return {"success": True, "message": "反馈已记录，将在审核后用于训练优化", "action": "recorded"}


@router.post("/feedback/record")
async def submit_error_feedback(req: ErrorFeedbackRequest, current_user: User = Depends(get_current_user)):
    """记录错误反馈：收集 {question, answer, sql, user_feedback} 存入审核队列"""
    logger.info(
        f"[feedback] record: question='{(req.question or '')[:60]}' "
        f"feedback='{req.user_feedback[:80]}'"
    )
    return await _record_error_feedback(
        question=req.question,
        sql=req.sql or "",
        answer=req.answer or "",
        user_feedback=req.user_feedback,
        session_id=req.session_id,
    )


@router.post("/init")
async def initialize():
    """初始化 Vanna Agent 和记忆库"""
    try:
        from backend.services.agentic_qa.vanna.agent import init_vanna_agent
        init_vanna_agent()
        return {"success": True, "message": "Vanna Agent 初始化完成，记忆库已加载"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ragflow/document-preview")
async def preview_document(dataset_id: str, document_id: str):
    """代理下载 RAGFlow 文档内容（供前端引用预览）"""
    import base64
    from backend.services.agentic_qa.ragflow.client import ragflow_client

    content, err = ragflow_client.download_document(dataset_id, document_id)
    if err:
        raise HTTPException(status_code=502, detail=err)
    return {"success": True, "content": base64.b64encode(content).decode("ascii")}


@router.get("/ragflow/document-download")
async def download_document(dataset_id: str, document_id: str):
    """代理 RAGFlow 文档下载 — 浏览器新标签页直接渲染 PDF/文件"""
    from fastapi.responses import Response
    from backend.services.agentic_qa.ragflow.client import ragflow_client

    content, err = ragflow_client.download_document(dataset_id, document_id)
    if err:
        raise HTTPException(status_code=502, detail=err)
    # 以 PDF MIME 返回，浏览器内置 PDF 查看器会直接渲染
    # application/octet-stream 会导致浏览器强制下载而非预览
    return Response(content=content, media_type="application/pdf")


@router.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "industrial-qa-platform"}
