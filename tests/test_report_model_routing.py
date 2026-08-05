"""报告模型路由与日志测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from backend.services.report_generator import (
    ModelConfigurationError,
    ReportGenerator,
    ReportModelExhaustedError,
)


class RecordingJobLogger:
    """记录格式化后的作业日志，便于验证实际模型选择。"""

    def __init__(self) -> None:
        """初始化日志容器。"""
        self.messages: list[str] = []

    def info(self, message: str, *args: Any) -> None:
        """记录一条 info 日志。

        Args:
            message: 日志模板。
            *args: 日志模板参数。
        """
        self.messages.append(message % args if args else message)


class RecordingCompletions:
    """记录 OpenAI 兼容接口收到的请求参数。"""

    def __init__(self) -> None:
        """初始化请求记录。"""
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        """记录生成参数并返回最小响应。

        Args:
            **kwargs: OpenAI聊天接口参数。

        Returns:
            带有固定内容的模拟响应。
        """
        self.kwargs = kwargs
        message = type("Message", (), {"content": "模型响应"})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class RecordingLLMClient:
    """提供可记录请求的 OpenAI 客户端替身。"""

    def __init__(self) -> None:
        """初始化聊天接口层级。"""
        self.completions = RecordingCompletions()
        self.chat = type("Chat", (), {"completions": self.completions})()


class FakeModelError(Exception):
    """携带 HTTP 状态码的模型调用异常。"""

    def __init__(self, status_code: int, message: str = "模型调用失败") -> None:
        """初始化模拟异常。

        Args:
            status_code: HTTP 状态码。
            message: 异常消息。
        """
        super().__init__(message)
        self.status_code = status_code


def _set_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
) -> None:
    """设置一个完整的供应商环境配置。

    Args:
        monkeypatch: Pytest 环境变量替换工具。
        provider: 供应商名称。
        base_url: API 地址。
        api_key: API 密钥。
        model: 模型名称。
    """
    provider_upper = provider.upper()
    monkeypatch.setenv(f"{provider_upper}_BASE_URL", base_url)
    monkeypatch.setenv(f"{provider_upper}_API_KEY", api_key)
    monkeypatch.setenv(f"{provider_upper}_MODEL", model)


def _create_generator(
    monkeypatch: pytest.MonkeyPatch,
    model_config: dict[str, Any],
) -> ReportGenerator:
    """创建使用内存模型配置的报告生成器。

    Args:
        monkeypatch: Pytest替换工具。
        model_config: 模型路由配置。

    Returns:
        报告生成器实例。
    """
    monkeypatch.setattr(ReportGenerator, "_load_model_config_file", lambda self: model_config)
    return ReportGenerator()


def test_report_model_routing_uses_specific_and_default_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """指定报告使用专属供应商，其他报告保持使用全局供应商。"""
    monkeypatch.setenv("PROVIDER", "kimi")
    monkeypatch.delenv("MODEL", raising=False)
    _set_provider(
        monkeypatch,
        "kimi",
        base_url="https://kimi.example/v1",
        api_key="kimi-secret",
        model="kimi-model",
    )
    _set_provider(
        monkeypatch,
        "deepseek",
        base_url="https://deepseek.example/v1",
        api_key="deepseek-secret",
        model="deepseek-model",
    )
    generator = _create_generator(
        monkeypatch,
        {"report_models": {"qualityDailyReport": {"provider": "deepseek"}}},
    )

    default_config = generator._get_llm_config_for_report("leanMorningDailyReport")
    quality_config = generator._get_llm_config_for_report("qualityDailyReport")

    assert default_config["provider"] == "kimi"
    assert default_config["model"] == "kimi-model"
    assert default_config["source"] == "default_provider"
    assert quality_config["provider"] == "deepseek"
    assert quality_config["model"] == "deepseek-model"
    assert quality_config["source"] == "report_models.qualityDailyReport.provider"


def test_report_model_routing_rejects_incomplete_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """专属供应商配置不完整时必须报错，不能与默认供应商混搭。"""
    monkeypatch.setenv("PROVIDER", "kimi")
    monkeypatch.delenv("MODEL", raising=False)
    _set_provider(
        monkeypatch,
        "kimi",
        base_url="https://kimi.example/v1",
        api_key="kimi-secret",
        model="kimi-model",
    )
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    generator = _create_generator(
        monkeypatch,
        {"report_models": {"qualityDailyReport": {"provider": "deepseek"}}},
    )

    with pytest.raises(ModelConfigurationError, match="DEEPSEEK_MODEL"):
        generator._get_llm_config_for_report("qualityDailyReport")


def test_model_selection_log_contains_real_provider_and_no_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型选择日志应包含真实路由信息，且不能泄露密钥。"""
    monkeypatch.setenv("PROVIDER", "kimi")
    monkeypatch.delenv("MODEL", raising=False)
    _set_provider(
        monkeypatch,
        "kimi",
        base_url="https://user:password@kimi.example/v1?token=visible",
        api_key="never-log-this-key",
        model="kimi-model",
    )
    generator = _create_generator(monkeypatch, {"report_models": {}})
    monkeypatch.setattr(
        generator,
        "_load_report_config",
        lambda config_path=None: {
            "report_mapping": {
                "leanMorningDailyReport": [
                    {"template": "unused.txt", "output_name": "测试报告"}
                ]
            }
        },
    )
    logger = RecordingJobLogger()

    stream = generator.generate_reports_stream(
        {},
        "leanMorningDailyReport",
        job_logger=logger,
    )
    assert next(stream)["event"] == "start"
    combined_log = "\n".join(logger.messages)

    assert "provider=kimi" in combined_log
    assert "model=kimi-model" in combined_log
    assert "source=default_provider" in combined_log
    assert "base_url=" not in combined_log
    assert "kimi.example" not in combined_log
    assert "password" not in combined_log
    assert "token=visible" not in combined_log
    assert "never-log-this-key" not in combined_log


