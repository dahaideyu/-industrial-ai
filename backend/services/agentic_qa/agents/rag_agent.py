# cython: annotation_typing=False, infer_types=False, language_level=3
"""LangGraph RAG Agent 节点 — 流式调用 RAGFlow 进行文档问答"""
from typing import Optional
from langgraph.config import RunnableConfig
from backend.services.agentic_qa.state import AgentState
from backend.services.agentic_qa.ragflow.client import ragflow_client
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("agents.rag")


def query_rag(state: AgentState, config: Optional[RunnableConfig] = None) -> AgentState:
    """流式查询 RAGFlow 聊天助手，推送增量文本块到前端，并保留引用信息"""
    question = state["normalized_question"] or state["question"]
    logger.info(f"[rag] streaming query: '{question[:60]}'")

    state["steps"].append({
        "step": "querying_rag",
        "status": "in_progress",
        "message": "正在查阅文档知识库..."
    })

    # 获取 step_callback（用于向前端推送流式增量块）
    step_cb = None
    if config:
        step_cb = config.get("configurable", {}).get("step_callback")

    # 收集流式增量块
    streamed_chunks = []

    def on_rag_chunk(delta: str):
        """RAGFlow 流式回调：仅累积，不推送增量块（改为前端打字机效果）"""
        streamed_chunks.append(delta)
        # 不再逐块推送 step_cb，避免 WebSocket 传输碎片化导致的中断
        # 前端通过 HTTP 响应获取完整 answer 后用打字机效果模拟流式输出

    try:
        # 默认回退到 settings.ragflow_chat_id（旧行为）；若上游提供 chat_id 则透传
        from backend.core.agentic_qa.config import settings as _settings
        rag_chat_id = state.get("rag_chat_id") or _settings.ragflow_chat_id
        result = ragflow_client.chat_sync(
            question=question,
            chat_id=rag_chat_id,
            on_chunk=on_rag_chunk,
        )

        if result.get("success"):
            answer = result["answer"]
            thinking = result.get("thinking", "")
            references = result.get("references")

            logger.info(f"[rag] answer={len(answer)}chars thinking={len(thinking)}chars "
                        f"refs={references.get('total', 0) if references else 0}")

            # 推送最终完成步骤
            if step_cb:
                try:
                    step_cb({
                        "step": "rag_stream",
                        "status": "done",
                        "message": "",
                        "references": references,
                        "thinking": thinking,
                    })
                except Exception:
                    pass

            state["steps"][-1]["status"] = "done"
            state["steps"][-1]["message"] = "文档查询完成"

            return {
                **state,
                "rag_answer": answer,
                "rag_thinking": thinking,
                "rag_references": references,
                "final_answer": answer,
            }
        else:
            error = result.get("error", "未知错误")
            logger.error(f"[rag] FAILED: {error}")
            state["steps"][-1]["status"] = "error"
            return {
                **state,
                "rag_answer": None,
                "final_answer": f"文档查询失败: {error}",
            }

    except Exception as e:
        logger.error(f"[rag] exception: {e}")
        state["steps"][-1]["status"] = "error"
        return {
            **state,
            "rag_answer": None,
            "final_answer": f"文档查询异常: {str(e)}",
        }


# ============================================================
# 纯函数（不依赖 AgentState）— 供外部直接调用
# ============================================================

def query_rag_direct(question: str) -> dict:
    """纯 RAG 查询函数，不依赖 AgentState。

    Args:
        question: 用户问题

    Returns:
        {"answer": str, "references": list, "thinking": str}
    """
    logger.info(f"[rag_direct] query: '{question[:60]}'")

    try:
        from backend.core.agentic_qa.config import settings as _settings
        result = ragflow_client.chat_sync(
            question=question,
            chat_id=_settings.ragflow_chat_id,
        )

        if result.get("success"):
            answer = result.get("answer", "")
            thinking = result.get("thinking", "")
            references = result.get("references")
            ref_list = []
            if references:
                ref_list = references.get("chunks", []) if isinstance(references, dict) else []
            logger.info(f"[rag_direct] answer={len(answer)}chars thinking={len(thinking)}chars")
            return {"answer": answer, "references": ref_list, "thinking": thinking}
        else:
            error = result.get("error", "未知错误")
            logger.error(f"[rag_direct] FAILED: {error}")
            return {"answer": f"文档查询失败: {error}", "references": [], "thinking": ""}

    except Exception as e:
        logger.error(f"[rag_direct] exception: {e}")
        return {"answer": f"文档查询异常: {str(e)}", "references": [], "thinking": ""}
