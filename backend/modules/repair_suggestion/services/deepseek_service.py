"""旧 DeepSeek 服务模块的兼容入口。

新代码应从 ``llm_service`` 导入 ``LLMService``。保留本模块是为了避免已有
部署脚本或外部调用方因模块路径变化立即失效。
"""

from .llm_service import LLMService

DeepSeekService = LLMService

__all__ = ["DeepSeekService", "LLMService"]
