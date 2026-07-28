"""Unit tests for backend/services/knowledge_qa/kb_qa_service.py"""
from unittest.mock import MagicMock

from backend.services.knowledge_qa.kb_qa_service import KbQaService


def test_chat_returns_answer_and_references():
    """主流程返回 answer + references + used_kb_ids。"""
    repo = MagicMock()
    repo.get_recent_messages.return_value = []
    router = MagicMock()
    router.route.return_value = ["kb-1", "kb-2"]
    mgr = MagicMock()
    mgr.get_or_create.return_value = "chat-1"
    mgr.update_datasets.return_value = True

    ragflow = MagicMock()
    ragflow.chat_sync.return_value = {
        "success": True,
        "answer": "测试答案 ##0$$",
        "thinking": "",
        "references": {"total": 1, "chunks": [], "doc_aggs": []},
    }

    kb_list = [
        {"id": "kb-1", "name": "合规性", "rag_dataset_id": "ds-1"},
        {"id": "kb-2", "name": "SOP", "rag_dataset_id": "ds-2"},
    ]
    kb_repo = MagicMock()
    kb_repo.list_accessible = MagicMock(return_value=kb_list)

    svc = KbQaService(
        repo=repo,
        kb_repo=kb_repo,
        kb_router=router,
        chat_assistant_mgr=mgr,
        ragflow_client=ragflow,
    )
    svc.set_llm_call(lambda p: "summary")

    result = svc.chat(
        db=MagicMock(),
        user_id=1,
        session_id="sess-1",
        question="问题",
        manual_kb_ids=[],
    )

    assert result["answer"] == "测试答案 ##0$$"
    assert set(result["used_kb_ids"]) == {"kb-1", "kb-2"}
    assert "references" in result


def test_chat_uses_manual_kb_ids_when_router_fails():
    """路由失败时回退到 manual_kb_ids。"""
    repo = MagicMock()
    repo.get_recent_messages.return_value = []
    router = MagicMock()
    router.route.return_value = []
    mgr = MagicMock()
    mgr.get_or_create.return_value = "chat-1"
    mgr.update_datasets.return_value = True
    ragflow = MagicMock()
    ragflow.chat_sync.return_value = {
        "success": True,
        "answer": "答",
        "references": None,
    }
    kb_repo = MagicMock()
    kb_repo.list_accessible = MagicMock(return_value=[
        {"id": "kb-1", "name": "A", "rag_dataset_id": "ds-1"},
        {"id": "kb-2", "name": "B", "rag_dataset_id": "ds-2"},
    ])

    svc = KbQaService(
        repo=repo, kb_repo=kb_repo, kb_router=router,
        chat_assistant_mgr=mgr, ragflow_client=ragflow,
    )
    svc.set_llm_call(lambda p: "summary")

    result = svc.chat(
        db=MagicMock(), user_id=1, session_id="s",
        question="Q", manual_kb_ids=["kb-1"],
    )

    assert result["used_kb_ids"] == ["kb-1"]


def test_chat_uses_all_kbs_when_no_manual_and_router_fails():
    """路由失败且无 manual 时回退到全量。"""
    repo = MagicMock()
    repo.get_recent_messages.return_value = []
    router = MagicMock()
    router.route.return_value = []
    mgr = MagicMock()
    mgr.get_or_create.return_value = "chat-1"
    ragflow = MagicMock()
    ragflow.chat_sync.return_value = {"success": True, "answer": "A", "references": None}
    kb_repo = MagicMock()
    kb_repo.list_accessible = MagicMock(return_value=[
        {"id": "kb-1", "name": "A", "rag_dataset_id": "ds-1"},
        {"id": "kb-2", "name": "B", "rag_dataset_id": "ds-2"},
    ])

    svc = KbQaService(
        repo=repo, kb_repo=kb_repo, kb_router=router,
        chat_assistant_mgr=mgr, ragflow_client=ragflow,
    )
    svc.set_llm_call(lambda p: "summary")

    result = svc.chat(
        db=MagicMock(), user_id=1, session_id="s",
        question="Q", manual_kb_ids=[],
    )

    assert set(result["used_kb_ids"]) == {"kb-1", "kb-2"}