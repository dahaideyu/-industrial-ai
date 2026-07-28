# cython: annotation_typing=False, infer_types=False, language_level=3
"""数据分析 Agent — 推理数据洞察、生成图表配置"""
import json
import re
from typing import Optional
from langgraph.config import RunnableConfig
from backend.services.agentic_qa.state import AgentState
from backend.services.agentic_qa.state import _push_step
from backend.core.agentic_qa.llm import llm
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("agents.analysis")

ANALYSIS_SYSTEM = """你是一个工业数据分析师。根据查询结果给出数据洞察，必要时生成图表配置。

## 任务
1. 根据"当前分析任务"的指引，对数据进行针对性分析
2. 发现数据中的规律：趋势、异常、占比、对比、高发时段等
3. 如果数据适合可视化且分析任务需要图表，生成图表配置
4. 用 2-4 句话总结关键洞察，必须有具体数字支撑

## 图表适用场景
- 柱状图(bar)：类型对比、排名（如各故障类型频次）
- 折线图(line)：时间趋势（如每日故障数随时间变化）
- 饼图(pie)：占比分布（如各车间故障占比）

## 输出格式（严格JSON）
{
  "insights": "数据洞察，2-4句话中文，包含具体数字",
  "chart": {
    "type": "bar",
    "title": "图表标题",
    "x_key": "数据中用作X轴的字段名",
    "y_key": "数据中用作Y轴的字段名",
    "data": [{"x_key值": y_key值}, ...]
  }
}

## 规则
- 数据量过少（<2行）或只有单维度时不生成图表，chart 设为 null
- 当数据字段较多时，选择当前分析任务最相关的维度来做图表
- chart.data 只包含图表渲染所需的聚合数据（不超过30条），不要塞入全部原始数据
- insights 要具体、有数字支撑，不要泛泛而谈。例如"近30天共报修42次，其中电器故障占38%（16次），是最高频的故障类型"
- 如果原始数据是明细列表而分析任务是趋势，先对数据做逻辑聚合（如按日期/类型分组计数）再给出结论和图表
- 只输出 JSON，不要任何其他文本"""


def analyze_data(state: AgentState, config: Optional[RunnableConfig] = None) -> AgentState:
    question = state["question"]
    sql = state.get("sql", "")
    results = state.get("query_results") or []
    session_memory = state.get("session_memory") or {}
    history = session_memory.get("history", [])

    # 路径B: 从 session_memory 取上次查询数据，并理解用户的分析意图
    last_query = session_memory.get("last_query")
    analysis_focus = ""
    analysis_data_desc = ""

    if last_query and (not results or len(results) == 0):
        # 优先使用 result_groups（分组数据），fallback 到 flat results
        result_groups = last_query.get("result_groups")
        if result_groups and len(result_groups) > 1:
            best_group = max(result_groups, key=lambda g: g.get("rows", 0))
            results = best_group.get("results") or []
            analysis_data_desc = (
                f"本次查询共{len(result_groups)}个结果集，"
                f"当前分析的是数据量最大的一个（{best_group.get('rows', 0)}条）"
            )
            sql = last_query.get("sql", sql)
        else:
            results = last_query.get("results") or []
            sql = last_query.get("sql", sql)

        if not question or question.strip() in ("分析", "分析一下", "分析数据"):
            suggestions = session_memory.get("analysis_suggestions", [])
            if suggestions:
                analysis_focus = suggestions[0]
            question = last_query.get("question", question)
        else:
            analysis_focus = _extract_analysis_focus(question)
            question = last_query.get("question", question)

    if not results:
        return {**state, "final_answer": "查询未返回数据，无法进行数据分析。请尝试调整查询条件后重新提问。"}

    _push_step(state, config, {"step": "analyzing_data", "status": "in_progress",
                        "message": f"正在分析数据{f'（{analysis_focus}）' if analysis_focus else ''}..."})

    is_enriched = bool(re.search(r'基于".*?"的查询结果[，,]', question))
    context_intro = ""
    if analysis_focus:
        if is_enriched:
            context_intro = f"（基于上一轮查询结果，聚焦: {analysis_focus}）"
    elif analysis_data_desc:
        context_intro = f"（{analysis_data_desc}）"

    # 构建对话历史
    history_context = ""
    if history:
        history_lines = ["## 之前的对话"]
        for i, h in enumerate(history[-3:], 1):
            history_lines.append(f"{i}. 用户: {h.get('question', '')}")
            a = h.get("answer", "")
            if a:
                history_lines.append(f"   AI: {a[:100]}{'...' if len(a) > 100 else ''}")
        history_context = "\n".join(history_lines) + "\n\n"

    data_json = _build_data_summary(results)

    # 数据和分析任务放在 user_prompt 中，system_prompt 仅保留角色行为指令
    user_prompt = """{}## 原始用户问题
{}

## 当前分析任务
{}

## 本次分析的SQL
{}

## 待分析数据（共 {} 条）
{}

请分析以上数据，严格按JSON格式输出洞察和图表配置。""".format(history_context, question, analysis_focus or '根据数据特征进行综合分析', sql, len(results), data_json)

    try:
        response = llm.chat_once(
            user_prompt=user_prompt,
            system_prompt=ANALYSIS_SYSTEM,
            temperature=0.2,
            max_tokens=4000,
        )
        parsed = _parse_analysis_response(response)
        insights = parsed.get("insights") or ""
        chart_config = parsed.get("chart")

        if not insights:
            logger.warning(f"[analysis] LLM returned empty insights. "
                           f"raw_response_len={len(response)} "
                           f"raw_first_300={response[:300]}")

        logger.info(
            f"[analysis] insights: {insights[:100]}... "
            f"chart={chart_config['type'] if chart_config else 'none'}"
        )

        _push_step(state, config, {"step": "analyzing_data", "status": "done",
                            "message": "数据分析完成"})

        if context_intro:
            insights = f"{context_intro}\n\n{insights}"

        # 清除分析建议，防止二次分析循环
        session_memory.pop("analysis_suggestions", None)
        session_memory.pop("analysis_data_desc", None)

        result: dict = {
            **state,
            "final_answer": insights,
            "session_memory": session_memory,
        }
        if chart_config:
            result["analysis_chart"] = chart_config
        return result

    except Exception as e:
        logger.error(f"[analysis] failed: {e}")
        return {**state, "final_answer": f"数据分析失败: {e}"}


