"""KBQA 配置项单元测试。

验证 backend/core/agentic_qa/config.py 中的 KBQA 相关配置项存在且默认值正确。
"""
from backend.core.agentic_qa.config import settings


def test_kbqa_settings_exist():
    """KBQA 配置项存在。"""
    assert hasattr(settings, "kbqa_router_llm")
    assert hasattr(settings, "kbqa_router_timeout")
    assert hasattr(settings, "kbqa_chat_timeout")
    assert hasattr(settings, "kbqa_history_full_turns")
    assert hasattr(settings, "kbqa_max_context_tokens")
    assert hasattr(settings, "kbqa_summary_model")
    assert hasattr(settings, "kbqa_session_idle_days")
    assert hasattr(settings, "kbqa_chat_assistant_name_prefix")


def test_kbqa_defaults():
    """默认值符合设计。"""
    assert settings.kbqa_router_llm == "deepseek-v4-flash"
    assert settings.kbqa_router_timeout == 8.0
    assert settings.kbqa_chat_timeout == 30.0
    assert settings.kbqa_history_full_turns == 3
    assert settings.kbqa_max_context_tokens == 6000
    assert settings.kbqa_session_idle_days == 7