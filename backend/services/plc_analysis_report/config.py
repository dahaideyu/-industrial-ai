# cython: annotation_typing=False, infer_types=False, language_level=3
"""PLC 解析服务配置管理模块 - 使用 pydantic-settings 管理 API 配置"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """PLC 解析服务配置"""

    # DashScope API 配置
    dashscope_api_key: str = "sk-REDACTED"
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 模型配置
    vision_model: str = "qwen-vl-plus"
    text_model: str = "qwen3.6-plus"

    # 超时配置（秒）
    vision_timeout: float = 120.0
    text_timeout: float = 180.0
    max_retries: int = 3

    # PDF 处理配置
    pdf_dpi: int = 300

    class Config:
        env_prefix = "PLC_"
        env_file = "docker/.env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()

