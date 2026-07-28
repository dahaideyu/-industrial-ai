"""用户级 RAGFlow Chat Assistant 生命周期管理。"""

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.services.agentic_qa.ragflow.client import RAGFlowClient, RAGFlowError
from backend.services.knowledge_qa.repository import KbQaRepository

logger = logging.getLogger(__name__)


class ChatAssistantManager:
    """按用户懒创建 RAGFlow Chat Assistant，复用同一实例。"""

    def __init__(self, repo: KbQaRepository, ragflow_client: RAGFlowClient):
        self._repo = repo
        self._ragflow = ragflow_client

    def get_or_create(
        self,
        db: Session,
        user_id: int,
        name_prefix: str = "用户-",
        user_name: Optional[str] = None,
    ) -> str:
        """获取或创建用户的 Chat Assistant，返回 chat_id。

        Args:
            db: 数据库会话。
            user_id: 用户 ID。
            name_prefix: 名字前缀（默认"用户-"）。
            user_name: 用户名（username/display_name），用于更友好的 Chat Assistant 命名。
                       None 时回退到 "用户{user_id}"。
        """
        m = self._repo.get_or_create_chat_assistant(db, user_id)
        if m.ragflow_chat_id:
            return m.ragflow_chat_id

        # 懒创建。RAGFlow 的 Chat Assistant 名称建议使用人类可读形式：优先用用户名，缺失则用 ID。
        if user_name:
            chat_name = f"{name_prefix}{user_name}"
        else:
            chat_name = f"{name_prefix}{user_id}"

        try:
            chat_id = self._ragflow.create_chat(
                name=chat_name,
                dataset_ids=[],
            )
        except RAGFlowError as e:
            # 换库/重建数据卷后本地映射丢失，但 RAGFlow 已有同名助手：
            # 按名字找回复用并补录，避免 "Duplicated chat name" 把问答打成 500
            if "duplicated" not in str(e).lower():
                raise
            existing = self._ragflow.list_chats(name=chat_name)
            if not existing:
                raise
            chat_id = existing[0]["id"]
            logger.info(f"[KBQA] 复用 RAGFlow 已有 chat assistant: name={chat_name!r}, chat_id={chat_id}")
        m.ragflow_chat_id = chat_id
        db.commit()
        db.refresh(m)
        logger.info(f"[KBQA] created chat assistant: name={chat_name!r}, user_id={user_id}, chat_id={chat_id}")
        return chat_id

    def update_datasets(
        self,
        db: Session,
        user_id: int,
        dataset_ids: List[str],
    ) -> bool:
        """更新用户的 chat assistant dataset_ids，并 touch last_used_at。"""
        chat_id = self.get_or_create(db, user_id)
        ok = self._ragflow.update_chat_datasets(chat_id, dataset_ids)
        if ok:
            self._repo.touch_chat_assistant(db, user_id)
        return ok

    def delete(self, db: Session, user_id: int) -> bool:
        """删除用户的 chat assistant。"""
        m = self._repo.get_or_create_chat_assistant(db, user_id)
        if not m.ragflow_chat_id:
            return True
        try:
            self._ragflow.delete_chat(m.ragflow_chat_id)
        except Exception as e:
            logger.warning(f"[KBQA] failed to delete ragflow chat {m.ragflow_chat_id}: {e}")
        m.ragflow_chat_id = ""
        db.commit()
        return True