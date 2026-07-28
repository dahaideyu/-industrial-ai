# cython: annotation_typing=False, infer_types=False, language_level=3
"""Entity-related tools: search_entities, get_schema."""
from typing import Any, Dict, Optional

from backend.core.agentic_qa.logger import get_logger
from backend.services.agentic_qa.base_tool import BaseTool, ToolContext

logger = get_logger("agentic_qa.tool_impls.entity_tools")


# ── SearchEntitiesTool ──

class SearchEntitiesTool(BaseTool):
    """Search entity index for matching device/line names."""

    name = "search_entities"
    description = (
        "搜索实体索引，查找匹配的设备名称、产线名称或其他实体。"
        "使用完整管道：别名匹配 → 向量搜索 → LIKE 回退。"
    )
    schema = {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "搜索关键词，用于实体查找",
            },
            "entity_type": {
                "type": "string",
                "description": "可选实体类型过滤（如 device、line）",
            },
        },
        "required": ["keyword"],
    }
    when_to_use = "用户问题中包含设备/产线名称，需要确认或搜索具体实体"
    when_not_to_use = "问题不涉及具体实体，或已通过 confirmed_entities 获得"

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        keyword = kwargs.get("keyword", "")
        entity_type = kwargs.get("entity_type")

        from backend.services.agentic_qa.agents.entity_resolver import _search_with_fallback

        try:
            results = _search_with_fallback(keyword, entity_type or "")
            filtered = [
                {
                    "name": r.get("label", ""),
                    "type": r.get("entity_type", entity_type or ""),
                    "label": r.get("label", ""),
                    "value": r.get("value", ""),
                    "score": r.get("score", 0),
                    "sublabel": r.get("sublabel", ""),
                    "match_type": r.get("match_type", ""),
                }
                for r in (results or [])
                if not entity_type or r.get("entity_type") == entity_type
            ]
            return {"entities": filtered[:10]}
        except Exception as e:
            logger.warning(f"[SearchEntitiesTool] error: {e}")
            return {"entities": []}


# ── GetSchemaTool ──

class GetSchemaTool(BaseTool):
    """Retrieve relevant table schemas for SQL generation."""

    name = "get_schema"
    description = (
        "检索与问题相关的数据库表结构信息。在生成 SQL 前，"
        "可用于了解表的列名、类型和关系。"
    )
    schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "用于查找相关表结构的问题",
            },
        },
        "required": ["question"],
    }
    when_to_use = "生成 SQL 前需要了解表结构，或表名/列名不确定"
    when_not_to_use = "已有足够表结构信息，或不需要查库"

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        question = kwargs.get("question", "")

        from backend.services.agentic_qa.vanna.agent import get_vanna_manager

        try:
            manager = get_vanna_manager()
            schemas = manager.search_table_schemas(question, limit=5)
            schema_texts = [
                s.content if hasattr(s, "content") else str(s)
                for s in (schemas or [])
            ]
            return {"schemas": schema_texts}
        except Exception as e:
            logger.warning(f"[GetSchemaTool] error: {e}")
            return {"schemas": []}
