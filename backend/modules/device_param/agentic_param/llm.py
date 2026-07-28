# cython: annotation_typing=False, infer_types=False, language_level=3
"""独立的同步 LLM 客户端（OpenAI 兼容，从 CONFIG 取 provider/model/base_url/api_key）。

不复用 agentic_qa / sql_qa 的客户端，保持参数诊断域自包含。DeepSeek 等支持 function calling。
"""
from openai import OpenAI

from core.config import CONFIG

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=CONFIG["base_url"], api_key=CONFIG["api_key"],
                         timeout=120.0)
    return _client


def get_model() -> str:
    return CONFIG["model"]
