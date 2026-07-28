# cython: annotation_typing=False, infer_types=False, language_level=3
"""RAG tool: query_rag."""
from typing import Any, Dict

from backend.core.agentic_qa.logger import get_logger
from backend.services.agentic_qa.base_tool import BaseTool, ToolContext

logger = get_logger("agentic_qa.tool_impls.rag_tool")


# ── QueryRagTool ──

class QueryRagTool(BaseTool):
    """Query RAGFlow document knowledge base."""

    name = "query_rag"
    description = (
        "查询 RAGFlow 文档知识库，获取基于文档的回答。"
        "适用于文档/法规/标准类问题，或需要引用文档内容的场景。"
    )
    schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "要在文档中搜索的问题",
            },
        },
        "required": ["question"],
    }
    when_to_use = "用户问题涉及文档、法规、标准、操作规范等知识库内容"
    when_not_to_use = "问题需要查询数据库实时数据，或属于闲聊/概念解释"

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        question = kwargs.get("question", "")

        # 暂用旧的 query_rag + AgentState 方式（后续改为 query_rag_direct）
        from backend.services.agentic_qa.agents.rag_agent import query_rag as _query_rag
        from backend.services.agentic_qa.state import AgentState

        state: AgentState = {
            "question": question,
            "normalized_question": question,
            "rag_answer": None,
            "rag_thinking": None,
            "rag_references": None,
            "final_answer": None,
            "session_memory": {},
            "session_id": ctx.session_id,
            "sql": None,
            "sql_valid": True,
            "sql_error": None,
            "query_results": None,
            "result_groups": None,
            "analysis_suggestions": None,
            "analysis_chart": None,
            "messages": [],
            "steps": [],
            "intent": "doc_query",
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
            "user_role": "admin",
            "use_rag": True,
        }
        try:
            state = _query_rag(state, {})
            return {
                "answer": state.get("rag_answer", ""),
                "references": state.get("rag_references"),
                "thinking": state.get("rag_thinking"),
            }
        except Exception as e:
            logger.error(f"[QueryRagTool] error: {e}")
            return {"answer": f"RAG查询失败: {e}", "references": None, "thinking": None}