def test_selected_model_is_sent_to_llm_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """报告专属模型必须进入最终聊天接口请求，而不只是显示在日志中。"""
    monkeypatch.setenv("PROVIDER", "kimi")
    monkeypatch.delenv("MODEL", raising=False)
    _set_provider(
        monkeypatch,
        "kimi",
        base_url="https://kimi.example/v1",
        api_key="kimi-secret",
        model="kimi-model",
    )
    _set_provider(
        monkeypatch,
        "deepseek",
        base_url="https://deepseek.example/v1",
        api_key="deepseek-secret",
        model="deepseek-model",
    )
    generator = _create_generator(
        monkeypatch,
        {"report_models": {"qualityDailyReport": {"provider": "deepseek"}}},
    )
    client = RecordingLLMClient()
    monkeypatch.setattr(generator, "_get_llm_client", lambda config: client)
    monkeypatch.setattr(generator, "_load_template", lambda template_file: "{data_sources}")
    llm_config = generator._get_llm_config_for_report("qualityDailyReport")

    content = generator._generate_report({}, "unused.txt", llm_config)

    assert content == "模型响应"
    assert client.completions.kwargs["model"] == "deepseek-model"


def _create_failover_generator(monkeypatch: pytest.MonkeyPatch) -> ReportGenerator:
    """创建 OpenCode → DeepSeek 的测试生成器。

    Args:
        monkeypatch: Pytest 环境替换工具。

    Returns:
        使用零等待重试策略的报告生成器。
    """
    monkeypatch.setenv("PROVIDER", "deepseek")
    monkeypatch.delenv("MODEL", raising=False)
    _set_provider(
        monkeypatch,
        "opencode",
        base_url="https://opencode.example/v1",
        api_key="opencode-secret",
        model="opencode-model",
    )
    _set_provider(
        monkeypatch,
        "deepseek",
        base_url="https://deepseek.example/v1",
        api_key="deepseek-secret",
        model="deepseek-model",
    )
    return _create_generator(
        monkeypatch,
        {
            "retry_policy": {
                "max_attempts_per_model": 2,
                "backoff_seconds": 0,
                "heartbeat_interval_seconds": 10,
            },
            "default_models": [
                {"provider": "opencode"},
                {"provider": "deepseek"},
            ],
            "report_models": {
                "leanMorningDailyReport": {"providers": ["deepseek"]},
                "factoryMorningDailyReport": {"providers": ["deepseek"]},
            },
        },
    )


def test_morning_reports_use_only_deepseek_and_other_reports_use_failover_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两种早会日报只使用 DeepSeek，其他报告使用 OpenCode → DeepSeek。"""
    generator = _create_failover_generator(monkeypatch)

    lean_chain = generator._get_llm_configs_for_report("leanMorningDailyReport")
    factory_chain = generator._get_llm_configs_for_report("factoryMorningDailyReport")
    quality_daily_chain = generator._get_llm_configs_for_report("qualityDailyReport")
    quality_weekly_chain = generator._get_llm_configs_for_report("qualityWeeklyReport")

    assert [item["provider"] for item in lean_chain] == ["deepseek"]
    assert [item["provider"] for item in factory_chain] == ["deepseek"]
    assert [item["provider"] for item in quality_daily_chain] == ["opencode", "deepseek"]
    assert [item["provider"] for item in quality_weekly_chain] == ["opencode", "deepseek"]


def test_opencode_quota_error_falls_back_to_deepseek_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenCode 套餐限额属于不可短时恢复错误，应直接降级到 DeepSeek。"""
    generator = _create_failover_generator(monkeypatch)
    chain = generator._get_llm_configs_for_report("qualityWeeklyReport")
    calls: list[str] = []

    def fake_call(prompt: str, config: dict[str, Any]) -> str:
        """按供应商返回模拟调用结果。"""
        calls.append(config["provider"])
        if config["provider"] == "opencode":
            raise FakeModelError(429)
        return "DeepSeek 完整报告"

    monkeypatch.setattr(generator, "_call_model_once", fake_call)

    content, used_config = generator._call_model_with_failover("prompt", chain)

    assert content == "DeepSeek 完整报告"
    assert used_config["provider"] == "deepseek"
    assert calls == ["opencode", "deepseek"]


