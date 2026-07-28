# cython: annotation_typing=False, infer_types=False, language_level=3
from openai import OpenAI
from typing import Optional, List, Dict, Any, Callable
import time
from backend.core.agentic_qa.config import settings
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("core.llm")

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


class LLMConnectionError(Exception):
    """LLM 连接失败异常"""
    pass


class LLM:
    """通用 LLM 客户端，根据 PROVIDER 环境变量自动适配模型供应商"""

    def __init__(self):
        self.client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url
        )
        self.model = settings.deepseek_model

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ) -> Any:
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature
        }
        if max_tokens:
            params["max_tokens"] = max_tokens

        if stream:
            return self.client.chat.completions.create(**params, stream=True)
        else:
            response = self.client.chat.completions.create(**params)
            content = response.choices[0].message.content
            if not content:
                logger.warning(f"[llm] API returned empty content. model={params.get('model')} finish_reason={response.choices[0].finish_reason} usage={response.usage}")
            return content

    def chat_once(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)

    def chat_once_with_retry(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        on_retry: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        """带重试的聊天接口，最多重试 MAX_RETRIES 次（含空响应重试）"""
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = self.chat_once(
                    user_prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if not result or not result.strip():
                    raise ValueError("LLM returned empty content (likely token limit or reasoning overflow)")
                return result
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    msg = f"连接大模型异常，正在重试... ({attempt}/{MAX_RETRIES})"
                    logger.warning(f"[llm] retry {attempt}/{MAX_RETRIES}: {e}")
                    if on_retry:
                        on_retry(attempt, msg)
                    time.sleep(RETRY_DELAY)

        logger.error(f"[llm] all {MAX_RETRIES} retries failed: {last_error}")
        raise LLMConnectionError(f"连接大模型失败，请稍后重试。（已重试{MAX_RETRIES}次）")


llm = LLM()

# 向后兼容别名
DeepSeekLLM = LLM
