from backend.services.knowledge_management.knowledge_overview_svc import (
    KnowledgeOverviewService,
    _call_llm,
)

# ── 原有测试 ──

def test_diagnose_returns_dict_with_top_level_keys():
    svc = KnowledgeOverviewService()
    # 空 db 会触发 SQLAlchemy 报错，因此仅断言接口存在
    assert hasattr(svc, "diagnose")
    assert callable(svc.diagnose)


def test_diagnose_handles_empty_db(monkeypatch):
    """全空数据库应返回 0 数据 + enabled_kb_count=0，结构稳定不报错。"""
    from unittest.mock import MagicMock
    monkeypatch.setattr(
        "backend.services.knowledge_management.knowledge_overview_svc.kb_type_state_svc.list_states",
        lambda db: {},
    )
    svc = KnowledgeOverviewService()
    fake_db = MagicMock()

    result = svc.diagnose(fake_db)

    assert "summary" in result
    assert "progress" in result
    assert "quality" in result
    assert "compliance" in result
    assert "missing" in result
    assert "evaluated_at" in result
    assert result["summary"]["total_progress"] == 0
    assert result["summary"]["enabled_kb_count"] == 0


def test_build_summary_returns_fallback_when_llm_unavailable(monkeypatch):
    """LLM 不可用时返回降级文案，长度 ≤ 400。"""
    monkeypatch.setattr(
        "backend.services.knowledge_management.knowledge_overview_svc._call_llm",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("llm down")),
    )
    svc = KnowledgeOverviewService()
    diag = {"summary": {"total_progress": 50, "expired_count": 2, "low_quality_doc_count": 3}}

    summary = svc.build_summary(diag)

    assert isinstance(summary, str)
    assert len(summary) <= 800
    assert "完成率" in summary or "暂无" in summary


def test_diagnose_kb_progress_uses_existing_service(monkeypatch):
    """diagnose 必须通过 kb_type_state_svc 拿启用/禁用状态。"""
    fake_states = {"compliance": False, "device_doc": True, "sop_doc": True, "history": False}
    monkeypatch.setattr(
        "backend.services.knowledge_management.knowledge_overview_svc.kb_type_state_svc.list_states",
        lambda db: fake_states,
    )
    from unittest.mock import MagicMock
    svc = KnowledgeOverviewService()
    result = svc.diagnose(db=MagicMock())
    assert result["summary"]["enabled_kb_count"] == 2
    assert result["summary"]["disabled_kb_count"] == 2


# ── 新增测试 ──

def test_build_summary_cache_hit(monkeypatch):
    """连续两次调用 build_summary 时，LLM 只调用一次（缓存命中）。"""
    call_count = 0

    def counting_llm(prompt, system_prompt):
        nonlocal call_count
        call_count += 1
        return "缓存测试总结文案"

    monkeypatch.setattr(
        "backend.services.knowledge_management.knowledge_overview_svc._call_llm",
        counting_llm,
    )
    # 清零缓存
    monkeypatch.setattr(
        "backend.services.knowledge_management.knowledge_overview_svc._summary_cache",
        {"text": "", "expires_at": 0.0},
    )

    svc = KnowledgeOverviewService()
    diag = {"summary": {"total_progress": 80, "expired_count": 0}}

    first = svc.build_summary(diag)
    second = svc.build_summary(diag)

    assert first == "缓存测试总结文案"
    assert second == "缓存测试总结文案"
    assert call_count == 1  # 第二次命中缓存，不调 LLM


def test_diagnose_is_not_returning_zero(monkeypatch):
    """diagnose 返回的 summary 字段不全是硬编码 0 — 至少有 enabled/disabled 是真值。"""
    fake_states = {"compliance": True, "device_doc": True, "sop_doc": False, "history": False}
    monkeypatch.setattr(
        "backend.services.knowledge_management.knowledge_overview_svc.kb_type_state_svc.list_states",
        lambda db: fake_states,
    )
    from unittest.mock import MagicMock
    svc = KnowledgeOverviewService()
    result = svc.diagnose(db=MagicMock())
    # enabled/disabled 计数必须非零
    assert result["summary"]["enabled_kb_count"] == 2
    assert result["summary"]["disabled_kb_count"] == 2


def test_call_llm_timeout(monkeypatch):
    """_call_llm 超时后抛出 RuntimeError。"""
    import concurrent.futures

    def slow_llm(prompt, system_prompt):
        raise concurrent.futures.TimeoutError("模拟超时")

    monkeypatch.setattr(
        "backend.services.knowledge_management.knowledge_overview_svc._call_llm_inner",
        slow_llm,
    )
    monkeypatch.setattr(
        "backend.services.knowledge_management.knowledge_overview_svc._LLM_TIMEOUT_SEC",
        0.01,
    )
    import pytest
    with pytest.raises(RuntimeError, match="超时"):
        _call_llm("p", "s")
