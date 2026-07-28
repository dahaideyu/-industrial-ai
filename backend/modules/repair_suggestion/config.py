# cython: annotation_typing=False, infer_types=False, language_level=3
import os
from dotenv import load_dotenv

load_dotenv()


def _get_llm_config():
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
    DEEPSEEK_API_KEY = _llm_config["api_key"]
    DEEPSEEK_BASE_URL = _llm_config["base_url"]
    DEEPSEEK_MODEL = _llm_config["model"]

    # RAGFlow
    RAGFLOW_BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://192.168.106.100:9380")
    RAGFLOW_API_KEY = os.getenv("RAGFLOW_API_KEY")
    RAGFLOW_HISTORY_ASSISTANT_ID = os.getenv("RAGFLOW_HISTORY_ASSISTANT_ID")
    RAGFLOW_DOC_ASSISTANT_ID = os.getenv("RAGFLOW_DOC_ASSISTANT_ID")

    # Service
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
