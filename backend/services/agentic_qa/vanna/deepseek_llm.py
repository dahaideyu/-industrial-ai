# cython: annotation_typing=False, infer_types=False, language_level=3
"""Vanna LlmService — 通用 LLM 实现（根据 PROVIDER 环境变量自动适配）"""
from typing import List, AsyncGenerator
from openai import OpenAI, AsyncOpenAI
from vanna.core import LlmService, LlmMessage, LlmRequest, LlmResponse, LlmStreamChunk
from backend.core.agentic_qa.config import settings


class LlmServiceImpl(LlmService):
    """通用 LLM API 适配 Vanna LlmService 接口，根据 PROVIDER 环境变量自动适配模型供应商"""

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = None
    ):
        self.api_key = api_key or settings.deepseek_api_key
        self.base_url = base_url or settings.deepseek_base_url
        self.model = model or settings.deepseek_model
        self._client = None
        self._async_client = None

    @property
    def client(self):
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    @property
    def async_client(self):
        if self._async_client is None:
            self._async_client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._async_client

    def _to_openai_messages(self, messages: List[LlmMessage]) -> list:
        return [{"role": msg.role, "content": msg.content} for msg in messages]

    def send_request(self, request: LlmRequest) -> LlmResponse:
        """同步请求 (LlmService 抽象方法)"""
        response = self.client.chat.completions.create(
            model=request.model or self.model,
            messages=self._to_openai_messages(request.messages),
            temperature=request.temperature if request.temperature is not None else 0.1,
            max_tokens=request.max_tokens or 4096
        )
        return LlmResponse(content=response.choices[0].message.content)

    async def stream_request(self, request: LlmRequest) -> AsyncGenerator[LlmStreamChunk, None]:
        """流式请求 (LlmService 抽象方法)"""
        stream = await self.async_client.chat.completions.create(
            model=request.model or self.model,
            messages=self._to_openai_messages(request.messages),
            temperature=request.temperature if request.temperature is not None else 0.1,
            max_tokens=request.max_tokens or 4096,
            stream=True
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield LlmStreamChunk(content=delta.content)

    def validate_tools(self, tools: List) -> List[str]:
        """验证工具列表 (LlmService 抽象方法)"""
        return []  # DeepSeek 不强制校验工具

    # 保留旧方法以兼容现有代码
    def process(self, request: LlmRequest) -> LlmResponse:
        return self.send_request(request)

    async def aprocess(self, request: LlmRequest) -> LlmResponse:
        messages = self._to_openai_messages(request.messages)
        response = await self.async_client.chat.completions.create(
            model=request.model or self.model,
            messages=messages,
            temperature=request.temperature if request.temperature is not None else 0.1,
            max_tokens=request.max_tokens or 4096
        )
        return LlmResponse(content=response.choices[0].message.content)

    async def astream(self, request: LlmRequest) -> AsyncGenerator[LlmStreamChunk, None]:
        async for chunk in self.stream_request(request):
            yield chunk


# 向后兼容别名
DeepSeekLlmService = LlmServiceImpl