def _extract_analysis_focus(question: str) -> str:
    """从 enriched 问题中提取纯分析意图。

    输入: '基于"XXX"的查询结果，分析每日故障报修趋势...'
    输出: '分析每日故障报修趋势...'
    """
    match = re.search(r'基于".*?"的查询结果[，,]\s*(.*)', question)
    if match:
        return match.group(1).strip()
    cleaned = re.sub(r'^基于[^，,]*[，,]\s*', '', question)
    return cleaned


def _build_data_summary(results: list) -> str:
    """构建数据摘要JSON，截断大结果集"""
    max_chars = 3000
    summary = json.dumps(results[:50], ensure_ascii=False, default=str)
    if len(summary) > max_chars:
        summary = summary[:max_chars] + f"... (共{len(results)}条)"
    return summary


def _parse_analysis_response(response: str) -> dict:
    """解析LLM返回的JSON，处理markdown包裹和格式问题"""
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```\w*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {"insights": cleaned[:500] if cleaned.strip() else "", "chart": None}


# ============================================================
# 纯函数（不依赖 AgentState）— 供外部直接调用
# ============================================================

def analyze_data_direct(question: str, query_results: list) -> dict:
    """纯数据分析函数，不依赖 AgentState。

    Args:
        question: 用户问题或分析意图
        query_results: 查询结果列表（dict 列表）

    Returns:
        {"insights": str, "chart": dict | None}
    """
    if not query_results:
        return {"insights": "查询未返回数据，无法进行数据分析。", "chart": None}

    data_json = _build_data_summary(query_results)

    user_prompt = """## 原始用户问题
{}

## 当前分析任务
根据数据特征进行综合分析

## 待分析数据（共 {} 条）
{}

请分析以上数据，严格按JSON格式输出洞察和图表配置。""".format(question, len(query_results), data_json)

    try:
        response = llm.chat_once(
            user_prompt=user_prompt,
            system_prompt=ANALYSIS_SYSTEM,
            temperature=0.2,
            max_tokens=4000,
        )
        parsed = _parse_analysis_response(response)
        insights = parsed.get("insights") or ""
        chart_config = parsed.get("chart")

        if not insights:
            logger.warning(f"[analyze_data_direct] LLM returned empty insights")

        logger.info(
            f"[analyze_data_direct] insights: {insights[:100]}... "
            f"chart={chart_config['type'] if chart_config else 'none'}"
        )

        return {"insights": insights, "chart": chart_config}

    except Exception as e:
        logger.error(f"[analyze_data_direct] failed: {e}")
        return {"insights": f"数据分析失败: {e}", "chart": None}
