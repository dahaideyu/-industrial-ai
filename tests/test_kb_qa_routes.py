"""Tests for backend/routes/knowledge_qa/routes.py

验证 kb-qa 路由模块可被导入，并且暴露 router + 关键 Pydantic 模型。
"""


def test_kbqa_router_module_exists():
    """kb-qa 路由模块可被导入。"""
    from backend.routes.knowledge_qa import routes as kbqa_routes_module
    assert kbqa_routes_module.router is not None
    assert hasattr(kbqa_routes_module, "ChatRequest")
    assert hasattr(kbqa_routes_module, "ChatResponse")
    assert hasattr(kbqa_routes_module, "KbOut")
