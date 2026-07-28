from backend.services.knowledge_qa.kb_router import KbRouter


def test_class_has_route_method():
    assert hasattr(KbRouter, "route")


def test_route_keeps_manual_kb_ids():
    """手动选择的 KB 必须包含在结果中。"""
    router = KbRouter(llm_call=lambda p: '["kb-3"]')
    result = router.route(
        question="问题",
        history=[],
        manual_kb_ids=["kb-1", "kb-2"],
        available_kbs=[
            {"id": "kb-1", "name": "A", "description": "desc A"},
            {"id": "kb-2", "name": "B", "description": "desc B"},
            {"id": "kb-3", "name": "C", "description": "desc C"},
        ],
    )
    assert "kb-1" in result
    assert "kb-2" in result


def test_route_returns_empty_on_llm_failure():
    """LLM 异常时返回空列表（让调用方兜底）。"""
    def bad_llm(p):
        raise RuntimeError("LLM error")

    router = KbRouter(llm_call=bad_llm)
    result = router.route(
        question="问题",
        history=[],
        manual_kb_ids=[],
        available_kbs=[{"id": "kb-1", "name": "A"}],
    )
    assert result == []


def test_route_parses_json_response():
    """正常 LLM 响应应被解析为 KB id 列表。"""
    router = KbRouter(llm_call=lambda p: '["kb-1", "kb-3"]')
    result = router.route(
        question="问题",
        history=[],
        manual_kb_ids=[],
        available_kbs=[
            {"id": "kb-1", "name": "A"},
            {"id": "kb-2", "name": "B"},
            {"id": "kb-3", "name": "C"},
        ],
    )
    assert set(result) == {"kb-1", "kb-3"}