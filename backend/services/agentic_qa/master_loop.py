# cython: annotation_typing=False, infer_types=False, language_level=3
# backend/services/agentic_qa/master_loop.py
"""Master LLM ReAct Loop — 基于 ToolRegistry + ToolContext 的简化编排 + LLM streaming + 增强日志"""
import asyncio
import json
import time
from typing import Any, Dict, List, Optional
from backend.core.agentic_qa.llm import llm
from backend.core.agentic_qa.logger import get_logger
from backend.services.agentic_qa.base_tool import ToolContext, ToolRegistry, StepBuilder
from backend.services.agentic_qa.tool_impls import ALL_TOOLS
from backend.services.agentic_qa.master_prompt import build_system_prompt
from backend.services.agentic_qa.preprocess import assemble_context, format_pre_context
from backend.services.agentic_qa.blueprint import format_blueprint_section
from backend.services.agentic_qa.memory import get_memory_hub
from backend.services.agentic_qa.agent_state import AgentState

logger = get_logger("agentic_qa.master_loop")

# 创建全局 ToolRegistry 并注册所有 Tool
_registry = ToolRegistry()
for _tool in ALL_TOOLS:
    _registry.register(_tool)


async def run_master_loop(
    question: str,
    session_id: str,
    step_callback=None,
    conversation_history: str = "",
    conversation_history_list: List[Dict] = None,
    session_memory: Dict = None,
) -> Dict[str, Any]:
    """Main ReAct loop — Plan + 并行执行 + 自我评估。"""
    t0 = time.time()
    sm = session_memory or {}
    confirmed = sm.get("confirmed_entities", [])

    logger.info(f"[master_loop] START session={session_id} question='{question[:100]}' confirmed={bool(confirmed)}")

    # 1. 预处理
    asm_ctx = await assemble_context(question, sm, skip_extraction=bool(confirmed), step_callback=step_callback)

    exclude_tools = {"search_entities"} if confirmed else set()
    tool_guidance = _registry.prompt_section(exclude=exclude_tools)
    system_prompt = build_system_prompt(tool_guidance, session_id, conversation_history)

    pre_text = format_pre_context(asm_ctx)
    if pre_text:
        system_prompt += "\n\n## 预处理上下文（可直接使用）\n" + pre_text

    blueprint = asm_ctx.get("query_blueprint")
    if blueprint:
        blueprint_text = format_blueprint_section(blueprint)
        if blueprint_text:
            system_prompt += "\n\n" + blueprint_text

    if confirmed:
        lines = []
        for ec in confirmed:
            field = ec.get("field", ec.get("entity_type", "实体"))
            raw = ec.get("values") or ec.get("selected_values")
            if not raw:
                v = ec.get("value")
                raw = [v] if v else []
            if raw:
                lines.append(f"- {field}: {', '.join(str(v) for v in raw)}")
        if lines:
            system_prompt += (
                "\n\n## 已确认实体（权威上下文）\n"
                + "\n".join(lines)
                + "\n\n用户已确认上述实体，请直接查 schema、生成 SQL、执行查询。"
            )

    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history_list:
        for h in conversation_history_list[-5:]:
            hq = h.get("question", "")
            ha = h.get("answer", "")
            hs = h.get("sql", "")
            messages.append({"role": "user", "content": hq})
            asst_content = ha
            if hs:
                asst_content = f"{ha}\n\n<!-- 上轮SQL: {hs[:500]} -->"
            messages.append({"role": "assistant", "content": asst_content})

    messages.append({"role": "user", "content": question})

    # 2. 构建状态和上下文
    memory_hub = get_memory_hub(session_id)
    tool_context = ToolContext(
        session_id=session_id,
        memory_hub=memory_hub,
        step_callback=step_callback,
        confirmed_entities=confirmed,
        entity_candidates=asm_ctx.get("entity_candidates", {}),
    )
    state = AgentState(question=question, session_id=session_id)

    # 3. Plan 阶段（明显简单的查询跳过，省一次 LLM 往返降延迟）
    if _is_simple_query(question):
        logger.info("[master_loop] SKIP plan stage (simple query)")
    else:
        plan_text = await _generate_plan(state, messages)
        if plan_text:
            messages[0]["content"] += f"\n\n## 查询计划（执行参考）\n{plan_text}\n\n⚠ 如果实际执行发现计划不可行，请调整策略并说明原因。"

    # 4. ReAct 循环
    final_followups: List[str] = []

    while True:
        # LLM 调用
        try:
            response, thinking_text = await _llm_stream_call(messages, step_callback, session_id, exclude_tools)
        except Exception as e:
            logger.error(f"[master_loop] LLM call failed: {e}")
            try:
                response = _llm_tool_call(messages, exclude_tools)
                thinking_text = ""
            except Exception as e2:
                logger.error(f"[master_loop] LLM fallback also failed: {e2}")
                break

        message = response.choices[0].message
        content = message.content or ""
        tool_calls = getattr(message, "tool_calls", None) or []

        # 无 tool_calls → 最终回答
        if not tool_calls:
            state.final_answer = content
            followups = _parse_followups(content)
            final_followups = followups if "## 追问建议" in (content or "") else []
            if followups:
                state.final_answer = content.split("## 追问建议")[0].strip()
            await _push_step(step_callback, {
                "id": "final_answer", "type": "final_answer",
                "title": "生成回答", "status": "done",
                "detail": state.final_answer[:200], "elapsed_ms": 0, "attempt": 1,
            })
            messages.append({"role": "assistant", "content": content})
            logger.info(f"[master_loop] FINAL_ANSWER len={len(state.final_answer)}")
            break

        # 追加 assistant 消息
        messages.append({"role": "assistant", "content": content, "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in tool_calls
        ]})

        # 推送 running 状态
        for tc in tool_calls:
            await _push_step(step_callback, StepBuilder.build(
                tc.function.name, "running",
                StepBuilder.running_detail(tc.function.name), attempt=1
            ))

        # 并行执行工具
        t_start = time.time()
        tool_results = await _execute_tools_parallel(tool_calls, state, tool_context)
        elapsed = round((time.time() - t_start) * 1000)

        # 处理结果 + 反思
        for tc, result in tool_results:
            tool_name = tc.function.name if hasattr(tc, 'function') else "unknown"
            is_error = bool(result.get("error"))

            # ask_clarification 立即返回
            if tool_name == "ask_clarification" or result.get("action") == "pause_for_clarification":
                await _push_step(step_callback, StepBuilder.build(
                    tool_name, "done",
                    StepBuilder.detail_for_result(tool_name, result),
                    elapsed_ms=elapsed, attempt=1
                ))
                msg = result.get("message", "需要更多信息")
                return {
                    "answer": msg, "sql": state.last_sql, "chart": state.final_chart,
                    "needs_clarification": True,
                    "clarification_message": msg,
                    "clarification_groups": result.get("groups"),
                    "clarification_options": result.get("options"),
                    "source": "agentic_qa",
                }

            # step 推送
            status = "error" if is_error else "done"
            detail = StepBuilder.detail_for_result(tool_name, result) if not is_error else str(result["error"])[:120]
            step_dict = StepBuilder.build(tool_name, status, detail, elapsed_ms=elapsed, attempt=1)
            if is_error:
                step_dict["error"] = {"message": str(result["error"])[:120]}
            await _push_step(step_callback, step_dict)

            # 日志
            result_summary = _summarize_result(tool_name, result)
            logger.info(f"[master_loop] {tool_name} {'ERROR' if is_error else 'OK'} elapsed={elapsed}ms result={result_summary[:150]}")

            # execute_sql 成功后添加提示
            if tool_name == "execute_sql" and result.get("success"):
                result["_hint"] = "数据已获取。请直接在 content 中用中文整理回答用户问题，不要再调用任何工具。"

            # 追加 tool result 到 messages（必须在反思之前，保持 API 消息顺序）
            result_json = json.dumps(result, ensure_ascii=False, default=str)
            if len(result_json) > 16000:
                result_json = result_json[:16000] + f"...(截断, 共{len(result_json)}字符)"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_json,
            })

            # 反思（在 tool result 之后追加，避免违反 API 消息顺序）
            if should_reflect(tool_name, result):
                try:
                    reflection = await _reflect(tool_name, result, state, messages)
                    messages.append({"role": "assistant", "content": f"[反思] {reflection}"})
                except Exception as e:
                    logger.warning(f"[master_loop] reflect failed: {e}")

        # 停止检查
        should_stop, reason = state.check_should_stop()
        if should_stop:
            logger.info(f"[master_loop] STOP reason={reason}")
            break

    # 5. 结论生成（有数据就必须有结论）
    elapsed = round((time.time() - t0) * 1000)

    if state.last_query_results and len(state.last_query_results) > 0:
        has_substantial_answer = (
            state.final_answer
            and len(state.final_answer) > 50
            and not state.final_answer.startswith("查询返回")
        )
        if not has_substantial_answer:
            try:
                # 构建数据摘要（更多数据、更完整的上下文）
                sample = state.last_query_results[:20]
                sample_json = json.dumps(sample, ensure_ascii=False, default=str)[:5000]
                total = len(state.last_query_results)

                # 如果有分析洞察，一并提供给 LLM 做结论整合
                analysis_hint = ""
                if state.final_answer and len(state.final_answer) > 10:
                    analysis_hint = f"\n\n已有分析参考（请基于此整合为完整结论）:\n{state.final_answer[:1500]}"

                messages.append({"role": "user", "content":
                    f"查询已返回 {total} 条数据。请基于以下数据用中文直接回答用户的问题。"
                    f"要求：\n"
                    f"1. 结论先行，先给核心发现\n"
                    f"2. 说人话，面向现场人员\n"
                    f"3. 包含关键数据支撑\n"
                    f"4. 末尾附 '## 追问建议' 区域\n"
                    f"不要调用任何工具。{analysis_hint}\n\n"
                    f"数据样本（共{total}条，展示前{len(sample)}条）:\n{sample_json}"})
                all_tools = set(_registry.tools.keys())
                response, _ = await _llm_stream_call(messages, step_callback, session_id, all_tools)
                answer_content = response.choices[0].message.content or ""
                if answer_content.strip():
                    state.final_answer = answer_content
                    followups = _parse_followups(answer_content)
                    if followups:
                        state.final_answer = answer_content.split("## 追问建议")[0].strip()
                    final_followups = followups if "## 追问建议" in answer_content else []
            except Exception as e:
                logger.warning(f"[master_loop] conclusion generation failed: {e}")

    if not state.final_answer and state.last_query_results:
        state.final_answer = f"查询返回 {len(state.last_query_results)} 条数据。"
    if not state.final_answer:
        state.final_answer = "抱歉，多次尝试后仍无法获取正确数据。请尝试换个方式描述你的问题。"

    # 持久化
    if state.last_sql:
        memory_hub.update_session("last_query", {"sql": state.last_sql, "data": state.last_query_results})

    elapsed = round((time.time() - t0) * 1000)
    success = bool(state.last_query_results) or (bool(state.final_answer) and not state.final_answer.startswith("抱歉"))
    logger.info(f"[master_loop] END session={session_id} elapsed={elapsed}ms success={success} "
                f"answer_len={len(state.final_answer)} steps={len(state.executed_steps)}")

    return {
        "answer": state.final_answer,
        "sql": str(state.last_sql) if state.last_sql else None,
        "results": state.last_query_results,
        "result_groups": state.build_result_groups(),
        "chart": state.final_chart,
        "followups": final_followups,
        "needs_clarification": False,
        "source": "agentic_qa",
        "elapsed_ms": elapsed,
    }


