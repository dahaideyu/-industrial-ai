# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库问答主流程。"""

import logging
import re
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from backend.core.agentic_qa.config import settings
from backend.services.agentic_qa.ragflow.client import RAGFlowClient
from backend.services.knowledge_qa.chat_assistant_mgr import ChatAssistantManager
from backend.services.knowledge_qa.kb_router import KbRouter
from backend.services.knowledge_qa.message_history import MessageHistoryBuilder
from backend.services.knowledge_qa.repository import KbQaRepository

logger = logging.getLogger(__name__)


def _clean_display_text(value: str) -> str:
    """清理上游提取或解码产生的不可显示字符。

    Unicode 替换字符表示原始字节已经丢失，无法可靠还原；移除它们比在工业
    文本中展示“��”更安全，同时保留其余可读内容。
    """
    if not value:
        return ""
    cleaned = value.replace("\x00", "").replace("\ufeff", "")
    return re.sub(r"\ufffd+", "", cleaned)


def _clean_references(references: Optional[dict]) -> Optional[dict]:
    """清理引用块中的显示文本，避免预览侧栏继续展示乱码。"""
    if not references:
        return references

    cleaned = dict(references)
    cleaned_chunks = []
    for chunk in references.get("chunks") or []:
        cleaned_chunk = dict(chunk)
        for field in ("content", "document_name"):
            if isinstance(cleaned_chunk.get(field), str):
                cleaned_chunk[field] = _clean_display_text(cleaned_chunk[field])
        cleaned_chunks.append(cleaned_chunk)
    cleaned["chunks"] = cleaned_chunks

    cleaned_doc_aggs = []
    for doc_agg in references.get("doc_aggs") or []:
        cleaned_doc_agg = dict(doc_agg)
        if isinstance(cleaned_doc_agg.get("doc_name"), str):
            cleaned_doc_agg["doc_name"] = _clean_display_text(cleaned_doc_agg["doc_name"])
        cleaned_doc_aggs.append(cleaned_doc_agg)
    cleaned["doc_aggs"] = cleaned_doc_aggs
    return cleaned


class KbQaService:
    """编排 KB 路由 + 历史拼接 + RAGFlow chat + 持久化。"""

    def __init__(
        self,
        repo: KbQaRepository,
        kb_repo,
        kb_router: KbRouter,
        chat_assistant_mgr: ChatAssistantManager,
        ragflow_client: RAGFlowClient,
        history_builder: Optional[MessageHistoryBuilder] = None,
        llm_call: Optional[Callable[[str], str]] = None,
    ):
        self._repo = repo
        self._kb_repo = kb_repo
        self._router = kb_router
        self._mgr = chat_assistant_mgr
        self._ragflow = ragflow_client
        self._history_builder = history_builder or MessageHistoryBuilder(
            max_tokens=settings.kbqa_max_context_tokens,
            full_turns=settings.kbqa_history_full_turns,
        )
        self._llm_call = llm_call

    def set_llm_call(self, llm_call: Callable[[str], str]) -> None:
        """注入 LLM 调用函数。"""
        self._llm_call = llm_call

    def chat(
        self,
        db: Session,
        user_id: int,
        session_id: str,
        question: str,
        manual_kb_ids: List[str],
        user_name: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """主对话流程。

        Args:
            on_chunk: 流式回调，每收到一个增量文本块时调用 on_chunk(delta_text)。
                      不传则为非流式，等待完整响应后返回。
        """
        # 1. 加载历史
        db_messages = self._repo.get_recent_messages(db, session_id, limit=20)
        history = [{"role": m.role, "content": m.content} for m in db_messages]

        # 2. 构造 messages（含摘要压缩）
        def _summary_func(older: List[dict]) -> str:
            if self._llm_call is None:
                return "（历史摘要暂不可用）"
            return self._history_builder.summarize_history(older, self._llm_call)

        messages = self._history_builder.build(
            question=question,
            recent_messages=history,
            summary_func=_summary_func,
        )

        # 3. 加载可用 KB
        available_kbs = self._kb_repo.list_accessible(db, user_id)
        if not available_kbs:
            return {
                "answer": "请联系管理员配置知识库后再提问",
                "references": None,
                "used_kb_ids": [],
                "message_id": 0,
                "session_id": session_id,
            }

        # 4. KB 路由
        used_kb_ids = self._router.route(
            question=question,
            history=history,
            manual_kb_ids=manual_kb_ids,
            available_kbs=available_kbs,
            llm_call=self._llm_call,
        )

        # 5. 路由失败兜底
        if not used_kb_ids:
            used_kb_ids = (
                list(manual_kb_ids)
                if manual_kb_ids
                else [kb["id"] for kb in available_kbs]
            )

        # 6. 更新 chat assistant datasets
        dataset_ids = [
            kb["rag_dataset_id"]
            for kb in available_kbs
            if kb["id"] in used_kb_ids and kb.get("rag_dataset_id")
        ]
        chat_id = self._mgr.get_or_create(
            db, user_id, name_prefix=settings.kbqa_chat_assistant_name_prefix,
            user_name=user_name,
        )
        self._ragflow.update_chat_datasets(chat_id, dataset_ids)
        self._repo.touch_chat_assistant(db, user_id)
        self._repo.touch_session(db, session_id)

        # 7. 调用 RAGFlow chat
        history_for_rag = messages[:-1]

        def _emit_clean_chunk(delta: str) -> None:
            """流式推送前清理不可显示字符。"""
            cleaned_delta = _clean_display_text(delta)
            if on_chunk is not None and cleaned_delta:
                on_chunk(cleaned_delta)

        rag_result = self._ragflow.chat_sync(
            question=question,
            chat_id=chat_id,
            history_messages=history_for_rag,
            on_chunk=_emit_clean_chunk if on_chunk is not None else None,
        )

        # 8. 提取 references
        answer = _clean_display_text(rag_result.get("answer", ""))
        thinking = _clean_display_text(rag_result.get("thinking", ""))
        refs = _clean_references(rag_result.get("references"))

        # 9. 持久化
        self._repo.create_message(
            db, session_id, "user", question, used_kb_ids=used_kb_ids
        )
        assistant_msg = self._repo.create_message(
            db,
            session_id,
            "assistant",
            answer,
            used_kb_ids=used_kb_ids,
            rag_references=refs,
        )

        return {
            "answer": answer,
            "thinking": thinking,
            "references": refs,
            "used_kb_ids": used_kb_ids,
            "message_id": assistant_msg.id,
            "session_id": session_id,
        }
