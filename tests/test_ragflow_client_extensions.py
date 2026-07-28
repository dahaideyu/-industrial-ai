# tests/test_ragflow_client_extensions.py
"""RAGFlowClient 扩展方法单元测试（Chat Assistant 生命周期管理）"""
from unittest.mock import patch
import pytest
from backend.services.agentic_qa.ragflow.client import RAGFlowClient


def test_create_chat_returns_chat_id():
    client = RAGFlowClient()
    with patch.object(client, "_post_json") as mock_post:
        mock_post.return_value = {"code": 0, "data": {"id": "chat-123"}}
        result = client.create_chat(name="user-1")
    assert result == "chat-123"


def test_update_chat_datasets_returns_true_on_200():
    client = RAGFlowClient()
    with patch.object(client, "_patch_json") as mock_patch:
        mock_patch.return_value = {"code": 0}
        result = client.update_chat_datasets("chat-123", ["ds1", "ds2"])
    assert result is True


def test_delete_chat_returns_true_on_200():
    client = RAGFlowClient()
    with patch.object(client, "_delete_json") as mock_delete:
        mock_delete.return_value = {"code": 0}
        result = client.delete_chat("chat-123")
    assert result is True