def _llm_tool_call(messages: list, exclude_tools: set = None):
    """Call LLM with native tool calling (non-streaming)."""
    params = {
        "model": llm.model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 8192,
        "tools": _registry.all_schemas(exclude=exclude_tools),
        "tool_choice": "auto",
    }
    return llm.client.chat.completions.create(**params)


async def _llm_stream_call(messages: list, step_callback, session_id: str, exclude_tools: set = None):
    """流式调用 LLM，实时推送思考内容。返回 (complete_response, thinking_text)。"""
    try:
        stream = llm.client.chat.completions.create(
            model=llm.model,
            messages=messages,
            temperature=0.1,
            max_tokens=8192,
            tools=_registry.all_schemas(exclude=exclude_tools),
            tool_choice="auto",
            stream=True,
        )
    except Exception as e:
        logger.warning(f"[master_loop] streaming not supported, fallback to non-streaming: {e}")
        return _llm_tool_call(messages, exclude_tools), ""

    thinking_text = ""
    tool_calls_buffer = {}
    content_parts = []

    try:
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # DeepSeek reasoning_content（深度思考，优先使用）
            reasoning = getattr(delta, 'reasoning_content', None)
            if reasoning:
                thinking_text += reasoning
                await _push_step(step_callback, {
                    "type": "thinking_chunk",
                    "content": reasoning,
                })

            # 普通文本内容
            if delta.content:
                content_parts.append(delta.content)
                if not reasoning:
                    thinking_text += delta.content
                    await _push_step(step_callback, {
                        "type": "thinking_chunk",
                        "content": delta.content,
                    })

            # 工具调用（累积参数）
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index if hasattr(tc, 'index') else 0
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                    if tc.function:
                        if tc.function.name:
                            tool_calls_buffer[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_buffer[idx]["arguments"] += tc.function.arguments
    except Exception as e:
        logger.warning(f"[master_loop] streaming interrupted, using partial result: {e}")

    # thinking 结束
    if thinking_text:
        await _push_step(step_callback, {"type": "thinking_end"})

    # 构造完整的 response 对象（模拟 OpenAI API 返回格式）
    from types import SimpleNamespace

    complete_tool_calls = []
    for idx in sorted(tool_calls_buffer.keys()):
        tc_data = tool_calls_buffer[idx]
        if tc_data["name"]:  # 只有有名字的才是有效的 tool call
            complete_tool_calls.append(SimpleNamespace(
                id=tc_data["id"] or f"call_{idx}",
                type="function",
                function=SimpleNamespace(
                    name=tc_data["name"],
                    arguments=tc_data["arguments"],
                ),
            ))

    logger.info(f"[master_loop] streaming done: thinking_len={len(thinking_text)} content_len={len(''.join(content_parts))} tool_calls={len(complete_tool_calls)}")

    message = SimpleNamespace(
        content="".join(content_parts) if content_parts else None,
        tool_calls=complete_tool_calls if complete_tool_calls else None,
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
    )

    return response, thinking_text


def _parse_followups(text: str) -> List[str]:
    """从回答文本中解析 ## 追问建议 区域"""
    if not text or "## 追问建议" not in text:
        return []
    parts = text.split("## 追问建议", 1)
    if len(parts) < 2:
        return []
    followup_text = parts[1].strip()
    items = []
    for line in followup_text.split("\n"):
        line = line.strip().removeprefix("- ").removeprefix("* ").strip()
        if line and not line.startswith("#"):
            items.append(line)
    return items[:3]


async def _push_step(callback, step: dict):
    if callback:
        try:
            await callback(step)
        except Exception:
            pass


def _summarize_result(tool_name: str, result: dict) -> str:
    """为日志生成 tool result 摘要"""
    if result.get("error"):
        return f"ERROR: {str(result['error'])[:100]}"
    if tool_name == "execute_sql":
        return f"rows={result.get('row_count', 0)}"
    if tool_name == "generate_sql":
        sql = result.get("sql", "")
        return f"sql_len={len(sql)} success={result.get('success')}"
    if tool_name == "search_entities":
        return f"entities={len(result.get('entities', []))}"
    if tool_name == "analyze_data":
        insights = result.get("insights", "")
        return f"insights_len={len(insights)}"
    return json.dumps(result, ensure_ascii=False, default=str)[:100]


# ── Plan 阶段 ──

# 简单查询判定：用于跳过 Plan 阶段降低延迟。判定保守——只有“短问题 + 无分析意图 +
# 非复合问句”才算简单，宁可不跳（多花一次 Plan）也不把复杂查询误判为简单。
_ANALYSIS_INTENT_WORDS = (
    "对比", "比较", "趋势", "变化", "为什么", "原因", "分析", "排名", "排行",
    "分布", "占比", "环比", "同比", "关联", "预测", "异常", "诊断",
    "最高", "最低", "最多", "最少", "排序", "汇总", "统计", "top",
)


def _is_simple_query(question: str) -> bool:
    """是否为可跳过 Plan 的简单查询（保守判定）。"""
    q = (question or "").strip()
    if not q or len(q) > 30:
        return False
    low = q.lower()
    if any(w in low for w in _ANALYSIS_INTENT_WORDS):
        return False
    # 复合/多步问句（“先…再…”、“并且”、多个问号）通常不简单
    if any(sep in q for sep in ("先", "再", "并且", "以及", "然后", "；", ";")):
        return False
    if q.count("？") + q.count("?") > 1:
        return False
    return True


PLAN_PROMPT = """请分析这个问题并制定查询计划。不要调用任何工具，只输出分析。

用以下格式输出：

**问题理解**：[用户想查什么，涉及哪些实体，实体类型是什么]
**涉及实体**：[从问题和预处理上下文中识别的实体及其类型]
**查询策略**：
1. [第一步：查什么表，用什么条件]
2. [第二步：如果需要关联，怎么关联]
**可能的风险**：[实体名可能不匹配？表里可能没数据？]
**成功标准**：[什么算查到了有效数据]"""


async def _generate_plan(state, messages: list) -> str:
    """首轮：LLM 输出查询计划（不给工具）。返回计划文本。"""
    plan_messages = messages + [{"role": "user", "content": PLAN_PROMPT}]

    response = llm.client.chat.completions.create(
        model=llm.model,
        messages=plan_messages,
        temperature=0.1,
        max_tokens=2048,
    )
    plan_text = response.choices[0].message.content or ""
    state.plan_text = plan_text
    logger.info(f"[master_loop] PLAN len={len(plan_text)} preview={plan_text[:100]}")
    return plan_text


# ── 并行工具执行 ──

async def _execute_tools_parallel(tool_calls, state, tool_context) -> list:
    """并行执行多个 tool calls。返回 [(tc, result_dict), ...]"""
    tasks = []
    tc_list = []
    skipped = []

    for tc in tool_calls:
        fn = tc.function
        tool_name = fn.name
        try:
            tool_args = json.loads(fn.arguments)
        except json.JSONDecodeError as e:
            logger.warning(f"[master_loop] tool={tool_name} malformed args: {e}")
            tool_args = {}

        if tool_name not in _registry.tools:
            skipped.append((tc, {"error": f"未知工具: {tool_name}"}))
            logger.warning(f"[master_loop] UNKNOWN_TOOL={tool_name}")
            continue

        tool_args.pop("session_id", None)
        tool = _registry.get(tool_name)
        tasks.append(tool.run(ctx=tool_context, **tool_args))
        tc_list.append(tc)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    tool_results = []
    for tc, result in zip(tc_list, results):
        if isinstance(result, Exception):
            logger.error(f"[master_loop] tool {tc.function.name} FAILED: {result}")
            result = {"error": str(result)}
        state.record_tool_result(tc.function.name, result)
        tool_results.append((tc, result))

    tool_results.extend(skipped)
    return tool_results


# ── 自我评估 + 动态策略 ──

REFLECT_TOOLS = {"execute_sql", "search_entities", "diagnose_sql_error"}

REFLECT_PROMPT = """你刚才执行了 {tool_name}，结果如下：
{result_summary}

请反思：
1. 这个结果是否符合预期？
2. 如果不符合，可能的原因是什么？
3. 下一步应该怎么做？

输出格式：
**判断**：[符合预期 / 不符合预期，原因]
**下一步策略**：[具体行动]
**是否需要调整计划**：[是/否，如果需要，说明调整方向]"""


def should_reflect(tool_name: str, result: dict) -> bool:
    """是否需要反思这个 tool result"""
    if tool_name not in REFLECT_TOOLS:
        return False
    if tool_name == "execute_sql":
        row_count = result.get("row_count", 0)
        return row_count == 0 or row_count > 1000
    if tool_name == "search_entities":
        return len(result.get("entities", [])) == 0
    return True


async def _reflect(tool_name: str, result: dict, state, messages: list) -> str:
    """反思工具结果，输出下一步策略"""
    result_summary = json.dumps(result, ensure_ascii=False, default=str)[:500]
    prompt = REFLECT_PROMPT.format(tool_name=tool_name, result_summary=result_summary)

    reflect_messages = messages + [{"role": "user", "content": prompt}]

    response = llm.client.chat.completions.create(
        model=llm.model,
        messages=reflect_messages,
        temperature=0.1,
        max_tokens=1024,
    )
    reflection = response.choices[0].message.content or ""

    state.strategy_history.append(reflection[:200])
    logger.info(f"[master_loop] REFLECT tool={tool_name} len={len(reflection)}")
    return reflection
