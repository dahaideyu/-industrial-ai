# cython: annotation_typing=False, infer_types=False, language_level=3
import os
from dotenv import load_dotenv

load_dotenv()


def _get_llm_config() -> dict[str, str]:
    """根据 PROVIDER 环境变量获取 LLM 配置"""
    provider = os.getenv("PROVIDER", "deepseek").upper()
    return {
        "api_key": os.getenv(f"{provider}_API_KEY", ""),
        "base_url": os.getenv(f"{provider}_BASE_URL", ""),
        "model": os.getenv(f"{provider}_MODEL", ""),
    }


# 初始化时获取 LLM 配置
_llm_config = _get_llm_config()


class Config:
    # LLM 配置（根据 PROVIDER 环境变量动态读取）
    LLM_PROVIDER = os.getenv("PROVIDER", "deepseek").strip().lower()
    LLM_API_KEY = _llm_config["api_key"]
    LLM_BASE_URL = _llm_config["base_url"]
    LLM_MODEL = _llm_config["model"]

    # 兼容旧代码；新代码统一使用 LLM_* 命名，避免误判实际供应商。
    DEEPSEEK_API_KEY = LLM_API_KEY
    DEEPSEEK_BASE_URL = LLM_BASE_URL
    DEEPSEEK_MODEL = LLM_MODEL

    # RAGFlow
    RAGFLOW_BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://192.168.106.100:9380")
    RAGFLOW_API_KEY = os.getenv("RAGFLOW_API_KEY")
    RAGFLOW_HISTORY_ASSISTANT_ID = os.getenv("RAGFLOW_HISTORY_ASSISTANT_ID")
    RAGFLOW_DOC_ASSISTANT_ID = os.getenv("RAGFLOW_DOC_ASSISTANT_ID")

    # Service
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
