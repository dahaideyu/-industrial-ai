# cython: annotation_typing=False, infer_types=False, language_level=3
"""共享状态类型定义 — AgentState TypedDict

供 agentic_qa tool_impls 及 agentic_qa agents 共用。
"""
from typing import TypedDict, Annotated, List, Dict, Any, Optional
from langgraph.config import RunnableConfig
from langgraph.graph import add_messages
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("agentic_qa.state")


class AgentState(TypedDict):
    # 用户原始问题
    question: str

    # 归一化后的问题（用于下游 Agent）
    normalized_question: Optional[str]

    # 意图分类
    intent: Optional[str]  # "simple_fact", "aggregation", "multi_hop", "doc_query", "meta", "mixed"
    intent_confidence: Optional[float]

    # 是否需要澄清
    needs_clarification: bool
    clarification_questions: List[str]
    clarification_options: List[Dict[str, str]]  # [{label: "...", value: "..."}] 供前端按钮
    clarification_groups: List[Dict[str, Any]]   # 意图澄清分组选项
    clarification_type: Optional[str]            # "intent" 或 "entity"
    confirmed_clarifications: Optional[List[Dict[str, Any]]]  # 用户澄清选择

    # 自动补全的条件（供前端确认卡片）
    auto_completions: List[Dict[str, str]]  # [{field: "产线", value: "A", default: true}]

    # 实体消歧候选（供前端展示选择列表）
    entity_candidates: List[Dict[str, Any]]
    # [{entity_type, entity_label, mention, candidates: [{label, sublabel, value}], match_count, resolved, source}]

    # 已确认的实体（前端确认后回传，跳过实体检索步骤）
    confirmed_entities: Optional[List[Dict[str, Any]]]
    # [{entity_type, mention, value, label}]

    # 是否强制使用 RAG
    use_rag: bool

    # SQL 相关
    sql: Optional[str]
    sql_valid: bool
    sql_error: Optional[str]

    # 查询结果
    query_results: Optional[List[Dict[str, Any]]]
    result_groups: Optional[List[Dict[str, Any]]]  # 多SQL时每组分开: [{sql, results, rows}]
    analysis_suggestions: Optional[List[str]]       # 分析建议列表

    # RAG 结果
    rag_answer: Optional[str]
    rag_thinking: Optional[str]
    rag_references: Optional[Dict[str, Any]]

    # 数据分析
    analysis_chart: Optional[Dict[str, Any]]  # 图表配置 {type, title, x_key, y_key, data}

    # 最终回答
    final_answer: Optional[str]

    # 对话历史/记忆
    messages: Annotated[list, add_messages]

    # 会话级共享记忆（跨 Agent 继承）
    session_memory: Dict[str, Any]  # { confirmed_entities: [...], time_range: "...", metrics: [...], filters: {...} }

    # 会话信息
    session_id: Optional[str]
    user_role: str

    # 执行步骤记录（用于前端显示过程）
    steps: List[Dict[str, Any]]


def _push_step(state: AgentState, config: Optional[RunnableConfig], step: dict):
    """推送步骤到前端 WebSocket。参数顺序: (state, config, step)"""
    steps = [s for s in state.get("steps", []) if s is not None]
    if steps and steps[-1].get("step") == step.get("step"):
        steps[-1] = step
    else:
        steps.append(step)
    state["steps"] = steps

    logger.info(f"[_push_step] step={step.get('step')} status={step.get('status')} "
                 f"total_steps={len(steps)}")

    # 通过 config 获取回调推送到前端
    if config:
        cb = config.get("configurable", {}).get("step_callback")
        if cb:
            try:
                cb(step)
            except Exception:
                pass
