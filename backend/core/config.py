# cython: annotation_typing=False, infer_types=False, language_level=3
import os
import sys
import logging

# 统一的 .env 加载入口：幂等，若 app.py 已加载过则直接返回，不再二次加载选到不同文件
from core.env import load_env
load_env()

logger = logging.getLogger(__name__)

CONFIG = {
    "provider": None,
    "model": None,
    "base_url": None,
    "api_key": None
}


def load_config():
    """
    从环境变量加载模型配置
    需要的环境变量:
      - PROVIDER: 模型供应商 (deepseek, qwen3, openai, local_qwen3)
      - MODEL: (可选) 覆盖默认模型名称
    """
    provider = os.getenv("PROVIDER")
    if not provider:
        raise ValueError("请设置 PROVIDER 环境变量 (如: deepseek, qwen3, openai, local_qwen3)")

    provider_upper = provider.upper()
    base_url_var = f"{provider_upper}_BASE_URL"
    api_key_var = f"{provider_upper}_API_KEY"
    model_var = f"{provider_upper}_MODEL"

    base_url = os.getenv(base_url_var)
    api_key = os.getenv(api_key_var)
    default_model = os.getenv(model_var)

    if not base_url:
        raise ValueError(f"请在 .env 文件中配置 {base_url_var}")
    if not api_key:
        raise ValueError(f"请在 .env 文件中配置 {api_key_var}")

    model = os.getenv("MODEL") or default_model
    if not model:
        raise ValueError(f"请设置 MODEL 环境变量或在 .env 中配置 {model_var}")

    CONFIG["provider"] = provider
    CONFIG["model"] = model
    CONFIG["base_url"] = base_url
    CONFIG["api_key"] = api_key

    logger.info("已加载模型配置: provider=%s model=%s base_url=%s", provider, model, base_url)


try:
    load_config()
except Exception as e:
    logger.error("配置加载失败: %s", e)
    sys.exit(1)


def get_llm_client(async_client: bool = False, timeout: float = 600.0):
    """按 CONFIG（PROVIDER 环境变量决定的供应商）构造 OpenAI 兼容客户端。

    Args:
        async_client: True 返回 AsyncOpenAI，否则返回同步 OpenAI。
        timeout: 请求超时时间（秒）。
    """
    from openai import AsyncOpenAI, OpenAI

    cls = AsyncOpenAI if async_client else OpenAI
    return cls(base_url=CONFIG["base_url"], api_key=CONFIG["api_key"], timeout=timeout)
