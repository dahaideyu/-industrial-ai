"""ORM 模型单元测试：UserChatAssistant / KbQaSession / KbQaMessage。

验证 3 个模型继承 SQLAlchemy Base，并包含必需的字段。
"""
from backend.models.knowledge_qa import (
    UserChatAssistant,
    KbQaSession,
    KbQaMessage,
)


def test_models_exist_and_inherit_base():
    """ORM 模型定义存在且继承 SQLAlchemy Base"""
    from backend.core.knowledge_management.database import Base

    assert issubclass(UserChatAssistant, Base)
    assert issubclass(KbQaSession, Base)
    assert issubclass(KbQaMessage, Base)


def test_user_chat_assistant_columns():
    """UserChatAssistant 含必需字段"""
    cols = {c.name for c in UserChatAssistant.__table__.columns}
    assert {"user_id", "ragflow_chat_id", "last_used_at"}.issubset(cols)


def test_session_columns():
    """KbQaSession 含必需字段"""
    cols = {c.name for c in KbQaSession.__table__.columns}
    assert {"id", "user_id", "title"}.issubset(cols)


def test_message_columns():
    """KbQaMessage 含必需字段"""
    cols = {c.name for c in KbQaMessage.__table__.columns}
    assert {"session_id", "role", "content", "used_kb_ids", "rag_references"}.issubset(cols)