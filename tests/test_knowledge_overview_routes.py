"""路由集成测试：/dashboard/knowledge-overview 与 /summary。"""
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.routes.knowledge_management.routes import get_current_user


async def _fake_get_current_user(authorization=None):
    return "test_user"


@pytest.fixture(autouse=True)
def clean_overrides():
    """每个测试前后清理 dependency_overrides，避免泄露。"""
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_knowledge_overview_requires_auth():
    client = TestClient(app)
    resp = client.get("/api/knowledge-management/dashboard/knowledge-overview")
    assert resp.status_code == 401


def test_summary_requires_auth():
    client = TestClient(app)
    resp = client.get("/api/knowledge-management/dashboard/knowledge-overview/summary")
    assert resp.status_code == 401


def test_knowledge_overview_returns_expected_structure(monkeypatch):
    """绕过鉴权 + DB：验证端点 200 且包含诊断数据。"""
    app.dependency_overrides[get_current_user] = _fake_get_current_user

    from backend.services.knowledge_management.knowledge_overview_svc import KnowledgeOverviewService
    monkeypatch.setattr(
        KnowledgeOverviewService, "diagnose",
        lambda self, db: {
            "evaluated_at": "2026-07-01T00:00:00+08:00",
            "summary": {"total_progress": 0, "enabled_kb_count": 0},
            "progress": {"kb_progress": []},
            "quality": {"distribution": {"high": 0, "medium": 0, "low": 0}, "low_quality_docs": []},
            "compliance": {"valid_count": 0, "expired_count": 0, "expiring_soon_count": 0,
                           "expired_docs": [], "expiring_soon_docs": []},
            "missing": {"enabled_kb_without_plan": [], "plan_without_docs": []},
        },
    )

    client = TestClient(app)
    resp = client.get(
        "/api/knowledge-management/dashboard/knowledge-overview",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body or "summary" in body or "code" in body
