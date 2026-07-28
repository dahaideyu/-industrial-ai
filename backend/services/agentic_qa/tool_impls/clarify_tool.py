# cython: annotation_typing=False, infer_types=False, language_level=3
"""Clarification tool: ask_clarification."""
from typing import Any, Dict, List, Optional

from backend.core.agentic_qa.logger import get_logger
from backend.services.agentic_qa.base_tool import BaseTool, ToolContext

logger = get_logger("agentic_qa.tool_impls.clarify_tool")


# ── AskClarificationTool ──

class AskClarificationTool(BaseTool):
    """Pause execution and ask user for clarification."""

    name = "ask_clarification"
    description = (
        "暂停执行并向用户请求澄清。用于实体消歧或意图确认。"
        "务必提供具体的可点击选项，不要只问开放式问题。"
    )
    schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "简短的问题或提示，如 '请确认您要查询的设备：'",
            },
            "groups": {
                "type": "array",
                "description": "实体消歧时使用：一组或多组选项供用户选择",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "组标签，如 '和膏设备'",
                        },
                        "field": {
                            "type": "string",
                            "description": "字段名，如 'device'",
                        },
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可点击的选项文本",
                        },
                        "multi": {
                            "type": "boolean",
                            "description": "是否允许多选，默认 false",
                        },
                    },
                },
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "意图澄清时使用：简单的选项列表",
            },
            "allow_custom": {
                "type": "boolean",
                "description": "是否允许用户自定义输入，默认 true",
            },
        },
        "required": ["message"],
    }
    when_to_use = "实体名称有歧义需要消歧，或用户意图不明确需要确认"
    when_not_to_use = "实体已确认、意图明确，或可以通过其他工具自行解决"

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        message = kwargs.get("message", "")
        groups = kwargs.get("groups")
        options = kwargs.get("options")
        allow_custom = kwargs.get("allow_custom", True)

        _AGGREGATE_WORDS = {"全选", "两个都查", "所有都查", "全部", "所有", "都查", "都行"}

        def _clean_options(opts):
            """过滤掉与全选重复的聚合选项"""
            if not isinstance(opts, list):
                return []
            return [o for o in opts if isinstance(o, str) and o.strip() not in _AGGREGATE_WORDS]

        try:
            if groups:
                cleaned = []
                for g in groups:
                    g = dict(g)
                    g["options"] = _clean_options(g.get("options", []))
                    g["allow_select_all"] = False
                    g["allow_custom"] = g.get("allow_custom", allow_custom)
                    g["multi"] = g.get("multi", len(g["options"]) > 1)
                    if g["options"]:
                        cleaned.append(g)
                if cleaned:
                    return {
                        "action": "pause_for_clarification",
                        "type": "entity_ambiguous",
                        "message": message or "请确认以下信息：",
                        "groups": cleaned,
                    }
            # LLM used 'options' (simple list) instead of 'groups' — wrap into groups format
            clean_options = _clean_options(options)
            return {
                "action": "pause_for_clarification",
                "type": "intent_ambiguous",
                "message": message or "需要更多信息",
                "groups": [{
                    "field": "entity",
                    "label": message or "请选择",
                    "options": clean_options,
                    "multi": len(clean_options) > 1,
                    "allow_select_all": False,
                    "allow_custom": allow_custom,
                }] if clean_options else [],
                "options": options or [],
                "allow_custom": allow_custom,
            }
        except Exception as e:
            logger.error(f"[AskClarificationTool] error: {e}")
            return {
                "action": "pause_for_clarification",
                "type": "intent_ambiguous",
                "message": message or "需要更多信息",
                "options": [],
                "allow_custom": True,
            }
