"""维修建议通用 LLM 服务测试。"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from backend.modules.repair_suggestion.config import Config
from backend.modules.repair_suggestion.services.deepseek_service import (
    DeepSeekService as LegacyDeepSeekService,
)
from backend.modules.repair_suggestion.services.llm_service import (
    DeepSeekService,
    LLMService,
)


class FakeResponse:
    """模拟 OpenAI 兼容接口响应。"""

    status_code = 200
    text = ""

    def json(self) -> dict[str, Any]:
        """返回最小聊天响应。

        Returns:
            OpenAI 兼容响应数据。
        """
        return {"choices": [{"message": {"content": "完成"}}]}


class FakeAsyncClient:
    """模拟 httpx 异步客户端，避免测试访问网络。"""

    def __init__(self, timeout: float) -> None:
        """保存超时时间。

        Args:
            timeout: 请求超时时间。
        """
        self.timeout = timeout

    async def __aenter__(self) -> "FakeAsyncClient":
        """进入异步上下文。

        Returns:
            当前客户端。
        """
        return self

    async def __aexit__(self, *args: Any) -> None:
        """退出异步上下文。

        Args:
            *args: 异常上下文参数。
        """

    async def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
        """返回模拟成功响应。

        Args:
            *args: 请求位置参数。
            **kwargs: 请求关键字参数。

        Returns:
            模拟响应。
        """
        return FakeResponse()


@pytest.mark.asyncio
async def test_repair_llm_log_uses_actual_provider(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """维修建议日志应显示真实供应商，而不是写死 DeepSeek。"""
    monkeypatch.setattr(Config, "LLM_PROVIDER", "kimi")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://kimi.example/v1")
    monkeypatch.setattr(Config, "LLM_API_KEY", "secret")
    monkeypatch.setattr(Config, "LLM_MODEL", "kimi-model")
    monkeypatch.setattr(
        "backend.modules.repair_suggestion.services.llm_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    caplog.set_level(logging.INFO)

    service = LLMService()
    content, error = await service.chat("系统提示", "用户提示")

    assert content == "完成"
    assert error is None
    assert "provider=kimi" in caplog.text
    assert "model=kimi-model" in caplog.text
    assert "[DeepSeek]" not in caplog.text


def test_deepseek_service_alias_keeps_backward_compatibility() -> None:
    """旧类名保留为兼容别名，避免外部调用立即失效。"""
    assert DeepSeekService is LLMService
    assert LegacyDeepSeekService is LLMService
