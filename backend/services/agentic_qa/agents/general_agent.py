# cython: annotation_typing=False, infer_types=False, language_level=3
"""通用问答 Agent — 处理闲聊、概念解释等不涉及数据库查询的问题"""
from typing import Optional
from langgraph.config import RunnableConfig
from backend.services.agentic_qa.state import AgentState
from backend.services.agentic_qa.state import _push_step
from backend.services.agentic_qa.agents.entity_resolver import load_custom_metrics
from backend.core.agentic_qa.llm import llm
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("agents.general")

GENERAL_QA_SYSTEM = """你是一个工业数据智能问答助手。

## 角色
你服务于一家工业制造企业，能回答关于设备、产线、维修工单、生产指标等工业领域的问题。

## 回答规则
1. 如果有指标定义上下文，严格基于定义回答
2. 如果没有，结合你的工业知识给出准确、简洁的回答
3. 回答控制在 3-5 句话以内
4. 如果问题超出你的知识范围，诚实说明
5. 不要编造数据或统计数字"""


def answer_general_qa(state: AgentState, config: Optional[RunnableConfig] = None) -> AgentState:
    question = state["question"]
    session_memory = state.get("session_memory") or {}
    history = session_memory.get("history", [])

    _push_step(state, config, {"step": "general_qa", "status": "in_progress",
                        "message": "正在检索相关知识和指标定义..."})

    # 搜索自定义指标（如 OEE 等工业指标）
    metrics = load_custom_metrics()
    metric_context = _search_relevant_metrics(question, metrics)

    # 构建系统提示词
    prompt = GENERAL_QA_SYSTEM
    if metric_context:
        prompt = "## 相关指标定义（优先参考）\n" + metric_context + "\n\n" + prompt

    if history:
        history_lines = ["## 之前的对话（用于理解上下文指代）"]
        for i, h in enumerate(history[-3:], 1):
            history_lines.append(f"{i}. 用户: {h.get('question', '')}")
            a = h.get("answer", "")
            if a:
                history_lines.append(f"   AI: {a[:120]}{'...' if len(a) > 120 else ''}")
        prompt = "\n".join(history_lines) + "\n\n" + prompt

    _push_step(state, config, {"step": "general_qa", "status": "done",
                        "message": "正在生成回答..."})

    try:
        response = llm.chat_once(
            user_prompt=question,
            system_prompt=prompt,
            temperature=0.3,
            max_tokens=2048,
        )
        answer = response.strip()
        logger.info(f"[general_qa] answered: {answer[:100]}...")
    except Exception as e:
        logger.error(f"[general_qa] failed: {e}")
        answer = "抱歉，我暂时无法回答这个问题，请稍后再试。"

    return {**state, "final_answer": answer}


def _search_relevant_metrics(question: str, metrics: list) -> str:
    """从自定义指标中搜索与问题相关的内容，返回格式化的指标定义"""
    if not metrics:
        return ""

    question_lower = question.lower()
    matched = []
    for m in metrics:
        name = (m.get("name") or "").lower()
        desc = (m.get("description") or "").lower()
        keywords = (m.get("keywords") or "").lower()
        if any(kw in question_lower for kw in [name, desc, keywords] if kw):
            matched.append(m)
        # keyword 可能包含多个逗号分隔的关键词
        elif keywords:
            for kw in keywords.split(","):
                if kw.strip() and kw.strip() in question_lower:
                    matched.append(m)
                    break

    if not matched:
        # 宽松匹配：检查问题的关键词是否出现在指标定义中
        for m in metrics:
            name = m.get("name", "")
            if name and len(name) >= 2 and name[:2] in question:
                matched.append(m)

    if not matched:
        return ""

    lines = []
    for m in matched[:5]:
        name = m.get("name", "")
        desc = m.get("description", "")
        expr = m.get("sql_expression", "")
        parts = [f"- **{name}**"]
        if desc:
            parts.append(f"  定义: {desc}")
        if expr:
            parts.append(f"  计算公式: {expr}")
        lines.append("\n".join(parts))

    return "\n\n".join(lines)


# ============================================================
# 纯函数（不依赖 AgentState）— 供外部直接调用
# ============================================================

def answer_general_direct(question: str) -> dict:
    """纯通用回答函数，不依赖 AgentState。

    Args:
        question: 用户问题

    Returns:
        {"answer": str}
    """
    # 搜索自定义指标
    metrics = load_custom_metrics()
    metric_context = _search_relevant_metrics(question, metrics)

    # 构建系统提示词
    prompt = GENERAL_QA_SYSTEM
    if metric_context:
        prompt = "## 相关指标定义（优先参考）\n" + metric_context + "\n\n" + prompt

    try:
        response = llm.chat_once(
            user_prompt=question,
            system_prompt=prompt,
            temperature=0.3,
            max_tokens=2048,
        )
        answer = response.strip()
        logger.info(f"[answer_general_direct] answered: {answer[:100]}...")
    except Exception as e:
        logger.error(f"[answer_general_direct] failed: {e}")
        answer = "抱歉，我暂时无法回答这个问题，请稍后再试。"

    return {"answer": answer}
