# cython: annotation_typing=False, infer_types=False, language_level=3
"""General tool: answer_general."""
from typing import Any, Dict

from backend.core.agentic_qa.logger import get_logger
from backend.services.agentic_qa.base_tool import BaseTool, ToolContext

logger = get_logger("agentic_qa.tool_impls.general_tool")


# ── AnswerGeneralTool ──

class AnswerGeneralTool(BaseTool):
    """Answer general/chat questions without querying the database."""

    name = "answer_general"
    description = (
        "回答通用/闲聊类问题，不需要查询数据库。"
        "适用于问候语、概念解释、非数据类问题。"
    )
    schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "通用问题",
            },
        },
        "required": ["question"],
    }
    when_to_use = "用户问题是闲聊、问候、概念解释，不需要查库或文档"
    when_not_to_use = "问题需要查询数据库或文档知识库"

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        question = kwargs.get("question", "")

        # 暂用旧的 answer_general_qa + AgentState 方式（后续改为 answer_general_direct）
        from backend.services.agentic_qa.agents.general_agent import answer_general_qa as _answer_general
        from backend.services.agentic_qa.state import AgentState

        state: AgentState = {
            "question": question,
            "normalized_question": question,
            "session_memory": {"history": []},
            "session_id": ctx.session_id,
            "final_answer": None,
            "sql": None,
            "sql_valid": True,
            "sql_error": None,
            "query_results": None,
            "result_groups": None,
            "analysis_suggestions": None,
            "analysis_chart": None,
            "messages": [],
            "steps": [],
            "intent": "general_qa",
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
            state = _answer_general(state, {})
            return {"answer": state.get("final_answer", "")}
        except Exception as e:
            logger.error(f"[AnswerGeneralTool] error: {e}")
            return {"answer": f"抱歉，处理失败: {e}"}