def test_transient_error_retries_current_model_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """网络类临时错误应先重试当前模型，重试成功后不降级。"""
    generator = _create_failover_generator(monkeypatch)
    chain = generator._get_llm_configs_for_report("qualityMonthlyReport")
    calls: list[str] = []

    def fake_call(prompt: str, config: dict[str, Any]) -> str:
        """首次调用失败，第二次调用成功。"""
        calls.append(config["provider"])
        if len(calls) == 1:
            raise TimeoutError("timeout")
        return "OpenCode 重试成功"

    monkeypatch.setattr(generator, "_call_model_once", fake_call)

    content, used_config = generator._call_model_with_failover("prompt", chain)

    assert content == "OpenCode 重试成功"
    assert used_config["provider"] == "opencode"
    assert calls == ["opencode", "opencode"]


def test_partial_stream_is_discarded_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenCode 流式输出中途失败时不得把残缺内容混入 DeepSeek 结果。"""
    generator = _create_failover_generator(monkeypatch)
    chain = generator._get_llm_configs_for_report("deviceMaintenanceWeeklyReport")
    calls: list[str] = []

    def fake_stream(
        prompt: str,
        config: dict[str, Any],
    ) -> Any:
        """返回包含中途失败的模拟流。"""
        calls.append(config["provider"])
        if config["provider"] == "opencode":
            yield "OpenCode 残缺内容"
            raise FakeModelError(429)
        yield "DeepSeek "
        yield "完整报告"

    monkeypatch.setattr(generator, "_iter_model_stream", fake_stream)

    events = list(generator._stream_model_with_failover("prompt", chain))
    success_event = next(event for event in events if event["event"] == "success")

    assert "".join(success_event["chunks"]) == "DeepSeek 完整报告"
    assert "OpenCode 残缺内容" not in success_event["chunks"]
    assert calls == ["opencode", "deepseek"]


def test_failed_provider_is_skipped_for_remaining_reports_in_same_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当前任务确认 OpenCode 不可用后，后续子报告应直接使用 DeepSeek。"""
    generator = _create_failover_generator(monkeypatch)
    chain = generator._get_llm_configs_for_report("qualityWeeklyReport")
    calls: list[str] = []
    disabled_providers: set[str] = set()

    def fake_call(prompt: str, config: dict[str, Any]) -> str:
        """OpenCode 固定限额，DeepSeek 正常返回。"""
        calls.append(config["provider"])
        if config["provider"] == "opencode":
            raise FakeModelError(429)
        return f"DeepSeek:{prompt}"

    monkeypatch.setattr(generator, "_call_model_once", fake_call)

    first, _ = generator._call_model_with_failover(
        "report-1",
        chain,
        disabled_providers=disabled_providers,
    )
    second, _ = generator._call_model_with_failover(
        "report-2",
        chain,
        disabled_providers=disabled_providers,
    )

    assert first == "DeepSeek:report-1"
    assert second == "DeepSeek:report-2"
    assert calls == ["opencode", "deepseek", "deepseek"]


def test_deepseek_is_final_model_and_exhaustion_raises_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """早会日报的 DeepSeek 重试失败后应终止，不得调用本地模型。"""
    generator = _create_failover_generator(monkeypatch)
    chain = generator._get_llm_configs_for_report("leanMorningDailyReport")
    calls: list[str] = []

    def fake_call(prompt: str, config: dict[str, Any]) -> str:
        """始终抛出临时错误以验证最终失败。"""
        calls.append(config["provider"])
        raise TimeoutError("timeout")

    monkeypatch.setattr(generator, "_call_model_once", fake_call)

    with pytest.raises(ReportModelExhaustedError, match="报告模型链全部失败"):
        generator._call_model_with_failover("prompt", chain)

    assert calls == ["deepseek", "deepseek"]


def test_missing_opencode_configuration_skips_to_deepseek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenCode 配置缺失时应保留可用的 DeepSeek 候选。"""
    generator = _create_failover_generator(monkeypatch)
    monkeypatch.delenv("OPENCODE_BASE_URL")
    monkeypatch.delenv("OPENCODE_API_KEY")
    monkeypatch.delenv("OPENCODE_MODEL")
    generator._model_config_cache.clear()

    chain = generator._get_llm_configs_for_report("qualityDailyReport")

    assert [item["provider"] for item in chain] == ["deepseek"]
