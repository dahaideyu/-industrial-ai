"""KBQA LRU 清理任务测试。"""
from unittest.mock import MagicMock, patch

from backend.services.knowledge_qa.tasks.cleanup_chat_assistants import (
    cleanup_idle_chat_assistants,
)


def test_cleanup_deletes_idle_chats():
    """LRU 清理应删除超过 idle_days 的 chat assistant。"""
    repo = MagicMock()
    mock_map = MagicMock(ragflow_chat_id="old-chat", user_id=1)
    repo.find_idle_chat_assistants.return_value = [mock_map]
    ragflow = MagicMock()
    ragflow.delete_chat.return_value = True

    db = MagicMock()

    with patch(
        "backend.services.knowledge_qa.tasks.cleanup_chat_assistants.KbQaRepository",
        return_value=repo,
    ), patch(
        "backend.services.knowledge_qa.tasks.cleanup_chat_assistants.ragflow_client",
        ragflow,
    ):
        count = cleanup_idle_chat_assistants(db, idle_days=7)

    assert count == 1
    ragflow.delete_chat.assert_called_once_with("old-chat")
    repo.delete_chat_assistant.assert_called_once()


def test_cleanup_skips_when_no_idle():
    repo = MagicMock()
    repo.find_idle_chat_assistants.return_value = []
    db = MagicMock()

    with patch(
        "backend.services.knowledge_qa.tasks.cleanup_chat_assistants.KbQaRepository",
        return_value=repo,
    ):
        count = cleanup_idle_chat_assistants(db, idle_days=7)

    assert count == 0