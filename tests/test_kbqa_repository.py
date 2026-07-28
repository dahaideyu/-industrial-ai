from backend.services.knowledge_qa.repository import KbQaRepository


def test_repository_class_exists():
    assert hasattr(KbQaRepository, "get_or_create_chat_assistant")
    assert hasattr(KbQaRepository, "update_chat_assistant_id")
    assert hasattr(KbQaRepository, "touch_chat_assistant")
    assert hasattr(KbQaRepository, "find_idle_chat_assistants")
    assert hasattr(KbQaRepository, "delete_chat_assistant")
    assert hasattr(KbQaRepository, "create_session")
    assert hasattr(KbQaRepository, "get_session")
    assert hasattr(KbQaRepository, "list_sessions")
    assert hasattr(KbQaRepository, "touch_session")
    assert hasattr(KbQaRepository, "create_message")
    assert hasattr(KbQaRepository, "get_recent_messages")
