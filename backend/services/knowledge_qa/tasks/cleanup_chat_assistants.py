# cython: annotation_typing=False, infer_types=False, language_level=3
"""LRU 清理：清理 7 天无活动的 RAGFlow Chat Assistant。"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from backend.core.agentic_qa.config import settings
from backend.core.knowledge_management.database import SessionLocal
from backend.services.agentic_qa.ragflow.client import ragflow_client
from backend.services.knowledge_qa.repository import KbQaRepository

logger = logging.getLogger(__name__)


def cleanup_idle_chat_assistants(db: Optional[Session] = None, idle_days: Optional[int] = None) -> int:
    """清理超过 idle_days 未活动的 chat assistant。

    Returns:
        实际清理数量
    """
    idle_days = idle_days or settings.kbqa_session_idle_days
    if db is None:
        db = SessionLocal()

    repo = KbQaRepository()
    idle_mappers = repo.find_idle_chat_assistants(db, idle_days)
    cleaned = 0

    for m in idle_mappers:
        try:
            if m.ragflow_chat_id:
                ragflow_client.delete_chat(m.ragflow_chat_id)
            repo.delete_chat_assistant(db, m)
            cleaned += 1
            logger.info(
                f"[KBQA cleanup] cleaned user={m.user_id} chat={m.ragflow_chat_id}"
            )
        except Exception as e:
            logger.warning(
                f"[KBQA cleanup] failed to clean user={m.user_id}: {e}"
            )
            continue

    return cleaned