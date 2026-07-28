# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库问答数据访问层。"""

import json
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.models.knowledge_qa import (
    KbQaMessage,
    KbQaSession,
    UserChatAssistant,
)


class KbQaRepository:
    """封装 KBQA 相关的 DB 访问。"""

    # ---- Chat Assistant 映射 ----

    def get_or_create_chat_assistant(
        self, db: Session, user_id: int
    ) -> UserChatAssistant:
        """获取或懒创建用户的 Chat Assistant 映射（chat_id 由调用方填充）。"""
        m = (
            db.query(UserChatAssistant)
            .filter(UserChatAssistant.user_id == user_id)
            .one_or_none()
        )
        if m is None:
            m = UserChatAssistant(
                user_id=user_id,
                ragflow_chat_id="",  # 后续由 manager 填充
            )
            db.add(m)
            db.commit()
            db.refresh(m)
        return m

    def update_chat_assistant_id(
        self, db: Session, user_id: int, ragflow_chat_id: str
    ) -> None:
        """更新用户的 ragflow_chat_id 和 last_used_at。"""
        m = (
            db.query(UserChatAssistant)
            .filter(UserChatAssistant.user_id == user_id)
            .one()
        )
        m.ragflow_chat_id = ragflow_chat_id
        m.last_used_at = datetime.utcnow()
        db.commit()

    def touch_chat_assistant(self, db: Session, user_id: int) -> None:
        """更新 last_used_at。"""
        m = (
            db.query(UserChatAssistant)
            .filter(UserChatAssistant.user_id == user_id)
            .one_or_none()
        )
        if m:
            m.last_used_at = datetime.utcnow()
            db.commit()

    def find_idle_chat_assistants(
        self, db: Session, idle_days: int
    ) -> List[UserChatAssistant]:
        """查找超过 N 天未活动的 chat assistant。"""
        threshold = datetime.utcnow() - timedelta(days=idle_days)
        return (
            db.query(UserChatAssistant)
            .filter(UserChatAssistant.last_used_at < threshold)
            .filter(UserChatAssistant.ragflow_chat_id != "")
            .all()
        )

    def delete_chat_assistant(self, db: Session, m: UserChatAssistant) -> None:
        db.delete(m)
        db.commit()

    # ---- Session ----

    def create_session(
        self, db: Session, user_id: int, title: str = "新会话"
    ) -> KbQaSession:
        s = KbQaSession(user_id=user_id, title=title)
        db.add(s)
        db.commit()
        db.refresh(s)
        return s

    def get_session(self, db: Session, session_id: str) -> Optional[KbQaSession]:
        return db.query(KbQaSession).filter(KbQaSession.id == session_id).one_or_none()

    def list_sessions(self, db: Session, user_id: int) -> List[KbQaSession]:
        return (
            db.query(KbQaSession)
            .filter(KbQaSession.user_id == user_id)
            .order_by(KbQaSession.updated_at.desc())
            .all()
        )

    def touch_session(self, db: Session, session_id: str) -> None:
        s = self.get_session(db, session_id)
        if s:
            s.updated_at = datetime.utcnow()
            db.commit()

    def delete_session(self, db: Session, session_id: str, user_id: int) -> bool:
        """删除会话及其所有消息。返回是否成功。"""
        s = (
            db.query(KbQaSession)
            .filter(KbQaSession.id == session_id, KbQaSession.user_id == user_id)
            .one_or_none()
        )
        if s is None:
            return False
        # 先删除关联的消息
        db.query(KbQaMessage).filter(KbQaMessage.session_id == session_id).delete()
        # 再删除会话
        db.delete(s)
        db.commit()
        return True

    # ---- Message ----

    def create_message(
        self,
        db: Session,
        session_id: str,
        role: str,
        content: str,
        used_kb_ids: Optional[List[str]] = None,
        rag_references: Optional[dict] = None,
    ) -> KbQaMessage:
        m = KbQaMessage(
            session_id=session_id,
            role=role,
            content=content,
            used_kb_ids=json.dumps(used_kb_ids, ensure_ascii=False) if used_kb_ids else None,
            rag_references=json.dumps(rag_references, ensure_ascii=False) if rag_references else None,
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        return m

    def get_recent_messages(
        self, db: Session, session_id: str, limit: int = 20
    ) -> List[KbQaMessage]:
        """取最近 N 条消息（按时间倒序再正序）。"""
        rows = (
            db.query(KbQaMessage)
            .filter(KbQaMessage.session_id == session_id)
            .order_by(KbQaMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(rows))
