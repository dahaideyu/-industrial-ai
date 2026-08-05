# cython: annotation_typing=False, infer_types=False, language_level=3
"""
多报告生成器
支持一份配置生成多份报告（简化版，不涉及知识库）
支持流式输出（串行生成 + 顺序输出）
支持带引用的报告生成（通过 RAGFlow 检索接口）
"""
import os
import re
import json
import logging
import queue
import threading
import time
import yaml
from typing import Any, Dict, List, Generator
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
import httpx
from clients.ragflow_client import get_ragflow_client
from backend.utils.data_cleaner import clean_raw_data, EXCLUDED_SOURCE_KEY_PREFIXES

logger = logging.getLogger(__name__)


class ModelConfigurationError(ValueError):
    """模型供应商或报告模型路由配置无效。"""


class ReportModelExhaustedError(RuntimeError):
    """报告模型链中的所有候选模型均调用失败。"""


class ReportGenerator:
    """多报告生成器"""

    def __init__(
        self,
        llm_model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        max_workers: int = 3,
    ) -> None:
        """
        初始化报告生成器

        Args:
            llm_model: LLM 模型名称
            base_url: LLM API 地址
            api_key: LLM API 密钥
            max_workers: 最大并发数（默认为3，可根据 API 限制调整）
        """
        self.provider = os.getenv("PROVIDER", "local_qwen3").strip().lower()
        provider_upper = self.provider.upper()
        base_url = base_url or os.getenv(f"{provider_upper}_BASE_URL")
        api_key = api_key or os.getenv(f"{provider_upper}_API_KEY")
        default_model = os.getenv(f"{provider_upper}_MODEL", "")

        self.base_url = base_url
        self.api_key = api_key
        self.model = llm_model or os.getenv("MODEL", default_model)
        self.max_workers = max_workers
        self._validate_model_config(
            {
                "provider": self.provider,
                "base_url": self.base_url,
                "api_key": self.api_key,
                "model": self.model,
            },
            context="默认模型",
            missing_names={
                "base_url": f"{provider_upper}_BASE_URL",
                "api_key": f"{provider_upper}_API_KEY",
                "model": f"{provider_upper}_MODEL 或 MODEL",
            },
        )

        # 检测 Ollama 并修正 base_url（Ollama OpenAI 兼容端点需要 /v1 后缀）
        if self._is_ollama():
            self.base_url = self._normalize_ollama_url(self.base_url)

        self.llm = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=600.0,
            max_retries=0,
        )

        # 模型配置缓存：{report_code: [{provider/base_url/api_key/model/...}, ...]}
        self._model_config_cache: dict[str, list[dict[str, Any]]] = {}
        # 加载模型配置文件
        self._model_config = self._load_model_config_file()
        retry_policy = self._model_config.get("retry_policy", {})
        if not isinstance(retry_policy, dict):
            raise ModelConfigurationError("retry_policy 必须是字典配置")
        self.max_attempts_per_model = int(self._positive_number(
            retry_policy.get("max_attempts_per_model", 2),
            name="retry_policy.max_attempts_per_model",
            number_type=int,
        ))
        self.retry_backoff_seconds = float(self._positive_number(
            retry_policy.get("backoff_seconds", 2),
            name="retry_policy.backoff_seconds",
            number_type=float,
            allow_zero=True,
        ))
        self.heartbeat_interval_seconds = float(self._positive_number(
            retry_policy.get("heartbeat_interval_seconds", 10),
            name="retry_policy.heartbeat_interval_seconds",
            number_type=float,
        ))

    @staticmethod
    def _positive_number(
        value: Any,
        *,
        name: str,
        number_type: type[int] | type[float],
        allow_zero: bool = False,
    ) -> int | float:
        """读取并校验重试策略中的正数配置。

        Args:
            value: 原始配置值。
            name: 配置项名称。
            number_type: 目标数值类型。
            allow_zero: 是否允许零。

        Returns:
            校验后的数值。

        Raises:
            ModelConfigurationError: 配置不是有效数值或超出允许范围。
        """
        try:
            parsed = number_type(value)
        except (TypeError, ValueError) as exc:
            raise ModelConfigurationError(f"{name} 必须是有效数字") from exc
        minimum = 0 if allow_zero else 1
        if parsed < minimum:
            comparator = "大于等于 0" if allow_zero else "大于 0"
            raise ModelConfigurationError(f"{name} 必须{comparator}")
        return parsed

    def _load_model_config_file(self) -> dict:
        """
        加载模型配置文件 config/model_config.yaml

        Returns:
            配置字典，如果文件不存在则返回空字典
        """
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(project_root, 'backend', 'config', 'model_config.yaml')

        if not os.path.exists(config_path):
            logger.debug("[模型配置] 配置文件不存在: %s，使用默认模型配置", config_path)
            return {}

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                logger.debug("[模型配置] 已加载配置文件: %s", config_path)
                return config or {}
        except Exception as e:
            logger.warning("[模型配置] 加载配置文件失败: %s，使用默认模型配置", e)
            return {}

    @staticmethod
    def _validate_model_config(
        config: dict,
        *,
        context: str,
        missing_names: dict[str, str] | None = None,
    ) -> None:
        """校验一套模型配置必须来自同一供应商且字段完整。

        Args:
            config: 待校验的模型配置。
            context: 用于错误信息的配置来源说明。
            missing_names: 字段缺失时展示的环境变量或配置项名称。

        Raises:
            ModelConfigurationError: 供应商、地址、密钥或模型名称缺失。
        """
        required_fields = ("provider", "base_url", "api_key", "model")
        missing_fields = [field for field in required_fields if not config.get(field)]
        if not missing_fields:
            return

        labels = missing_names or {}
        missing_labels = [labels.get(field, field) for field in missing_fields]
        raise ModelConfigurationError(
            f"{context}配置不完整，缺少: {', '.join(missing_labels)}；"
            "为避免跨供应商混用，不会回退到默认模型配置"
        )

    def _resolve_provider_config(self, provider: str) -> dict:
        """
        根据 provider 名称从环境变量解析配置

        Args:
            provider: provider 名称，如 "deepseek", "local_qwen3"

        Returns:
            {"base_url": str, "api_key": str, "model": str}
        """
        normalized_provider = provider.strip().lower()
        provider_upper = normalized_provider.upper()
        base_url = os.getenv(f"{provider_upper}_BASE_URL", "")
        api_key = os.getenv(f"{provider_upper}_API_KEY", "")
        model = os.getenv(f"{provider_upper}_MODEL", "")
        return {
            "provider": normalized_provider,
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
        }

    def _resolve_model_candidate(
        self,
        candidate: str | dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        """将一个候选模型配置解析为完整且独立的供应商配置。

        Args:
            candidate: 供应商名称或直接模型配置。
            source: 配置来源，用于日志和错误说明。

        Returns:
            完整模型配置。

        Raises:
            ModelConfigurationError: 候选配置格式错误或字段不完整。
        """
        if isinstance(candidate, str):
            candidate = {"provider": candidate}
        if not isinstance(candidate, dict):
            raise ModelConfigurationError(f"{source} 必须是供应商名称或字典配置")

        provider = str(candidate.get("provider", "")).strip().lower()
        if provider:
            config = self._resolve_provider_config(provider)
        else:
            config = {
                "provider": str(candidate.get("provider_name", "custom")).strip().lower(),
            }

        for field in ("base_url", "api_key", "model"):
            if field in candidate:
                config[field] = candidate[field]
        config["source"] = source

        provider_upper = config["provider"].upper()
        self._validate_model_config(
            config,
            context=f"候选模型 {source}",
            missing_names={
                "base_url": f"{provider_upper}_BASE_URL 或 base_url",
                "api_key": f"{provider_upper}_API_KEY 或 api_key",
                "model": f"{provider_upper}_MODEL 或 model",
            },
        )
        config["is_ollama"] = self._is_ollama_url(config.get("base_url", ""))
        if config["is_ollama"]:
            config["base_url"] = self._normalize_ollama_url(config["base_url"])
        return config

    def _get_llm_configs_for_report(self, report_code: str) -> list[dict[str, Any]]:
        """获取报告对应的有序模型链。

        报告专属 ``providers`` 会完整覆盖默认模型链；未配置的报告使用
        ``default_models``。旧版单 ``provider`` 和直接连接配置继续兼容。

        Args:
            report_code: 报告类型编码。

        Returns:
            已去重的可用模型配置列表。

        Raises:
            ModelConfigurationError: 配置结构无效或没有任何可用候选模型。
        """
        if report_code in self._model_config_cache:
            return self._model_config_cache[report_code]

        report_models = self._model_config.get("report_models", {})
        if not isinstance(report_models, dict):
            raise ModelConfigurationError("report_models 必须是字典配置")

        candidates: list[str | dict[str, Any]]
        sources: list[str]
        report_config = report_models.get(report_code)
        if report_config is not None:
            if not isinstance(report_config, dict):
                raise ModelConfigurationError(f"report_models.{report_code} 必须是字典配置")
            if "providers" in report_config:
                raw_candidates = report_config["providers"]
                if not isinstance(raw_candidates, list) or not raw_candidates:
                    raise ModelConfigurationError(
                        f"report_models.{report_code}.providers 必须是非空列表"
                    )
                candidates = raw_candidates
                sources = [
                    f"report_models.{report_code}.providers[{index}]"
                    for index in range(len(candidates))
                ]
            else:
                candidates = [report_config]
                suffix = "provider" if report_config.get("provider") else "direct"
                sources = [f"report_models.{report_code}.{suffix}"]
        else:
            raw_defaults = self._model_config.get("default_models")
            if raw_defaults is None:
                candidates = [
                    {
                        "provider": self.provider,
                        "base_url": self.base_url,
                        "api_key": self.api_key,
                        "model": self.model,
                    }
                ]
                sources = ["default_provider"]
            else:
                if not isinstance(raw_defaults, list) or not raw_defaults:
                    raise ModelConfigurationError("default_models 必须是非空列表")
                candidates = raw_defaults
                sources = [f"default_models[{index}]" for index in range(len(candidates))]

        configs: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        configuration_errors: list[str] = []
        for candidate, source in zip(candidates, sources):
            try:
                config = self._resolve_model_candidate(candidate, source=source)
            except ModelConfigurationError as exc:
                # 候选模型彼此独立；某个供应商未配置时允许继续尝试下一候选。
                configuration_errors.append(str(exc))
                print(f"[模型配置] 跳过不可用候选: source={source}, reason=配置不完整")
                continue
            identity = (config["provider"], config["model"])
            if identity in seen:
                continue
            seen.add(identity)
            configs.append(config)

        if not configs:
            detail = "；".join(configuration_errors) or "未配置候选模型"
            raise ModelConfigurationError(f"报告 {report_code} 没有可用模型：{detail}")

        self._model_config_cache[report_code] = configs
        return configs

    def _get_llm_config_for_report(self, report_code: str) -> dict[str, Any]:
        """兼容旧调用方，返回报告模型链中的首个可用模型。"""
        return self._get_llm_configs_for_report(report_code)[0]

    def _format_model_selection(self, report_code: str, llm_config: dict) -> str:
        """格式化不包含密钥和 API 地址的模型路由日志。

        Args:
            report_code: 报告类型编码。
            llm_config: 已解析的模型配置。

        Returns:
            包含真实供应商、模型和来源的日志文本。
        """
        return (
            f"[模型选择] report_code={report_code} "
            f"provider={llm_config.get('provider', '未知')} "
            f"model={llm_config.get('model', '未知')} "
            f"source={llm_config.get('source', '未知')}"
        )

    def _get_llm_client(self, llm_config: dict) -> OpenAI:
        """
        根据配置创建或获取 LLM 客户端

        Args:
            llm_config: LLM 配置字典

        Returns:
            OpenAI 客户端实例
        """
        # 使用配置的 base_url 和 api_key 作为缓存 key
        cache_key = f"{llm_config.get('base_url', '')}|{llm_config.get('api_key', '')}"

        if not hasattr(self, '_llm_client_cache'):
            self._llm_client_cache = {}

        if cache_key not in self._llm_client_cache:
            self._llm_client_cache[cache_key] = OpenAI(
                base_url=llm_config['base_url'],
                api_key=llm_config['api_key'],
                timeout=600.0,
                max_retries=0,
            )

        return self._llm_client_cache[cache_key]

    @staticmethod
    def _log_model_event(job_logger: Any, level: str, message: str, *args: Any) -> None:
        """记录不包含连接地址或密钥的模型重试日志。"""
        if job_logger:
            logger_method = getattr(job_logger, level, None) or getattr(job_logger, "info")
            logger_method(message, *args)
            return
        print(message % args if args else message)

    @staticmethod
    def _get_error_status_code(error: Exception) -> int | None:
        """从 OpenAI/httpx 异常中提取 HTTP 状态码。"""
        status_code = getattr(error, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        response = getattr(error, "response", None)
        response_status = getattr(response, "status_code", None)
        return response_status if isinstance(response_status, int) else None

    def _is_retryable_model_error(self, error: Exception) -> bool:
        """判断当前模型是否值得进行一次短间隔重试。

        认证、欠费、套餐限额和其他 4xx 通常不会在数秒内恢复，因此直接切换模型。
        网络类错误、408 和 5xx 才在当前模型上重试。
        """
        status_code = self._get_error_status_code(error)
        if status_code is not None:
            return status_code == 408 or status_code >= 500
        if isinstance(
            error,
            (
                APIConnectionError,
                APITimeoutError,
                httpx.NetworkError,
                httpx.TimeoutException,
                TimeoutError,
                ConnectionError,
            ),
        ):
            return True
        # 兼容部分 OpenAI 兼容网关抛出的普通运行时异常。
        return not isinstance(error, APIStatusError)

    def _safe_error_summary(self, error: Exception) -> str:
        """生成不会包含请求地址、密钥或响应正文的错误摘要。"""
        status_code = self._get_error_status_code(error)
        status_text = f", status={status_code}" if status_code is not None else ""
        return f"{type(error).__name__}{status_text}"

    def _iter_model_stream(
        self,
        prompt: str,
        llm_config: dict[str, Any],
    ) -> Generator[str, None, None]:
        """执行一次模型流式调用，仅产出文本片段。"""
        if llm_config.get("is_ollama"):
            yield from self._ollama_stream(prompt, llm_config)
            return

        llm_client = self._get_llm_client(llm_config)
        for chunk in llm_client.chat.completions.create(
            model=llm_config["model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            stream=True,
        ):
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    def _call_model_once(
        self,
        prompt: str,
        llm_config: dict[str, Any],
    ) -> str:
        """执行一次非流式模型调用。"""
        if llm_config.get("is_ollama"):
            return self._ollama_chat(prompt, llm_config)

        llm_client = self._get_llm_client(llm_config)
        response = llm_client.chat.completions.create(
            model=llm_config["model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return response.choices[0].message.content

    def _call_model_with_failover(
        self,
        prompt: str,
        llm_configs: list[dict[str, Any]],
        *,
        job_logger: Any = None,
        disabled_providers: set[str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """按模型链执行非流式调用，并在模型故障时重试或降级。"""
        disabled = disabled_providers if disabled_providers is not None else set()
        failures: list[str] = []

        for llm_config in llm_configs:
            provider = llm_config["provider"]
            if provider in disabled:
                continue

            for attempt in range(1, self.max_attempts_per_model + 1):
                self._log_model_event(
                    job_logger,
                    "info",
                    "[模型调用] provider=%s model=%s attempt=%d/%d",
                    provider,
                    llm_config["model"],
                    attempt,
                    self.max_attempts_per_model,
                )
                try:
                    content = self._call_model_once(prompt, llm_config)
                    if not content or not content.strip():
                        raise RuntimeError("模型返回空内容")
                    self._log_model_event(
                        job_logger,
                        "info",
                        "[模型成功] provider=%s model=%s",
                        provider,
                        llm_config["model"],
                    )
                    return content, llm_config
                except Exception as error:
                    summary = self._safe_error_summary(error)
                    failures.append(f"{provider}:{summary}")
                    retryable = self._is_retryable_model_error(error)
                    can_retry = retryable and attempt < self.max_attempts_per_model
                    self._log_model_event(
                        job_logger,
                        "warning",
                        "[模型失败] provider=%s attempt=%d reason=%s action=%s",
                        provider,
                        attempt,
                        summary,
                        "retry" if can_retry else "fallback",
                    )
                    if not can_retry:
                        break
                    if self.retry_backoff_seconds:
                        time.sleep(self.retry_backoff_seconds)

            disabled.add(provider)

        failure_summary = "; ".join(failures) or "没有可调用的候选模型"
        raise ReportModelExhaustedError(f"报告模型链全部失败：{failure_summary}")

    def _stream_model_with_failover(
        self,
        prompt: str,
        llm_configs: list[dict[str, Any]],
        *,
        job_logger: Any = None,
        disabled_providers: set[str] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """原子化执行流式模型链。

        每次尝试先在后台线程缓冲完整内容。成功后才返回全部片段；失败片段会被
        丢弃。主线程在等待期间持续产出 heartbeat 事件。
        """
        disabled = disabled_providers if disabled_providers is not None else set()
        failures: list[str] = []

        for llm_config in llm_configs:
            provider = llm_config["provider"]
            if provider in disabled:
                continue

            for attempt in range(1, self.max_attempts_per_model + 1):
                self._log_model_event(
                    job_logger,
                    "info",
                    "[模型调用] provider=%s model=%s attempt=%d/%d",
                    provider,
                    llm_config["model"],
                    attempt,
                    self.max_attempts_per_model,
                )
                result_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

                def stream_worker() -> None:
                    """在后台消费一次模型流，避免等待期间阻塞 SSE 心跳。"""
                    try:
                        for chunk in self._iter_model_stream(prompt, llm_config):
                            result_queue.put(("content", chunk))
                        result_queue.put(("done", None))
                    except Exception as error:
                        result_queue.put(("error", error))

                worker = threading.Thread(target=stream_worker, daemon=True)
                worker.start()
                buffered_chunks: list[str] = []
                last_heartbeat = time.monotonic()
                failure: Exception | None = None

                while worker.is_alive() or not result_queue.empty():
                    try:
                        event_type, payload = result_queue.get(timeout=0.5)
                    except queue.Empty:
                        event_type, payload = "", None

                    if event_type == "content":
                        buffered_chunks.append(payload)
                    elif event_type == "error":
                        failure = payload
                        break
                    elif event_type == "done":
                        break

                    now = time.monotonic()
                    if now - last_heartbeat >= self.heartbeat_interval_seconds:
                        yield {"event": "heartbeat"}
                        last_heartbeat = now

                worker.join(timeout=0.1)
                if failure is None and not "".join(buffered_chunks).strip():
                    failure = RuntimeError("模型返回空内容")

                if failure is None:
                    self._log_model_event(
                        job_logger,
                        "info",
                        "[模型成功] provider=%s model=%s",
                        provider,
                        llm_config["model"],
                    )
                    yield {
                        "event": "success",
                        "chunks": buffered_chunks,
                        "llm_config": llm_config,
                    }
                    return

                summary = self._safe_error_summary(failure)
                failures.append(f"{provider}:{summary}")
                retryable = self._is_retryable_model_error(failure)
                can_retry = retryable and attempt < self.max_attempts_per_model
                self._log_model_event(
                    job_logger,
                    "warning",
                    "[模型失败] provider=%s attempt=%d reason=%s action=%s",
                    provider,
                    attempt,
                    summary,
                    "retry" if can_retry else "fallback",
                )
                if not can_retry:
                    break
                if self.retry_backoff_seconds:
                    time.sleep(self.retry_backoff_seconds)

            disabled.add(provider)

        failure_summary = "; ".join(failures) or "没有可调用的候选模型"
        raise ReportModelExhaustedError(f"报告模型链全部失败：{failure_summary}")

    def _is_ollama_url(self, url: str) -> bool:
        """检测 URL 是否为 Ollama 服务（仅通过端口判断，不受 OLLAMA_NATIVE_API 影响）"""
        return "11434" in (url or "")

    def _is_ollama(self) -> bool:
        """检测是否为 Ollama 模型（仅通过 provider 或端口判断）"""
        provider = os.getenv("PROVIDER", "").lower()
        return "ollama" in provider or "11434" in (self.base_url or "")

    def _normalize_ollama_url(self, url: str) -> str:
        """修正 Ollama base_url，确保包含 /v1 后缀用于 OpenAI 兼容端点"""
        if url and not url.rstrip("/").endswith("/v1"):
            return url.rstrip("/") + "/v1"
        return url

    def _get_ollama_base_url(self, base_url: str = None) -> str:
        """获取 Ollama 原生 API 的 base_url（去掉 /v1 后缀）

        Args:
            base_url: 可选，指定的 base_url，为 None 时使用 self.base_url

        Returns:
            Ollama 原生 API 地址，如 http://10.1.1.5:11434
        """
        url = (base_url or self.base_url or "").rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        return url

    def _ollama_chat(self, prompt: str, llm_config: dict = None) -> str:
        """Ollama 原生非流式调用 /api/chat

        Args:
            prompt: 提示词
            llm_config: 可选，LLM 配置字典，为 None 时使用默认配置

        Returns:
            生成的文本内容
        """
        model = llm_config.get('model', self.model) if llm_config else self.model
        base_url = llm_config.get('base_url') if llm_config else None

        think = llm_config.get('think', False) if llm_config else False

        url = f"{self._get_ollama_base_url(base_url)}/api/chat"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": think,
            "options": {"temperature": 0.2}
        }
        logger.debug("[Ollama] 原生 API 非流式调用: %s model=%s", url, model)

        with httpx.Client(timeout=600.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "")

    def _ollama_stream(self, prompt: str, llm_config: dict = None) -> Generator[str, None, None]:
        """Ollama 原生流式调用 /api/chat

        Args:
            prompt: 提示词
            llm_config: 可选，LLM 配置字典，为 None 时使用默认配置

        Yields:
            生成的文本片段
        """
        model = llm_config.get('model', self.model) if llm_config else self.model
        base_url = llm_config.get('base_url') if llm_config else None

        think = llm_config.get('think', False) if llm_config else False

        url = f"{self._get_ollama_base_url(base_url)}/api/chat"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "think": think,
            "options": {"temperature": 0.2}
        }
        logger.debug("[Ollama] 原生 API 流式调用: %s model=%s", url, model)

        with httpx.Client(timeout=600.0) as client:
            with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if "message" in data and "content" in data["message"]:
                                yield data["message"]["content"]
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            logger.warning("[Ollama] 返回非 JSON 行: %s", line[:100])

    def generate_reports(
        self,
        data: dict,
        report_code: str,
        config_path: str = None,
        parallel: bool = True,
        job_logger=None
    ) -> List[Dict]:
        """
        根据报告配置生成多份报告（非流式）

        Args:
            data: 原始数据
            report_code: 报告代码（如 leanQualityWeekReport）
            config_path: 配置文件路径
            parallel: 是否并行生成（默认为 True）

        Returns:
            报告列表，每个报告包含：
                {
                    'output_name': 报告名称,
                    'template': 模板文件名,
                    'content': 报告内容'
                }
        """
        # 加载配置
        templates_config = self._load_report_config(config_path)
        report_entry = templates_config['report_mapping'].get(report_code, [])
        if isinstance(report_entry, dict):
            templates = report_entry.get('templates', [])
        else:
            templates = report_entry

        if not templates:
            raise ValueError(f"未找到 reportCode={report_code} 的配置")

        # 获取当前报告类型的模型配置
        llm_configs = self._get_llm_configs_for_report(report_code)
        llm_config = llm_configs[0]

        log = job_logger.info if job_logger else print

        log(f"\n{'='*60}")
        log(f"[报告生成] 共 {len(templates)} 份报告待生成")
        log(self._format_model_selection(report_code, llm_config))
        log(f"[报告生成] 并行模式: {'启用' if parallel else '禁用'}")
        if parallel:
            log(f"[报告生成] 最大并发数: {self.max_workers}")
        log(f"{'='*60}")

        results = []

        if parallel and len(templates) > 1:
            # 并行生成
            results = self._generate_reports_parallel(data, templates, job_logger, llm_configs)
        else:
            # 串行生成
            results = self._generate_reports_sequential(data, templates, job_logger, llm_configs)

        return results

    def generate_reports_stream(
        self,
        data: dict,
        report_code: str,
        config_path: str = None,
        job_logger=None,
        preprocessed_data_json: str = None,
        template_limit: int = None,
    ) -> Generator[dict, None, None]:
        """
        流式生成多份报告
        支持 context_from_index 依赖链：后续报告可使用前序报告输出作为上下文
        支持 use_raw_data 控制是否注入原始数据

        Args:
            data: 原始数据
            report_code: 报告代码（如 leanQualityWeekReport）
            config_path: 配置文件路径
            job_logger: 作业日志器实例
            preprocessed_data_json: 预处理后的数据 JSON（clean + map-reduce）。传了则跳过内部重复计算

        Yields:
            流式事件，格式：
            {
                'event': 'start' | 'report_start' | 'content' | 'report_end' | 'end',
                'report_name': 报告名称（report_start/report_end 事件）,
                'template': 模板文件名,
                'content': 内容块（content 事件）,
                'total': 完整内容（report_end 事件）,
                'index': 报告索引（0, 1, 2...）,
                'count': 总报告数
            }
        """
        # 加载配置
        templates_config = self._load_report_config(config_path)
        report_entry = templates_config['report_mapping'].get(report_code, [])
        if isinstance(report_entry, dict):
            templates = report_entry.get('templates', [])
        else:
            templates = report_entry

        if not templates:
            raise ValueError(f"未找到 reportCode={report_code} 的配置")

        total_count = len(templates)

        # 获取当前报告类型的模型配置
        llm_configs = self._get_llm_configs_for_report(report_code)
        llm_config = llm_configs[0]

        if job_logger:
            job_logger.info("")
            job_logger.info("=" * 60)
            job_logger.info("[报告生成] 共 %d 份报告待生成", total_count)
            job_logger.info(self._format_model_selection(report_code, llm_config))
            if llm_config.get('is_ollama'):
                job_logger.info("[报告生成] 模型类型: Ollama")
            job_logger.info("=" * 60)

        # 发送开始事件
        yield {
            'event': 'start',
            'count': total_count
        }

        # 已完成报告的输出内容（按 index 存储），供后续报告作为上下文
        report_outputs = {}
        # 当前任务内发生最终失败的供应商不再为后续子报告重复调用。
        disabled_providers: set[str] = set()

        for index, template_config in enumerate(templates):
            # 如果设置了模板数量限制，达到上限后停止
            if template_limit is not None and index >= template_limit:
                break

            output_name = template_config['output_name']
            template_file = template_config['template']
            use_ragflow = template_config.get('use_ragflow', False)
            use_raw_data = template_config.get('use_raw_data', True)
            context_from_index = template_config.get('context_from_index', None)
            use_all_workshop_reports = template_config.get('use_all_workshop_reports', False)
            use_historical_context = template_config.get('use_historical_context', False)

            # 报告开始事件
            yield {
                'event': 'report_start',
                'report_name': output_name,
                'template': template_file,
                'index': index,
                'count': total_count,
                'use_ragflow': use_ragflow
            }

            try:
                if job_logger:
                    job_logger.info("")
                    job_logger.info("[报告 %d/%d] 开始生成: %s", index + 1, total_count, output_name)
                    job_logger.info("  配置: use_raw_data=%s, use_ragflow=%s, use_historical_context=%s, context_from_index=%s",
                        use_raw_data, use_ragflow, use_historical_context, context_from_index)

                # 获取前序报告上下文（串行模式下直接读取）
                context = None
                if context_from_index is not None:
                    context = report_outputs.get(context_from_index, "")
                    if job_logger:
                        job_logger.info("  前序报告上下文: 第%d份, 长度=%d字符", context_from_index + 1, len(context))

                # 加载模板并分离关键词提取提示词和报告生成提示词
                template_content = self._load_template(template_file)
                keyword_prompt, report_prompt = self._split_template(template_content)

                full_content = ""
                citations = []

                # ========================================
                # 构建提示词
                # ========================================
                log = job_logger.info if job_logger else (lambda m, *a: logger.info(m, *a))

                log("  上下文: %s", "有(%d字符)" % (len(context),) if context else "无")

                if use_raw_data:
                    if preprocessed_data_json:
                        # 调用方已预处理过，直接复用，解析后输出关键统计
                        data_json = preprocessed_data_json
                        try:
                            parsed = json.loads(preprocessed_data_json)
                            resp = parsed.get("response", []) if isinstance(parsed, dict) else []
                            sk_list = [item.get("sourceKey", "?") for item in resp if isinstance(item, dict)]
                            prepped = [
                                item.get("sourceKey", "?") for item in resp
                                if isinstance(item, dict) and isinstance(item.get("data"), dict)
                                and item["data"].get("_preprocessed")
                            ]
                            log("  [预处理] 复用调用方数据: JSON=%d字符, sourceKey数=%d, 已预处理=%d(%s)",
                                len(preprocessed_data_json), len(sk_list), len(prepped),
                                ", ".join(prepped) if prepped else "无")
                        except Exception:
                            log("  [预处理] 使用调用方传入的预处理数据")
                    else:
                        # 预处理统计
                        raw_json_before = json.dumps(data, ensure_ascii=False, indent=2)
                        response_list_raw = data.get("response", []) if isinstance(data, dict) else []
                        source_keys_before = [
                            item.get("sourceKey") for item in response_list_raw
                            if isinstance(item, dict) and "sourceKey" in item
                        ]
                        excluded_in_data = [
                            sk for sk in source_keys_before
                            if any(sk.startswith(prefix) for prefix in EXCLUDED_SOURCE_KEY_PREFIXES)
                        ]

                        cleaned_data = clean_raw_data(data)
                        after_clean = len(json.dumps(cleaned_data, ensure_ascii=False, indent=2))

                        # 数据预处理：对配置了预处理器的 sourceKey 执行 map-reduce 变换
                        response_list = cleaned_data.get("response", [])
                        prepped_names: list = []
                        preprocessed_count = 0
                        if isinstance(response_list, list):
                            from backend.utils.data_preprocessor import preprocess_sources
                            preprocess_sources(response_list)
                            prepped_names = [
                                item.get("sourceKey", "?") for item in response_list
                                if isinstance(item, dict) and isinstance(item.get("data"), dict)
                                and item["data"].get("_preprocessed")
                            ]
                            preprocessed_count = len(prepped_names)

                        data_json = json.dumps(cleaned_data, ensure_ascii=False, indent=2)
                        after_reduce = len(data_json)

                        source_keys_after = [
                            item.get("sourceKey") for item in cleaned_data.get("response", [])
                            if isinstance(item, dict) and "sourceKey" in item
                        ] if isinstance(cleaned_data, dict) else []
                        reduction_pct = (1 - after_reduce / len(raw_json_before)) * 100 if raw_json_before else 0

                        log("  [预处理] 原始=%d → 清洗后=%d(-空值&过滤sourceKey) → reduce后=%d 字符 (总缩减 %.1f%%)",
                            len(raw_json_before), after_clean, after_reduce, reduction_pct)
                        log("  [预处理] sourceKey: %d → %d 个, map-reduce: %d 个 (%s)",
                            len(source_keys_before), len(source_keys_after), preprocessed_count,
                            ", ".join(prepped_names) if prepped_names else "无")
                        if excluded_in_data:
                            log("  [预处理] 已过滤 sourceKey: %s", excluded_in_data)

                    prompt = report_prompt.replace('{data_sources}', data_json)
                elif use_all_workshop_reports and isinstance(data, dict) and 'allWorkshopReports' in data:
                    workshop_reports = data['allWorkshopReports']
                    workshop_reports_str = self._format_workshop_reports_for_prompt(workshop_reports)
                    prompt = report_prompt.replace('{data_sources}', workshop_reports_str)
                else:
                    prompt = report_prompt.replace('{data_sources}', context or '')

                # 替换其他占位符
                for placeholder in ('{context_report}', '{historical_reports}', '{rag_results}'):
                    if placeholder in prompt:
                        prompt = prompt.replace(placeholder, context or '')

                # 注入临时规则（从 config/temporary_rules.yaml 加载）
                temporary_rules = self._load_temporary_rules(report_code)
                if temporary_rules:
                    if '{temporary_rules}' in prompt:
                        # 模板中有占位符，替换到对应位置
                        prompt = prompt.replace('{temporary_rules}', temporary_rules)
                    else:
                        # 模板中没有占位符，追加到提示词末尾
                        prompt = """{}

### 临时规则（必须严格遵守）
{}""".format(prompt, temporary_rules)
                    if job_logger:
                        job_logger.info("  临时规则: 已注入 %d 字符", len(temporary_rules))

                # 注入历史报告上下文（第2份报告用于趋势对比）
                if use_historical_context and isinstance(data, dict):
                    historical_context = data.get('meta', {}).get('historicalContext', '') if isinstance(data.get('meta'), dict) else ''
                    if historical_context:
                        prompt = """{}

# 历史报告参考（以下为近期AI生成的报告，用于趋势对比，严禁引用其引用脚标）
{}""".format(prompt, historical_context)

                # 知识库检索与引用注入（仅 use_ragflow=true 时）
                if use_ragflow:
                    ragflow_client = get_ragflow_client()

                    search_strategy = "模板关键词" if (keyword_prompt and context) else "默认构建"
                    if keyword_prompt and context:
                        search_query = self._extract_keywords_with_llm(keyword_prompt, context, data, llm_config)
                    else:
                        search_query = self._build_search_query(data, context, llm_config)

                    # 检查 search_query 是否为空
                    if not search_query:
                        if job_logger:
                            job_logger.warning("  知识库检索: 检索查询为空，跳过检索")
                        search_query = "质量检验数据"  # 使用默认查询
                        if job_logger:
                            job_logger.info("  知识库检索: 使用默认查询: %s", search_query)

                    if job_logger:
                        job_logger.info("  知识库检索: 策略=%s, 查询=%s",
                                        search_strategy,
                                        search_query[:100] + ("..." if len(search_query) > 100 else ""))

                    if context and len(context) > 100:
                        retrieved_chunks = self._retrieve_combined(
                            search_query=search_query,
                            report_content=context,
                            ragflow_client=ragflow_client,
                            top_k=5,
                            similarity_threshold=0.2,
                            job_logger=job_logger
                        )
                    else:
                        retrieved_chunks = ragflow_client.retrieve(
                            question=search_query,
                            page_size=10,
                            similarity_threshold=0.2,
                            job_logger=job_logger
                        )
                        retrieved_chunks = [c for c in retrieved_chunks if c.get('similarity', 0) >= 0.2]
                        if len(retrieved_chunks) > 5:
                            retrieved_chunks = retrieved_chunks[:5]

                    if retrieved_chunks:
                        for idx, chunk in enumerate(retrieved_chunks, 1):
                            citation = {
                                "id": idx,
                                "content": chunk["content"],
                                "source": chunk["document_name"],
                                "similarity": chunk["similarity"],
                                "document_id": chunk.get("document_id", ""),
                                "dataset_id": chunk.get("dataset_id", ""),
                                "positions": chunk.get("positions", []),
                                "docnm": chunk.get("docnm", chunk["document_name"])
                            }
                            citations.append(citation)

                        knowledge_context = self._format_knowledge_context(retrieved_chunks)
                        prompt = self._inject_citation_prompt(prompt, knowledge_context, len(retrieved_chunks))
                        if job_logger:
                            job_logger.info("  知识库检索结果: %d 个知识块", len(retrieved_chunks))
                            for i, cite in enumerate(citations[:3]):
                                job_logger.info("    [%d] %s (相似度: %.3f)", i+1, cite['source'], cite['similarity'])
                    else:
                        if job_logger:
                            job_logger.info("  ⚠️  知识库未检索到相关内容")

                    if context:
                        prompt = """{}

# 背景信息（以下内容为上一阶段AI生成的报告，仅作背景参考，严禁引用）
{}""".format(prompt, context)

                if job_logger:
                    job_logger.info("  提示词总长度: %d 字符", len(prompt))

                # ========================================
                # LLM 流式生成
                # ========================================
                if job_logger:
                    job_logger.info("[报告 %d/%d] 开始调用 LLM 生成...", index + 1, total_count)

                successful_config = None
                for model_event in self._stream_model_with_failover(
                    prompt,
                    llm_configs,
                    job_logger=job_logger,
                    disabled_providers=disabled_providers,
                ):
                    if model_event["event"] == "heartbeat":
                        # 路由层会把内部 heartbeat 转换成现有 SSE 注释心跳。
                        yield model_event
                        continue

                    successful_config = model_event["llm_config"]
                    for content in model_event["chunks"]:
                        full_content += content
                        yield {
                            "event": "content",
                            "content": content,
                            "index": index,
                            "count": total_count,
                        }

                if successful_config is None:
                    raise ReportModelExhaustedError("报告模型链未返回成功结果")
                llm_config = successful_config

                if job_logger:
                    job_logger.info("[报告 %d/%d] 生成完成，长度: %d 字符", index + 1, total_count, len(full_content))

                # 保存当前报告输出，供后续报告作为上下文
                report_outputs[index] = full_content

                # 后处理
                full_content = self._expand_citation_ranges(full_content)
                full_content = self._filter_base_report_citations(full_content)
                # 更新 report_outputs 为后处理后的内容
                report_outputs[index] = full_content

                # 发送 citations 事件
                if citations:
                    yield {
                        'event': 'citations',
                        'citations': citations,
                        'index': index,
                        'count': total_count
                    }

                # 发送报告完成事件
                yield {
                    'event': 'report_end',
                    'report_name': output_name,
                    'template': template_file,
                    'total': full_content,
                    'index': index,
                    'count': total_count,
                    'citations': citations,
                    'use_ragflow': use_ragflow
                }

                if job_logger:
                    job_logger.info("")
                    job_logger.info("=" * 70)
                    job_logger.info("[完成] 报告 %d/%d 完成: %s", index + 1, total_count, output_name)
                    job_logger.info("[完成] 报告内容长度: %d 字符", len(full_content))
                    job_logger.info("")
                    job_logger.info("  ┌─────────────────────────────────────────────┐")
                    job_logger.info("  │              报告内容                       │")
                    job_logger.info("  └─────────────────────────────────────────────┘")
                    display_content = full_content[:2000] + ("..." if len(full_content) > 2000 else "")
                    for line in display_content.split('\n'):
                        job_logger.info("  %s", line)
                    job_logger.info("")
                    job_logger.info("=" * 70)
                    job_logger.info("")

            except Exception as e:
                import traceback
                if job_logger:
                    job_logger.error("[报告 %d/%d] 生成失败: %s\n%s", index + 1, total_count, e, traceback.format_exc())
                else:
                    traceback.print_exc()

                # 失败时保存空内容，避免后续报告无限等待
                report_outputs[index] = ""

                yield {
                    'event': 'error',
                    'report_name': output_name,
                    'error': str(e),
                    'index': index,
                    'count': total_count
                }

                # fail-fast：一份报告失败即停止后续生成（后续报告可能依赖前序输出）
                remaining = total_count - index - 1
                if remaining > 0:
                    if job_logger:
                        job_logger.warning(
                            "[fail-fast] 第 %d 份报告失败，跳过剩余 %d 份报告",
                            index + 1, remaining
                        )
                break

        # 发送结束事件
        yield {
            'event': 'end'
        }

    def generate_report_with_citation(
        self,
        data: dict,
        template_file: str,
        context: str = None,
        use_ragflow: bool = False,
        job_logger=None,
        llm_config: dict | list[dict[str, Any]] = None,
        disabled_providers: set[str] | None = None,
    ) -> Dict:
        """
        生成带引用的报告

        当 use_ragflow=True 时：
        1. 调用 RAGFlow 检索接口获取相关知识块
        2. 将检索结果格式化为上下文，传给 LLM
        3. 在提示词中要求 LLM 使用 [数字] 格式的脚标标记引用
        4. 返回报告内容 + 引用列表

        Args:
            data: 原始数据
            template_file: 模板文件名
            context: 上下文（第一份报告内容）
            use_ragflow: 是否使用 RAGFlow 检索

        Returns:
            包含报告内容和引用信息的字典：
            {
                "content": "报告内容（带脚标）",
                "citations": [
                    {
                        "id": 1,
                        "content": "引用的原文内容",
                        "source": "来源文档名称",
                        "similarity": 0.85
                    }
                ]
            }
        """
        log = job_logger.info if job_logger else print

        # ========================================
        # 加载模板并构建提示词
        # ========================================
        log(f"\n{'='*70}")
        log(f"[单报告] 开始构建提示词")
        log(f"{'='*70}")
        log(f"  use_ragflow: {use_ragflow}")
        log(f"  有上下文: {'是' if context else '否'}")
        log(f"  有历史上下文: {'是' if (isinstance(data, dict) and data.get('meta', {}).get('historicalContext')) else '否'}")

        # 加载模板并分离关键词提取提示词和报告生成提示词
        template_content = self._load_template(template_file)
        keyword_prompt, report_prompt = self._split_template(template_content)

        # 构建基础提示词
        data_json = json.dumps(data, ensure_ascii=False, indent=2)
        prompt = report_prompt.replace('{data_sources}', data_json)
        logger.debug("[报告生成] 原始数据长度: %d 字符", len(data_json))

        citations = []

        if use_ragflow:
            # 使用 RAGFlow 检索接口
            ragflow_client = get_ragflow_client()

            # 构建检索查询：优先使用模板中的关键词提取提示词
            if keyword_prompt and context:
                logger.debug("[报告生成] 使用模板关键词提取提示词")
                search_query = self._extract_keywords_with_llm(keyword_prompt, context, data, llm_config)
            else:
                search_query = self._build_search_query(data, context, llm_config)

            # 并行检索：关键词检索 + 语义检索
            if context and len(context) > 100:
                log("[报告生成] 使用并行检索策略（关键词 + 语义）")
                retrieved_chunks = self._retrieve_combined(
                    search_query=search_query,
                    report_content=context,
                    ragflow_client=ragflow_client,
                    top_k=5,
                    similarity_threshold=0.2,
                    job_logger=job_logger
                )
            else:
                # 调用检索接口
                retrieved_chunks = ragflow_client.retrieve(
                    question=search_query,
                    page_size=10,
                    similarity_threshold=0.2,
                    job_logger=job_logger
                )

            # 过滤低质量结果，只保留相似度 >= 0.2 的知识块
            retrieved_chunks = [c for c in retrieved_chunks if c.get('similarity', 0) >= 0.2]
            if len(retrieved_chunks) > 5:
                retrieved_chunks = retrieved_chunks[:5]

            if retrieved_chunks:
                # 格式化检索结果为上下文
                knowledge_context = self._format_knowledge_context(retrieved_chunks)

                # 构建引用列表（包含文档下载和定位所需信息）
                for idx, chunk in enumerate(retrieved_chunks, 1):
                    citation = {
                        "id": idx,
                        "content": chunk["content"],
                        "source": chunk["document_name"],
                        "similarity": chunk["similarity"],
                        # 以下字段用于文档下载和定位
                        "document_id": chunk.get("document_id", ""),
                        "dataset_id": chunk.get("dataset_id", ""),
                        "positions": chunk.get("positions", []),
                        "docnm": chunk.get("docnm", chunk["document_name"])
                    }
                    citations.append(citation)

                # 将知识上下文和引用规则注入提示词
                prompt = self._inject_citation_prompt(prompt, knowledge_context, len(retrieved_chunks))

                logger.info("[报告生成] 检索到 %d 个知识块，已注入提示词", len(retrieved_chunks))
            else:
                logger.info("[报告生成] 未检索到相关知识块，使用普通 LLM 生成")

        # 如果有上下文（第一份报告），添加到提示词末尾作为背景参考
        if context:
            prompt = """{}

# 背景信息（以下内容为上一阶段AI生成的报告，仅作背景参考，严禁引用）
【基础质量周报】
{}""".format(prompt, context)

        # 如果有上下文（第一份报告），添加到提示词末尾作为背景参考
        if context:
            prompt = """{}

# 背景信息（以下内容为上一阶段AI生成的报告，仅作背景参考，严禁引用）
【基础质量周报】
{}""".format(prompt, context)
            logger.debug("[报告生成] 添加背景上下文: %d 字符", len(context))

        # 如果有历史报告上下文（从 SQLite 加载），追加到提示词供趋势对比
        historical_context = None
        if isinstance(data, dict):
            meta = data.get('meta', {})
            if isinstance(meta, dict):
                historical_context = meta.get('historicalContext', '')
        if historical_context:
            prompt = """{}

# 历史报告参考（以下为上一期AI生成的报告，用于趋势对比，严禁引用其引用脚标）
【上一期基础报告】
{}""".format(prompt, historical_context)
            logger.debug("[报告生成] 添加历史上下文: %d 字符", len(historical_context))

        logger.debug("[报告生成] 知识库检索: %d 个知识块", len(citations))
        for i, cite in enumerate(citations[:3]):
            logger.debug("[报告生成]   [%d] %s (相似度: %.3f)", i + 1, cite['source'], cite['similarity'])

        logger.debug("[报告生成] 最终提示词总长度: %d 字符", len(prompt))

        if isinstance(llm_config, list):
            llm_configs = llm_config
        elif llm_config:
            llm_configs = [llm_config]
        else:
            llm_configs = [{
                "provider": self.provider,
                "base_url": self.base_url,
                "api_key": self.api_key,
                "model": self.model,
                "is_ollama": self._is_ollama(),
                "source": "default_provider",
            }]

        # 调用 LLM 生成报告
        logger.info("[单报告] 开始调用 LLM 生成...")
        content, _ = self._call_model_with_failover(
            prompt,
            llm_configs,
            job_logger=job_logger,
            disabled_providers=disabled_providers,
        )
        content = self._expand_citation_ranges(content)
        content = self._filter_base_report_citations(content)

        return {
            "content": content,
            "citations": citations
        }

    def _split_template(self, template_content: str) -> tuple:
        """
        将模板内容分离为关键词提取提示词和报告生成提示词

        格式约定：
        =====KEYWORD_EXTRACTION=====
        ...关键词提取提示词...
        =====REPORT_GENERATION=====
        ...报告生成提示词...

        如果不包含分隔标记，则返回 (None, template_content)
        """
        marker_keyword = "=====KEYWORD_EXTRACTION====="
        marker_report = "=====REPORT_GENERATION====="

        if marker_keyword in template_content and marker_report in template_content:
            parts = template_content.split(marker_report, 1)
            keyword_part = parts[0].replace(marker_keyword, "").strip()
            report_part = parts[1].strip()
            return keyword_part, report_part

        return None, template_content

    def _build_search_query(self, data: dict, context: str = None, llm_config: dict = None) -> str:
        """
        从原始数据和上下文中提取检索关键词

        策略：
        1. 优先使用 LLM 对第一份报告进行总结，提取关键信息作为检索关键词
        2. 如果没有上下文或 LLM 调用失败，则回退到基于数据的关键词提取

        Args:
            data: 原始数据
            context: 上下文（第一份报告内容）
            llm_config: 可选，LLM 配置字典

        Returns:
            检索关键词
        """
        # 如果有上下文（第一份报告），使用 LLM 提取关键检索词
        if context and len(context) > 100:
            try:
                search_query = self._extract_keywords_with_llm(None, context, data, llm_config)
                if search_query:
                    logger.debug("[检索查询] 使用 LLM 提取的关键词: %s...", search_query[:200])
                    return search_query
            except Exception as e:
                logger.warning("[检索查询] LLM 提取关键词失败，回退到基础提取: %s", e)

        # 极简回退：只用 meta 基础信息，不从原数据中提取工序/检验项
        parts = []
        meta = data.get('meta', {})
        if meta.get('period'):
            parts.append(f"日期:{meta['period']}")
        if meta.get('qualifiedType'):
            parts.append(f"合格类型:{meta['qualifiedType']}")
        fallback = ' '.join(parts)
        logger.debug("[检索查询] 极简回退: %s", fallback if fallback else '质量检验数据')
        return fallback if fallback else "质量检验数据"

    def _extract_keywords_with_llm(self, keyword_prompt: str, report_content: str, data: dict, llm_config: dict = None) -> str:
        """
        使用 LLM 从报告内容中提取关键检索词

        Args:
            keyword_prompt: 关键词提取提示词模板（若为 None 则使用默认模板）
            report_content: 第一份报告的内容
            data: 原始数据
            llm_config: 可选，LLM 配置字典，为 None 时使用默认配置

        Returns:
            提取的检索关键词，失败返回 None
        """
        # 使用配置的模型或默认模型
        if llm_config:
            model = llm_config.get('model', self.model)
            llm_client = self._get_llm_client(llm_config)
        else:
            model = self.model
            llm_client = self.llm

        # 构建提取关键词的提示词
        if keyword_prompt:
            # 使用模板中提供的关键词提取提示词
            extract_prompt = keyword_prompt.replace('{report_content}', report_content[:2000])
        else:
            # 使用默认的关键词提取提示词
            extract_prompt = """你是一个数据分析助手。请从以下质量报告中提取关键信息，用于知识库检索。

要求：
1. 提取报告中提到的关键问题、异常工序、不合格检验项
2. 提取改进建议和措施
3. 输出格式：用空格分隔的关键词，每个关键词2-4个字
4. 不要输出标点符号和多余文字
5. 关键词数量控制在10-15个

报告内容（前2000字）：
{}

请直接输出关键词（用空格分隔）：""".format(report_content[:2000])

        # 调用 LLM 提取关键词
        response = llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": extract_prompt}],
            temperature=0.2
        )
        keywords = response.choices[0].message.content.strip()

        # 清理关键词
        # 移除可能的标点符号和多余文字
        keywords = keywords.replace('，', ' ').replace('。', ' ').replace('、', ' ')
        keywords = keywords.replace(',', ' ').replace('.', ' ').replace('：', ' ')
        keywords = keywords.replace(':', ' ').replace('；', ' ').replace(';', ' ')

        # 移除多余空格
        keywords = ' '.join(keywords.split())

        return keywords if keywords else None

    def _retrieve_with_segmentation(
        self,
        report_content: str,
        data: dict,
        ragflow_client,
        top_k: int = 5,
        similarity_threshold: float = 0.2,
        segment_by: str = 'paragraph'
    ) -> list:
        """
        分段检索策略：将报告内容分段，每段独立检索，合并去重
        参考 report-agent/demon/backend.py 的实现

        Args:
            report_content: 第一份报告的内容
            data: 原始数据
            ragflow_client: RAGFlow 客户端
            top_k: 每段返回的最大结果数
            similarity_threshold: 相似度阈值
            segment_by: 分段方式 ('paragraph' 或 'sentence')

        Returns:
            合并后的检索结果列表
        """
        # 根据分段方式分割报告内容
        if segment_by == 'sentence':
            # 按句子分段
            import re
            segments = re.split(r'[。！？.!?]', report_content)
            segments = [s.strip() for s in segments if s.strip()]
        else:
            # 按段落分段（默认）
            segments = report_content.split('\n')
            segments = [s.strip() for s in segments if s.strip()]

        logger.debug("[分段检索] 报告内容分为 %d 段", len(segments))

        # 收集所有检索结果
        all_chunks = []

        for idx, segment in enumerate(segments):
            # 跳过太短的段落（少于20字符）
            if len(segment) < 20:
                continue

            logger.debug("[分段检索] 检索第 %d/%d 段: %s...", idx + 1, len(segments), segment[:50])

            try:
                # 直接用段落内容作为检索问题（参考 backend.py 的实现）
                chunks = ragflow_client.retrieve(
                    question=segment,
                    page_size=5,
                    similarity_threshold=similarity_threshold
                )

                if chunks:
                    all_chunks.extend(chunks)
                    logger.debug("[分段检索] 找到 %d 个相关块", len(chunks))

            except Exception as e:
                logger.warning("[分段检索] 检索段落失败: %s", e)
                continue

        logger.debug("[分段检索] 总共找到 %d 个相关块", len(all_chunks))

        # 去重（按 chunk_id 去重）
        unique_chunks_dict = {}
        for chunk in all_chunks:
            chunk_id = chunk.get('chunk_id')
            if chunk_id and chunk_id not in unique_chunks_dict:
                unique_chunks_dict[chunk_id] = chunk
        unique_chunks = list(unique_chunks_dict.values())
        logger.debug("[分段检索] 去重后剩下 %d 个块", len(unique_chunks))

        # 过滤低相似度结果
        unique_chunks = [c for c in unique_chunks if c.get('similarity', 0) >= similarity_threshold]
        logger.debug("[分段检索] 过滤低质量后剩下 %d 个块", len(unique_chunks))

        # 按相似度排序，取 top_k 个
        unique_chunks.sort(key=lambda x: x.get('similarity', 0), reverse=True)
        final_chunks = unique_chunks[:top_k]

        logger.debug("[分段检索] 最终返回 %d 个知识块", len(final_chunks))
        return final_chunks

    def _retrieve_semantic(
        self,
        report_content: str,
        ragflow_client,
        top_k: int = 5,
        similarity_threshold: float = 0.2,
        job_logger=None
    ) -> list:
        """
        语义检索策略：取报告前 1000 字符作为查询，进行纯向量语义检索。

        使用全文的前 1000 字符（覆盖结论 + 核心问题）作为查询文本，
        调用 RAGFlow 纯向量检索，召回更精准的相关知识块。

        Args:
            report_content: 报告内容（取前 1000 字符作为查询）
            ragflow_client: RAGFlow 客户端
            top_k: 返回的最大结果数
            similarity_threshold: 相似度阈值
            job_logger: 作业日志器

        Returns:
            检索结果列表
        """
        log = job_logger.info if job_logger else print

        # 取报告前 1000 字符作为查询，覆盖结论和核心问题
        query_text = report_content[:1000].strip()
        log(f"[语义检索] 查询文本长度: {len(query_text)} 字符")
        log("")
        log("  ┌─────────────────────────────────────────────┐")
        log("  │         语义检索 - 查询文本                   │")
        log("  └─────────────────────────────────────────────┘")
        for line in query_text.split('\n'):
            log(f"  {line}")
        log("")

        try:
            # 纯向量语义检索：vector_similarity_weight=1.0, keyword=False
            log(f"[语义检索] 调用 RAGFlow 检索...")
            log(f"  page_size: 10")
            log(f"  similarity_threshold: {similarity_threshold}")
            log(f"  vector_similarity_weight: 1.0")
            log(f"  keyword: False")
            log("")

            chunks = ragflow_client.retrieve(
                question=query_text,
                page_size=10,
                similarity_threshold=similarity_threshold,
                vector_similarity_weight=1.0,
                keyword=False
            )

            log(f"[语义检索] 原始召回 {len(chunks)} 个知识块")
            log("")
            log("  ┌─────────────────────────────────────────────┐")
            log("  │         语义检索 - 原始召回结果               │")
            log("  └─────────────────────────────────────────────┘")
            for idx, chunk in enumerate(chunks, 1):
                log(f"  [{idx}] 来源: {chunk.get('source', '未知')}")
                log(f"      相似度: {chunk.get('similarity', 0):.4f}")
                log(f"      内容: {chunk.get('content', '')[:200]}...")
                log("")

            # 过滤低相似度结果
            filtered_chunks = [c for c in chunks if c.get('similarity', 0) >= similarity_threshold]
            # 按相似度排序，取 top_k
            filtered_chunks.sort(key=lambda x: x.get('similarity', 0), reverse=True)
            final_chunks = filtered_chunks[:top_k]

            log(f"[语义检索] 过滤后 {len(filtered_chunks)} 个，最终返回 {len(final_chunks)} 个")
            log("")
            log("  ┌─────────────────────────────────────────────┐")
            log("  │         语义检索 - 最终返回结果               │")
            log("  └─────────────────────────────────────────────┘")
            for idx, chunk in enumerate(final_chunks, 1):
                log(f"  [{idx}] 来源: {chunk.get('source', '未知')}")
                log(f"      相似度: {chunk.get('similarity', 0):.4f}")
                log(f"      完整内容:")
                for line in chunk.get('content', '').split('\n'):
                    log(f"        {line}")
                log("")

            return final_chunks

        except Exception as e:
            log(f"[语义检索] 检索失败: {e}")
            import traceback
            log(f"[语义检索] 错误详情: {traceback.format_exc()}")
            return []

    def _retrieve_combined(
        self,
        search_query: str,
        report_content: str,
        ragflow_client,
        top_k: int = 5,
        similarity_threshold: float = 0.2,
        job_logger=None
    ) -> list:
        """
        并行执行关键词混合检索和语义检索，合并去重后取 top_k 个知识块。

        并行策略：
        - 关键词混合检索：基于 LLM 提取的关键词进行混合检索
        - 语义检索：基于报告全文前 1000 字符进行纯向量检索

        Args:
            search_query: 关键词检索查询
            report_content: 报告内容（用于语义检索）
            ragflow_client: RAGFlow 客户端
            top_k: 返回的最大结果数
            similarity_threshold: 相似度阈值
            job_logger: 作业日志器

        Returns:
            合并去重后的检索结果列表
        """
        import concurrent.futures
        log = job_logger.info if job_logger else print

        log("")
        log("=" * 70)
        log("[RAGFlow 检索] 开始并行检索")
        log("=" * 70)
        log(f"  检索策略: 关键词混合检索 + 语义检索 (并行执行)")
        log(f"  相似度阈值: {similarity_threshold}")
        log(f"  返回 TOP_K: {top_k}")
        log("")
        log("  ┌─────────────────────────────────────────────┐")
        log("  │         关键词检索 - 查询文本                  │")
        log("  └─────────────────────────────────────────────┘")
        log(f"  {search_query}")
        log("")

        def _keyword_search():
            """关键词混合检索"""
            log("[关键词检索] 调用 RAGFlow 检索...")
            chunks = ragflow_client.retrieve(
                question=search_query,
                page_size=10,
                similarity_threshold=similarity_threshold
            )
            log(f"[关键词检索] 召回 {len(chunks)} 个知识块")
            return [c for c in chunks if c.get('similarity', 0) >= similarity_threshold]

        def _semantic_search():
            """语义检索"""
            return self._retrieve_semantic(
                report_content=report_content,
                ragflow_client=ragflow_client,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                job_logger=job_logger
            )

        # 并行执行两种检索策略
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_keyword = executor.submit(_keyword_search)
            future_semantic = executor.submit(_semantic_search)

            keyword_chunks = future_keyword.result()
            semantic_chunks = future_semantic.result()

        log(f"[并行检索] 关键词检索到 {len(keyword_chunks)} 个块，语义检索到 {len(semantic_chunks)} 个块")
        log("")
        log("  ┌─────────────────────────────────────────────┐")
        log("  │         关键词检索 - 召回结果                 │")
        log("  └─────────────────────────────────────────────┘")
        for idx, chunk in enumerate(keyword_chunks, 1):
            log(f"  [{idx}] 来源: {chunk.get('source', '未知')}")
            log(f"      相似度: {chunk.get('similarity', 0):.4f}")
            log(f"      内容: {chunk.get('content', '')[:300]}...")
            log("")

        # 合并结果
        all_chunks = keyword_chunks + semantic_chunks

        # 按 chunk_id 去重，保留更高相似度的
        unique_chunks = {}
        for chunk in all_chunks:
            chunk_id = chunk.get('chunk_id')
            if not chunk_id:
                continue
            if chunk_id not in unique_chunks:
                unique_chunks[chunk_id] = chunk
            else:
                if chunk.get('similarity', 0) > unique_chunks[chunk_id].get('similarity', 0):
                    unique_chunks[chunk_id] = chunk

        merged_chunks = list(unique_chunks.values())
        log(f"[并行检索] 合并去重后 {len(merged_chunks)} 个块")

        # 按相似度排序，取 top_k
        merged_chunks.sort(key=lambda x: x.get('similarity', 0), reverse=True)
        final_chunks = merged_chunks[:top_k]

        log(f"[并行检索] 最终返回 {len(final_chunks)} 个知识块")
        log("")
        log("  ┌─────────────────────────────────────────────┐")
        log("  │         RAGFlow 检索 - 最终知识库内容         │")
        log("  └─────────────────────────────────────────────┘")
        for idx, chunk in enumerate(final_chunks, 1):
            log(f"  [{idx}] 来源文档: {chunk.get('source', '未知')}")
            log(f"      相似度: {chunk.get('similarity', 0):.4f}")
            log(f"      完整内容:")
            for line in chunk.get('content', '').split('\n'):
                log(f"        {line}")
            log("")
        log("=" * 70)
        log("")

        return final_chunks

    def _format_knowledge_context(self, chunks: list) -> str:
        """
        将检索到的知识块格式化为上下文字符串

        编号格式使用 [1]、[2] 等直接编号，降低 LLM 映射成本。

        Args:
            chunks: 检索结果列表

        Returns:
            格式化后的知识上下文
        """
        context_parts = []
        for idx, chunk in enumerate(chunks, 1):
            context_parts.append(
                f"[{idx}] (来源: {chunk['document_name']}, 相似度: {chunk['similarity']:.2f})\n"
                f"{chunk['content']}"
            )
        return '\n\n'.join(context_parts)

    def _inject_citation_prompt(self, prompt: str, knowledge_context: str, chunk_count: int) -> str:
        """
        将知识上下文和引用规则注入到提示词中

        强化引用规则，确保 LLM 在正文中使用脚标引用知识库内容，
        而非仅在末尾列出引用来源。

        Args:
            prompt: 原始提示词
            knowledge_context: 知识上下文
            chunk_count: 知识块数量

        Returns:
            注入后的提示词
        """
        citation_rules = """
# 参考知识库
以下是与本次分析相关的知识库内容（共{}条），必须在正文分析中引用：

{}

# 引用规则（强制执行）
1. **必须在正文中引用**：以上知识库内容必须在正文分析中被引用，禁止仅在末尾列出。如果在正文中未出现任何 [数字] 脚标，则视为未引用知识库，必须重新分析并补充引用。
2. **脚标格式**：使用 [数字] 格式的脚标标记（如 [1]、[2]），脚标从 [1] 开始递增。
3. **具体引用场景**：
   - 根因推测时：引用知识库中的类似案例或故障标准（如"根据设备保养基准，折弯度异常通常与模具磨损有关[1]"）
   - 改进措施时：引用知识库中的标准做法或操作规程（如"建议按照点检标准每2小时记录一次[2]"）
   - 异常分析时：引用知识库中的设备参数范围或故障处理标准
4. **正例示例**：
   - 正确："连冲线折弯度低于下限，可能因模具间隙过大导致[1]。建议参照设备保养基准进行模具调整[2]。"
   - 错误："连冲线折弯度低于下限，可能因模具间隙过大导致。（仅在末尾列出 [1][2]）"
5. **引用章节**：在报告末尾输出"## 引用来源"章节，列出所有被正文引用过的知识块，格式：[数字] 来源文档名称 - 引用内容摘要
6. **禁止误引用**：【基础质量周报】部分的内容是上一阶段生成的基础报告，不属于知识库，禁止为其添加引用脚标，禁止将基础质量周报的内容列入"## 引用来源"章节
7. **编号对应**：正文中 [1] 对应知识库中标记为 [1] 的内容，[2] 对应 [2]，以此类推
""".format(chunk_count, knowledge_context)
        # 插入引用规则：优先在 # 输入原数据 前插入，否则在 prompt 开头插入
        if '# 输入原数据' in prompt:
            prompt = prompt.replace(
                '# 输入原数据',
                f'{citation_rules}\n# 输入原数据'
            )
        else:
            prompt = f'{citation_rules}\n{prompt}'
        return prompt

    def _expand_citation_ranges(self, content: str) -> str:
        """
        将内容中的范围简写脚标展开为独立脚标。

        例如：
            [1-4]  -> [1][2][3][4]
            [1,2]  -> [1][2]
            [1-3,5] -> [1][2][3][5]

        Args:
            content: 原始报告内容

        Returns:
            展开后的内容
        """
        import re

        def expand_match(match):
            inner = match.group(1)
            ids = []
            # 先按逗号拆分多个区间
            for part in inner.split(','):
                part = part.strip()
                if '-' in part:
                    # 处理范围 1-4
                    try:
                        start, end = part.split('-', 1)
                        start = int(start.strip())
                        end = int(end.strip())
                        ids.extend(range(start, end + 1))
                    except ValueError:
                        # 解析失败保持原样
                        return match.group(0)
                else:
                    # 单个数字
                    try:
                        ids.append(int(part))
                    except ValueError:
                        return match.group(0)
            # 去重并保持顺序
            seen = set()
            unique_ids = []
            for i in ids:
                if i not in seen:
                    seen.add(i)
                    unique_ids.append(i)
            return ''.join(f'[{i}]' for i in unique_ids)

        # 匹配 [1-4]、[1,2,3]、[1-3,5] 等格式
        return re.sub(r'\[(\d+(?:[-,]\d+)+)\]', expand_match, content)

    def _filter_base_report_citations(self, content: str) -> str:
        """
        过滤掉引用来源中的"基础报告"条目，避免将上一阶段报告误引用为知识库来源。
        同时重新编号引用脚标，保持连续性。

        Args:
            content: 原始报告内容

        Returns:
            清理后的内容
        """
        # 直接处理实际换行符的内容
        working_content = content

        # 查找 "## 引用来源" 章节
        citation_match = re.search(r'\n##\s*引用来源\s*\n', working_content)
        if not citation_match:
            citation_match = re.search(r'##\s*引用来源\s*\n', working_content)
            if not citation_match:
                return content

        citation_start = citation_match.start()
        citation_header_end = citation_match.end()

        # 引用章节到下一个 ## 标题或文末
        rest = working_content[citation_header_end:]
        next_header = re.search(r'\n##\s', rest)
        if next_header:
            citation_end = citation_header_end + next_header.start()
        else:
            citation_end = len(working_content)

        citation_section = working_content[citation_header_end:citation_end]
        prefix = working_content[:citation_start]
        suffix = working_content[citation_end:]

        # 解析每条引用行
        citation_pattern = re.compile(r'^\s*\[(\d+)\]\s*(.+?)\s*[-–—]\s*(.+?)\s*$', re.MULTILINE)
        matches = citation_pattern.findall(citation_section)

        if not matches:
            return content

        base_keywords = ['基础报告', '基础质量周报', '上一阶段']

        old_to_new = {}
        new_citations = []
        new_id = 1

        for old_id_str, source, text in matches:
            old_id = int(old_id_str)
            if any(kw in source for kw in base_keywords):
                old_to_new[old_id] = None
            else:
                old_to_new[old_id] = new_id
                new_citations.append((new_id, source.strip(), text.strip()))
                new_id += 1

        # 无变化，直接返回
        if len(new_citations) == len(matches):
            return content

        # 替换正文中的脚标
        def replacer(m):
            num = int(m.group(1))
            mapped = old_to_new.get(num)
            return f'[{mapped}]' if mapped else ''

        prefix = re.sub(r'\[(\d+)\]', replacer, prefix)

        # 重建引用章节
        if new_citations:
            new_citation_section = '## 引用来源\n' + '\n'.join(
                f'[{cid}] {src} - {txt}' for cid, src, txt in new_citations
            )
            result = prefix + new_citation_section + suffix
        else:
            result = prefix.rstrip() + suffix

        # 直接返回，不做 \n 字面量转换
        return result

    def _load_report_config(self, config_path: str = None) -> dict:
        """
        加载报告配置文件

        Args:
            config_path: 配置文件路径，默认为 config/report_templates.yaml

        Returns:
            配置字典
        """
        if config_path is None:
            # 默认配置路径：项目根目录/config/report_templates.yaml
            current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(current_dir, 'backend', 'config', 'report_templates.yaml')

        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _load_template(self, template_file: str) -> str:
        """
        加载提示词模板

        优先级：明文文件 > 加密加载器兜底

        Args:
            template_file: 模板文件名

        Returns:
            模板内容
        """
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # 1. 优先从项目根目录加载（特殊规则）
        root_path = os.path.join(project_root, 'prompts', template_file)
        if os.path.exists(root_path):
            with open(root_path, 'r', encoding='utf-8') as f:
                return f.read()

        # 2. 从各模块 prompts/ 目录加载
        modules_dir = os.path.join(project_root, 'backend', 'modules')
        if os.path.isdir(modules_dir):
            for module_name in os.listdir(modules_dir):
                module_prompts_dir = os.path.join(modules_dir, module_name, 'prompts')
                if os.path.isdir(module_prompts_dir):
                    template_path = os.path.join(module_prompts_dir, template_file)
                    if os.path.exists(template_path):
                        with open(template_path, 'r', encoding='utf-8') as f:
                            return f.read()

        # 3. 兜底：通过加密加载器查找（生产环境 prompts_encrypted.json）
        from backend.utils.prompt_loader import prompt_loader
        try:
            return prompt_loader.get_prompt(template_file)
        except FileNotFoundError:
            pass

        raise FileNotFoundError(f"模板文件不存在: {template_file}")

    def _load_temporary_rules(self, report_code: str = None) -> str:
        """
        加载临时规则并格式化为可注入提示词的文本

        从 config/temporary_rules.yaml 读取规则配置，
        按报告类型过滤、按优先级排序后格式化为文本段落。

        Args:
            report_code: 当前报告类型代码，用于过滤适用的规则。
                         若为 None 或空，则加载所有启用的规则。

        Returns:
            格式化后的临时规则文本，若无适用规则则返回空字符串
        """
        import datetime

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        rules_path = os.path.join(project_root, 'backend', 'config', 'temporary_rules.yaml')

        # 配置文件不存在时静默返回，不影响正常报告生成
        if not os.path.exists(rules_path):
            return ''

        try:
            with open(rules_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except Exception:
            return ''

        if not config or 'rules' not in config:
            return ''

        today = datetime.date.today()
        applicable_rules = []

        for rule in config['rules']:
            # 跳过未启用的规则
            if not rule.get('enabled', False):
                continue

            # 检查是否已过期
            expire_date = rule.get('expire_date')
            if expire_date:
                try:
                    expire = datetime.date.fromisoformat(str(expire_date))
                    if today > expire:
                        continue
                except (ValueError, TypeError):
                    pass

            # 检查报告类型是否匹配
            rule_types = rule.get('report_types', [])
            if rule_types and report_code and report_code not in rule_types:
                continue

            applicable_rules.append(rule)

        if not applicable_rules:
            return ''

        # 按优先级排序（数字越小越靠前）
        applicable_rules.sort(key=lambda r: r.get('priority', 999))

        # 格式化为文本
        lines = []
        for rule in applicable_rules:
            content = rule.get('content', '').strip()
            if content:
                lines.append(content)

        return '\n\n'.join(lines)

    def _generate_reports_sequential(
        self,
        data: dict,
        templates: List[Dict],
        job_logger=None,
        llm_configs: list[dict[str, Any]] | None = None,
    ) -> List[Dict]:
        """
        串行生成报告

        Args:
            data: 原始数据
            templates: 模板配置列表
            job_logger: 作业日志器
            llm_config: 可选，LLM 配置字典
        """
        results = []
        log = job_logger.info if job_logger else print
        disabled_providers: set[str] = set()

        for template_config in templates:
            output_name = template_config['output_name']
            template_file = template_config['template']
            use_ragflow = template_config.get('use_ragflow', False)

            log(f"\n{'='*60}")
            log(f"[报告生成] 开始生成: {output_name}")
            log(f"[报告生成] 使用 RAGFlow: {use_ragflow}")
            log(f"{'='*60}")

            try:
                # 生成报告
                if use_ragflow:
                    # 使用带引用的报告生成方法
                    result = self.generate_report_with_citation(
                        data=data,
                        template_file=template_file,
                        use_ragflow=True,
                        job_logger=job_logger,
                        llm_config=llm_configs,
                        disabled_providers=disabled_providers,
                    )
                    content = result['content']
                    citations = result['citations']
                else:
                    content = self._generate_report(
                        data,
                        template_file,
                        llm_configs,
                        disabled_providers=disabled_providers,
                    )
                    citations = []

                results.append({
                    'output_name': output_name,
                    'content': content,
                    'citations': citations
                })

                logger.info("[报告生成] %s 生成完成，内容长度: %d 字符，引用: %d",
                            output_name, len(content), len(citations))

            except Exception as e:
                logger.error("[报告生成] %s 生成失败: %s", output_name, e, exc_info=True)
                results.append({
                    'output_name': output_name,
                    'content': f"生成失败: {str(e)}",
                    'error': str(e),
                    'citations': []
                })

        return results

    def _generate_reports_parallel(
        self,
        data: dict,
        templates: List[Dict],
        job_logger=None,
        llm_configs: list[dict[str, Any]] | None = None,
    ) -> List[Dict]:
        """
        并行生成报告

        Args:
            data: 原始数据
            templates: 模板配置列表
            job_logger: 作业日志器
            llm_config: 可选，LLM 配置字典
        """
        results = {}
        completed_count = 0
        total_count = len(templates)
        log = job_logger.info if job_logger else print
        disabled_providers: set[str] = set()

        # 使用线程池并行执行
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_template = {
                executor.submit(
                    self._generate_single_report,
                    data,
                    template,
                    job_logger,
                    llm_configs,
                    disabled_providers,
                ): template
                for template in templates
            }

            # 按完成顺序收集结果
            for future in as_completed(future_to_template):
                template = future_to_template[future]

                try:
                    result = future.result()
                    results[template['template']] = result
                    completed_count += 1
                    logger.info("[进度] %d/%d 完成 - %s", completed_count, total_count, result['output_name'])

                except Exception as e:
                    logger.error("[报告生成] 并行任务失败: %s", e, exc_info=True)
                    results[template['template']] = {
                        'output_name': template['output_name'],
                        'content': f"生成失败: {str(e)}",
                        'error': str(e)
                    }

        # 按原始模板顺序排列结果
        ordered_results = []
        for template in templates:
            ordered_results.append(results[template['template']])

        return ordered_results

    def _generate_single_report(
        self,
        data: dict,
        template_config: Dict,
        job_logger=None,
        llm_configs: list[dict[str, Any]] | None = None,
        disabled_providers: set[str] | None = None,
    ) -> Dict:
        """
        生成单份报告

        Args:
            data: 原始数据
            template_config: 模板配置
            job_logger: 作业日志器
            llm_config: 可选，LLM 配置字典
        """
        output_name = template_config['output_name']
        template_file = template_config['template']
        use_ragflow = template_config.get('use_ragflow', False)
        log = job_logger.info if job_logger else print

        try:
            if use_ragflow:
                # 使用带引用的报告生成方法
                result = self.generate_report_with_citation(
                    data=data,
                    template_file=template_file,
                    use_ragflow=True,
                    job_logger=job_logger,
                    llm_config=llm_configs,
                    disabled_providers=disabled_providers,
                )
                content = result['content']
                citations = result['citations']
            else:
                content = self._generate_report(
                    data,
                    template_file,
                    llm_configs,
                    disabled_providers=disabled_providers,
                )
                citations = []

            return {
                'output_name': output_name,
                'content': content,
                'citations': citations
            }

        except Exception as e:
            return {
                'output_name': output_name,
                'content': f"生成失败: {str(e)}",
                'error': str(e),
                'citations': []
            }

    def _format_workshop_reports_for_prompt(self, workshop_reports: list) -> str:
        """
        将所有工序的报告格式化为提示词输入格式

        Args:
            workshop_reports: 工序报告列表，每个元素包含 workshopId, workshopName, procedureId, procedureName, report1Content

        Returns:
            格式化后的字符串，用于注入到提示词中
        """
        lines = []
        lines.append("## 各车间工序日会早报汇总")
        lines.append("")

        for idx, report in enumerate(workshop_reports, 1):
            lines.append(f"### {idx}. {report.get('workshopName', '未知车间')} - {report.get('procedureName', '未知工序')}")
            lines.append("")
            lines.append(report.get('report1Content', '无内容'))
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def generate_factory_reports_stream(
        self,
        all_workshop_reports: list,
        report_date: str,
        historical_context: str = None,
        config_path: str = None,
        job_logger=None,
        template_limit: int = None,
    ) -> Generator[dict, None, None]:
        """
        流式生成工厂级报告

        Args:
            all_workshop_reports: 所有工序生成的报告列表，每个元素包含 workshopId, workshopName, procedureId, procedureName, report1Content
            report_date: 报告日期
            historical_context: 历史工厂报告上下文
            config_path: 配置文件路径
            job_logger: 作业日志器实例

        Yields:
            流式事件，格式与 generate_reports_stream 相同
        """
        # 构建工厂级报告的输入数据结构
        factory_data = {
            'meta': {
                'reportDate': report_date,
                'reportType': 'factoryMorningDailyReport',
                'historicalContext': historical_context or ''
            },
            'allWorkshopReports': all_workshop_reports
        }

        # 复用现有的流式报告生成方法
        yield from self.generate_reports_stream(
            data=factory_data,
            report_code='factoryMorningDailyReport',
            config_path=config_path,
            job_logger=job_logger,
            template_limit=template_limit,
        )

    def _generate_report(
        self,
        data: dict,
        template_file: str,
        llm_config: dict[str, Any] | list[dict[str, Any]] | None = None,
        disabled_providers: set[str] | None = None,
    ) -> str:
        """
        生成报告

        Args:
            data: 原始数据
            template_file: 模板文件名
            llm_config: 可选，LLM 配置字典，为 None 时使用默认配置

        Returns:
            报告内容
        """
        # 加载模板并分离关键词提取部分
        template_content = self._load_template(template_file)
        _, report_prompt = self._split_template(template_content)

        # 构建提示词
        prompt = report_prompt.replace('{data_sources}', json.dumps(data, ensure_ascii=False, indent=2))

        if isinstance(llm_config, list):
            llm_configs = llm_config
        elif llm_config:
            llm_configs = [llm_config]
        else:
            llm_configs = [{
                "provider": self.provider,
                "base_url": self.base_url,
                "api_key": self.api_key,
                "model": self.model,
                "is_ollama": self._is_ollama(),
                "source": "default_provider",
            }]

        # 调用 LLM
        content, _ = self._call_model_with_failover(
            prompt,
            llm_configs,
            disabled_providers=disabled_providers,
        )

        return self._expand_citation_ranges(content)


# 单例
_generator = None


def get_report_generator(
    llm_model: str = None,
    base_url: str = None,
    api_key: str = None,
    max_workers: int = 3
) -> ReportGenerator:
    """
    获取报告生成器实例（单例）

    Args:
        llm_model: LLM 模型名称
        base_url: LLM API 地址
        api_key: LLM API 密钥
        max_workers: 最大并发数

    Returns:
        ReportGenerator 实例
    """
    global _generator
    if _generator is None:
        _generator = ReportGenerator(llm_model, base_url, api_key, max_workers)
    return _generator
