# tests/test_ragflow_chat_history.py
"""RAGFlowClient.chat_sync 多轮 history_messages 单元测试。"""
from unittest.mock import patch
import pytest
from backend.services.agentic_qa.ragflow.client import RAGFlowClient


def test_chat_sync_includes_history_messages():
    """history_messages 应被合并进 messages 数组。"""
    client = RAGFlowClient()
    captured = {}

    def fake_stream_post(method, url, **kwargs):
        captured["url"] = url
        import json
        captured["payload"] = json.loads(kwargs.get("content", b"{}"))
        class FakeResp:
            status_code = 200
            def iter_lines(self):
                return iter([])
        return FakeResp()

    import httpx
    with patch.object(httpx.Client, "stream", side_effect=fake_stream_post):
        client.chat_sync(
            question="当前问题",
            chat_id="chat-123",
            history_messages=[
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": "A1"},
            ],
        )

    msgs = captured["payload"]["messages"]
    assert len(msgs) == 3
    assert msgs[0] == {"role": "user", "content": "Q1"}
    assert msgs[1] == {"role": "assistant", "content": "A1"}
    assert msgs[2] == {"role": "user", "content": "当前问题"}


def test_chat_sync_works_without_history():
    """不传 history_messages 时应正常运作。"""
    client = RAGFlowClient()
    captured = {}

    def fake_stream_post(method, url, **kwargs):
        import json
        captured["payload"] = json.loads(kwargs.get("content", b"{}"))
        class FakeResp:
            status_code = 200
            def iter_lines(self):
                return iter([])
        return FakeResp()

    import httpx
    with patch.object(httpx.Client, "stream", side_effect=fake_stream_post):
        client.chat_sync(question="hi", chat_id="chat-123")

    msgs = captured["payload"]["messages"]
    assert len(msgs) == 1
    assert msgs[0] == {"role": "user", "content": "hi"}