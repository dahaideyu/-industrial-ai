"""Unit tests for backend/services/knowledge_qa/chat_assistant_mgr.py"""
from unittest.mock import MagicMock, patch
from backend.services.knowledge_qa.chat_assistant_mgr import ChatAssistantManager


def test_class_exists_with_methods():
    assert hasattr(ChatAssistantManager, "get_or_create")
    assert hasattr(ChatAssistantManager, "update_datasets")


def test_get_or_create_returns_existing_chat_id():
    """已有 chat_id 时直接返回，不调用 RAGFlow API。"""
    repo = MagicMock()
    repo.get_or_create_chat_assistant.return_value = MagicMock(
        ragflow_chat_id="existing-chat", user_id=1
    )
    mgr = ChatAssistantManager(repo=repo, ragflow_client=MagicMock())
    db = MagicMock()

    chat_id = mgr.get_or_create(db, user_id=1)

    assert chat_id == "existing-chat"
    repo.get_or_create_chat_assistant.assert_called_once()


def test_get_or_create_creates_new_chat_when_empty():
    """chat_id 为空时调用 RAGFlow 创建。"""
    repo = MagicMock()
    mock_map = MagicMock(ragflow_chat_id="", user_id=1)
    repo.get_or_create_chat_assistant.return_value = mock_map

    ragflow = MagicMock()
    ragflow.create_chat.return_value = "new-chat-id"

    mgr = ChatAssistantManager(repo=repo, ragflow_client=ragflow)
    db = MagicMock()

    chat_id = mgr.get_or_create(db, user_id=1, name_prefix="user-")

    assert chat_id == "new-chat-id"
    ragflow.create_chat.assert_called_once()
    assert mock_map.ragflow_chat_id == "new-chat-id"


def test_update_datasets_calls_patch():
    """update_datasets 应调用 PATCH + touch。"""
    repo = MagicMock()
    repo.get_or_create_chat_assistant.return_value = MagicMock(
        ragflow_chat_id="existing-chat", user_id=1
    )
    ragflow = MagicMock()
    ragflow.update_chat_datasets.return_value = True

    mgr = ChatAssistantManager(repo=repo, ragflow_client=ragflow)
    db = MagicMock()

    result = mgr.update_datasets(db, user_id=1, dataset_ids=["ds1", "ds2"])

    assert result is True
    ragflow.update_chat_datasets.assert_called_once_with(
        "existing-chat", ["ds1", "ds2"]
    )
    repo.touch_chat_assistant.assert_called_once()