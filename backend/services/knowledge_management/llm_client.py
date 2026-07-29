# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库模块共用的 LLM 调用封装，根据 PROVIDER 环境变量适配供应商（CONFIG 由 core.config 加载）"""
import requests

from backend.core.config import CONFIG


def call_llm(prompt: str, max_tokens: int = 2000, temperature: float = 0.3) -> str:
    """调用 LLM API 生成文本。

    Args:
        prompt: 用户提示。
        max_tokens: 最大生成 token 数。
        temperature: 采样温度。

    Returns:
        模型返回的文本内容。

    Raises:
        RuntimeError: API 调用失败或未返回有效响应。
    """
    url = f"{CONFIG['base_url'].rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {CONFIG['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": CONFIG["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("LLM API 未返回有效响应")

    return choices[0]["message"]["content"].strip()
