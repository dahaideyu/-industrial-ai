# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库问答 ORM 模型。

注意：user_id 字段原本使用 ForeignKey("users.id")，但 users 表在另一个
SQLAlchemy Base（agentic_qa.database.Base）中，与本模块的 Base 不同。
为避免 create_all() 失败，user_id 字段保留为普通 int 字段，依赖应用层
保证数据完整性。
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.knowledge_management.database import Base


class UserChatAssistant(Base):
    """用户级 RAGFlow Chat Assistant 映射。"""
    __tablename__ = "kb_qa_user_chat_assistants"

    id: Mapped[int] = mapped_column(primary_key=True)
    # user_id 不加 FK 约束（users 表在不同 Base），仅做应用层引用
    user_id: Mapped[int] = mapped_column(unique=True, index=True)
    ragflow_chat_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    last_used_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)


class KbQaSession(Base):
    """知识库问答会话。"""
    __tablename__ = "kb_qa_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # user_id 不加 FK 约束（users 表在不同 Base），仅做应用层引用
    user_id: Mapped[int] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(String(200), default="新会话")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )


class KbQaMessage(Base):
    """知识库问答消息。"""
    __tablename__ = "kb_qa_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("kb_qa_sessions.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    used_kb_ids: Mapped[Optional[str]] = mapped_column(Text)
    rag_references: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)