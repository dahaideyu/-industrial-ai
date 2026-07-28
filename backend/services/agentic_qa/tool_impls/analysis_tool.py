# cython: annotation_typing=False, infer_types=False, language_level=3
"""Analysis tool: analyze_data."""
from typing import Any, Dict, List, Optional

from backend.core.agentic_qa.logger import get_logger
from backend.services.agentic_qa.base_tool import BaseTool, ToolContext

logger = get_logger("agentic_qa.tool_impls.analysis_tool")


# ── AnalyzeDataTool ──

class AnalyzeDataTool(BaseTool):
    """Generate data insights and chart configuration from query results."""

    name = "analyze_data"
    description = (
        "对 SQL 查询结果进行数据分析，生成洞察和图表配置。"
        "在数据获取后调用，可自动从 session memory 读取最近的查询结果。"
    )
    schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "分析问题，描述你想从数据中获得什么洞察",
            },
            "query_results": {
                "type": "array",
                "items": {"type": "object"},
                "description": "可选，要分析的查询结果数据。不传则从 session memory 读取 last_query",
            },
        },
        "required": ["question"],
    }
    when_to_use = "execute_sql 成功返回数据后，需要分析趋势、异常或生成图表"
    when_not_to_use = "尚未获取数据，或用户不需要分析"

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        question = kwargs.get("question", "")
        query_results = kwargs.get("query_results")

        # 优先使用传入的 query_results，否则从 memory_hub 读取
        if not query_results and ctx.memory_hub:
            session_ctx = ctx.memory_hub.get_session_context()
            last_query = session_ctx.get("last_query")
            if last_query and isinstance(last_query, dict):
                query_results = last_query.get("data")

        if not query_results:
            return {"insights": "没有可供分析的数据。请先执行 SQL 查询获取数据。", "chart": None}

        # 暂用旧的 analyze_data + AgentState 方式（后续改为 analyze_data_direct）
        from backend.services.agentic_qa.agents.analysis_agent import analyze_data as _analyze_data
        from backend.services.agentic_qa.state import AgentState

        state: AgentState = {
            "question": question,
            "normalized_question": question,
            "session_memory": {
                "last_query": {"data": query_results, "sql": ""},
                "history": [],
            },
            "query_results": query_results,
            "result_groups": None,
            "final_answer": None,
            "analysis_chart": None,
            "session_id": ctx.session_id,
            "sql": None,
            "sql_valid": True,
            "sql_error": None,
            "analysis_suggestions": None,
            "messages": [],
            "steps": [],
            "intent": "analysis",
            "intent_confidence": None,
            "needs_clarification": False,
            "clarification_questions": [],
            "clarification_options": [],
            "clarification_groups": [],
            "clarification_type": None,
            "confirmed_clarifications": None,
            "entity_candidates": [],
            "auto_completions": [],
            "confirmed_entities": None,
            "rag_answer": None,
            "rag_thinking": None,
            "rag_references": None,
            "user_role": "admin",
            "use_rag": False,
        }
        try:
            state = _analyze_data(state, {})
            return {
                "insights": state.get("final_answer", ""),
                "chart": state.get("analysis_chart"),
            }
        except Exception as e:
            logger.error(f"[AnalyzeDataTool] error: {e}")
            return {"insights": f"分析失败: {e}", "chart": None}
