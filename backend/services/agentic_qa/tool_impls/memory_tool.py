# cython: annotation_typing=False, infer_types=False, language_level=3
"""Memory tool: read_memory."""
from typing import Any, Dict

from backend.core.agentic_qa.logger import get_logger
from backend.services.agentic_qa.base_tool import BaseTool, ToolContext

logger = get_logger("agentic_qa.tool_impls.memory_tool")


# ── ReadMemoryTool ──

class ReadMemoryTool(BaseTool):
    """Read a value from the session memory cache."""

    name = "read_memory"
    description = (
        "从 session memory 缓存中读取值。"
        "可读取 entity_context、last_query、analysis_suggestions 等。"
    )
    schema = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "要读取的 memory 键名",
            },
        },
        "required": ["key"],
    }
    when_to_use = "需要获取之前存储的实体上下文、查询结果、分析建议等"
    when_not_to_use = "需要实时查询数据，而非读取缓存"

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        key = kwargs.get("key", "")

        try:
            if not ctx.memory_hub:
                return {"key": key, "value": None, "found": False}

            context = ctx.memory_hub.get_session_context()
            value = context.get(key)
            return {"key": key, "value": value, "found": value is not None}
        except Exception as e:
            logger.warning(f"[ReadMemoryTool] error reading key='{key}': {e}")
            return {"key": key, "value": None, "found": False}
