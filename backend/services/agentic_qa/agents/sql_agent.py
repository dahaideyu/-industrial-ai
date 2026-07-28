# cython: annotation_typing=False, infer_types=False, language_level=3
"""LangGraph SQL Agent — generic NL2SQL using Vanna enhancers + LLM"""
from typing import Union
import json
import re
import time
import asyncio
from typing import Optional
from langgraph.config import RunnableConfig
from backend.services.agentic_qa.state import AgentState
from backend.services.agentic_qa.state import _push_step
from backend.services.agentic_qa.agents.entity_resolver import quick_typo_check
from backend.core.agentic_qa.llm import llm
from backend.services.agentic_qa.db.mysql import db
from backend.services.agentic_qa.vanna.agent import get_vanna_manager
from backend.services.agentic_qa.vanna.guard import validate_sql
from backend.services.agentic_qa.vanna.enhancers import CombinedEnhancer, SchemaContextEnhancer, MemoryRetrievalEnhancer
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("agents.sql")

MULTI_SQL_SEPARATOR = "\n-- NEXT QUERY --\n"

SQL_GENERATION_SYSTEM = """你是一个 MySQL 查询生成助手。

## 核心规则
1. 只生成 SELECT 语句，禁止 INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE
2. 必须使用 LIMIT 限制返回行数（默认 1000）
3. 对 sys_line 和 dev_device 表，必须加 del_flag=0 条件过滤已删除数据
4. 对于计数类查询，同时使用 GROUP_CONCAT 返回名称列表
5. 字符串匹配使用 LIKE
6. **严格遵循训练示例**：如果提示中有相似历史问答对，直接复用其 SQL 结构
7. **只使用提示中列出的表名和字段名**，不要臆造不存在的表或字段
8. **对话连续性（重要）**：如果对话历史中有前序查询，当前问题是基于前序结果的延续分析或追问，则必须复用前序 SQL 中的 WHERE 过滤条件（如实体名称、时间范围等），在此基础上加聚合/排序/分组等分析逻辑
9. **时间范围强制（极其重要）**：查询 dev_repair_order/dev_alarm/dev_maintenance 等带时间戳的表时，**必须**在 WHERE 中加时间范围条件（如 report_time >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)）。禁止无时间限制的全表扫描。若用户未指定时间范围，默认使用最近30天

## 复杂问题处理
如果问题包含多个子问题（如"先查A，再基于A的结果查B的最高频次"），可以生成多条 SQL，每条之间用 `-- NEXT QUERY --` 分隔。

## 输出格式
只输出 SQL 语句本身，不要 markdown 代码块，不要任何解释。
多SQL时用 `-- NEXT QUERY --` 分隔每条SQL。"""


def _run_enhancers(question: str, system_prompt: str) -> tuple:
    """Returns: (enhanced_system_prompt, retrieval_info)"""
    manager = get_vanna_manager()
    enhancer = CombinedEnhancer([
        SchemaContextEnhancer(manager._memory),
        MemoryRetrievalEnhancer(manager._memory),
    ])

    # 检查是否在已有的事件循环中（如 FastAPI），避免 asyncio.run() 冲突
    try:
        asyncio.get_running_loop()
        in_event_loop = True
    except RuntimeError:
        in_event_loop = False

    try:
        if in_event_loop:
            return _run_enhancers_in_thread(enhancer, system_prompt, question)
        else:
            from vanna.core.user.models import User
            user = User(id="admin", username="admin", group_memberships=["admin", "user"])
            result = asyncio.run(enhancer.enhance_system_prompt(system_prompt, question, user))
            ex_count = result.count("参考SQL:") if "参考SQL" in result else 0
            schema_count = result.count("TABLE_SCHEMA:") if "TABLE_SCHEMA" in result else 0
            return result, {"examples": ex_count, "schemas": schema_count}
    except Exception as e:
        logger.warning(f"[sql] enhancer failed: {e}")
        return system_prompt, {"examples": 0, "schemas": 0}


def _run_enhancers_in_thread(enhancer, system_prompt: str, question: str) -> tuple:
    """在独立线程中用新 event loop 运行 enhancer"""
    import concurrent.futures
    def _run():
        loop = asyncio.new_event_loop()
        try:
            user_obj = type('User', (), {
                'id': 'admin', 'username': 'admin', 'group_memberships': ['admin', 'user']
            })()
            return loop.run_until_complete(
                enhancer.enhance_system_prompt(system_prompt, question, user_obj)
            )
        finally:
            loop.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        result = ex.submit(_run).result(timeout=15)
    ex_count = result.count("参考SQL:") if "参考SQL" in result else 0
    schema_count = result.count("TABLE_SCHEMA:") if "TABLE_SCHEMA" in result else 0
    return result, {"examples": ex_count, "schemas": schema_count}


def _clean_sql(raw: str) -> str:
    sql = raw.strip()
    if sql.startswith("```sql"):
        sql = sql[7:]
    elif sql.startswith("```"):
        sql = sql[3:]
    if sql.endswith("```"):
        sql = sql[:-3]
    return sql.strip()


def generate_sql(state: AgentState, config: Optional[RunnableConfig] = None) -> AgentState:
    question = state["normalized_question"] or state["question"]
    t0 = time.time()

    # Step: enhance context (retrieve memory + schemas)
    _push_step(state, config, {"step": "retrieving_memory", "status": "in_progress",
                        "message": "正在从记忆库检索相关知识和表结构..."})
    t1 = time.time()

    enhanced_system, retrieval_info = _run_enhancers(question, SQL_GENERATION_SYSTEM)

    # 注入对话历史上下文
    session_memory = state.get("session_memory") or {}
    history = session_memory.get("history", [])
    last_query = session_memory.get("last_query")

    if history or last_query:
        history_lines = ["## 对话历史（本会话中之前的问答）", ""]

        # 如果存在 last_query（上一轮的实际 SQL+结果），优先提供精准上下文
        if last_query:
            prev_sql = last_query.get("sql", "")
            prev_question = last_query.get("question", "")
            history_lines.append("### 上一轮查询（最重要）")
            history_lines.append(f"- 用户问: {prev_question}")
            history_lines.append(f"- SQL: {prev_sql}")
            history_lines.append("")

        if history:
            history_lines.append("### 更早的对话")
            for i, h in enumerate(history, 1):
                q = h.get("question", "")
                a = h.get("answer", "")
                s = h.get("sql", "")
                history_lines.append(f"{i}. 用户问: {q}")
                if a:
                    a_short = a[:120] + "..." if len(a) > 120 else a
                    history_lines.append(f"   回答: {a_short}")
                if s:
                    history_lines.append(f"   SQL: {s}")

        history_lines.append("")
        history_lines.append("## 对话连续性要求（极其重要）")
        history_lines.append("如果当前问题是基于前序查询结果的延续（如统计、分析趋势、对比、排序、筛选子集等），你必须：")
        history_lines.append("1. 从上一轮SQL中提取所有实体过滤条件（如产线名 LIKE '%xxx%'、设备名=、设备ID IN(...)等）并原样保留")
        history_lines.append("2. 从上一轮SQL中提取时间范围条件（如 report_time >= DATE_SUB(...)、BETWEEN 等）并原样保留")
        history_lines.append("3. 保留上一轮SQL中用到的所有 JOIN 关联（因为WHERE条件依赖这些JOIN的表）")
        history_lines.append("4. 保留所有 del_flag=0 和 handle_status 等状态过滤条件")
        history_lines.append("5. 在此基础上再进行聚合/分组/排序/统计等操作")
        history_lines.append("")

        enhanced_system = "\n".join(history_lines) + "\n" + enhanced_system

    # 注入实体上下文 — 用户确认/系统自动匹配的实体，供 SQL 生成参考
    entity_context = session_memory.get("entity_context")
    if entity_context:
        lines = ["\n## 实体信息（已确认，SQL 的 WHERE 条件必须包含以下过滤）\n"]
        # 兼容 dict 格式（如 {'lines': ['1#制带线']}）和 list 格式
        if isinstance(entity_context, dict) and not any(isinstance(v, dict) for v in entity_context.values()):
            for key, vals in entity_context.items():
                if isinstance(vals, list):
                    val_list = "、".join(str(v) for v in vals[:8])
                    lines.append(f"- **{key}**：{val_list}")
                elif isinstance(vals, str):
                    lines.append(f"- **{key}**：{vals}")
        elif isinstance(entity_context, list):
            for ec in entity_context:
                if not isinstance(ec, dict):
                    continue
                vals = ec.get("values") or []
                val_list = "、".join(vals[:8])
                if len(vals) > 8:
                    val_list += f" 等{len(vals)}个"
                lines.append(f"- **{ec.get('entity_label', ec.get('entity_type', ''))}**（{ec.get('count', len(vals))}个）：{val_list}")
                if ec.get("table"):
                    lines.append(f"  对应表：`{ec['table']}`，匹配字段：`{ec.get('column', 'name')}`")
                if ec.get("sql_hint"):
                    lines.append(f"  提示：{ec['sql_hint']}")
        lines.append("")
        lines.append("**SQL 匹配方式（极其重要）**：")
        lines.append("- 用户已精确选定上述实体，SQL 必须使用精确匹配这些实体名称")
        lines.append("- 单实体：`字段 = '值'`")
        lines.append("- 多实体：`字段 IN ('值1', '值2', ...)`")
        lines.append("- **禁止**使用原问题中的关键词（如用户输入的简称）进行模糊 LIKE 匹配")
        lines.append("- **禁止**使用 `字段 LIKE '%关键词%'`，因为这会匹配到用户未选择的实体")
        lines.append("- 如果用户只选了部分实体，只筛选这些实体，不要包含未选中的")
        lines.append("")
        enhanced_system = "\n".join(lines) + "\n" + enhanced_system

    mem_elapsed = round((time.time() - t1) * 1000)

    # Build detailed retrieval message
    parts = []
    if retrieval_info.get("examples", 0) > 0:
        parts.append(f"{retrieval_info['examples']} 个相似问题-SQL对")
    if retrieval_info.get("schemas", 0) > 0:
        parts.append(f"{retrieval_info['schemas']} 个相关表结构")
    detail = "，".join(parts) if parts else "无相关内容"
    _push_step(state, config, {"step": "retrieving_memory", "status": "done",
                        "message": f"记忆库检索完成 ({mem_elapsed}ms)，检索到 {detail}", "elapsed_ms": mem_elapsed})

    # Step: generate SQL
    _push_step(state, config, {"step": "generating_sql", "status": "in_progress",
                        "message": "正在使用 LLM 生成 SQL 查询..."})
    t2 = time.time()

    try:
        response = llm.chat_once_with_retry(
            user_prompt=question,
            system_prompt=enhanced_system,
            temperature=0.1,
            max_tokens=4096,
            on_retry=lambda attempt, msg: _push_step(state, config, {
                "step": "generating_sql", "status": "in_progress", "message": msg
            })
        )
        logger.info(f"[generate_sql] LLM response ({len(response)} chars): {response[:200]}")
        raw = _clean_sql(response)

        # 解析多SQL：按 -- NEXT QUERY -- 分隔
        if MULTI_SQL_SEPARATOR.strip() in raw:
            sql_list = [s.strip() for s in raw.split(MULTI_SQL_SEPARATOR) if s.strip()]
            gen_elapsed = round((time.time() - t2) * 1000)
            logger.info(f"[generate_sql] {len(sql_list)} SQLs ready in {gen_elapsed}ms")
            _push_step(state, config, {"step": "generating_sql", "status": "done",
                                "message": f"生成 {len(sql_list)} 条 SQL ({gen_elapsed}ms)", "elapsed_ms": gen_elapsed})
            return {**state, "sql": sql_list, "sql_valid": True}
        else:
            gen_elapsed = round((time.time() - t2) * 1000)
            logger.info(f"[generate_sql] SQL ready in {gen_elapsed}ms: {raw[:200]}")
            _push_step(state, config, {"step": "generating_sql", "status": "done",
                                "message": f"SQL 生成完成 ({gen_elapsed}ms)", "elapsed_ms": gen_elapsed})
            return {**state, "sql": raw, "sql_valid": True}
    except Exception as e:
        gen_elapsed = round((time.time() - t2) * 1000)
        logger.error(f"[generate_sql] FAILED in {gen_elapsed}ms: {e}")
        _push_step(state, config, {"step": "generating_sql", "status": "error",
                            "message": f"SQL 生成失败 ({gen_elapsed}ms): {e}", "elapsed_ms": gen_elapsed})
        return {**state, "sql": None, "sql_valid": False, "sql_error": str(e)}


def execute_sql(state: AgentState, config: Optional[RunnableConfig] = None) -> AgentState:
    sql = state.get("sql")
    if not sql or not state.get("sql_valid"):
        return {**state, "final_answer": "未能生成有效的查询语句。"}

    # 统一转为列表处理
    sql_list = sql if isinstance(sql, list) else [sql]

    all_results = []
    all_sqls = []
    total_rows = 0
    elapsed_total = 0

    for idx, single_sql in enumerate(sql_list):
        label = f"第{idx+1}条" if len(sql_list) > 1 else ""

        # Step: validate
        _push_step(state, config, {"step": "validating_sql", "status": "in_progress",
                            "message": f"正在执行 SQL 安全检查{f' ({label})' if label else ''}..."})
        t0 = time.time()
        is_safe, result = validate_sql(single_sql)

        if not is_safe:
            return {
                **state, "sql_valid": False, "sql_error": result,
                "final_answer": f"查询被安全策略拦截: {result}"
            }

        cleaned_sql = result
        _push_step(state, config, {"step": "validating_sql", "status": "done",
                            "message": f"安全检查通过 ({label})" if label else "安全检查通过"})

        # Step: execute
        _push_step(state, config, {"step": "executing", "status": "in_progress",
                            "message": f"正在执行数据库查询{f' ({label})' if label else ''}..."})
        t1 = time.time()

        try:
            results = db.execute_query(cleaned_sql)
            exec_elapsed = round((time.time() - t1) * 1000)
            elapsed_total += exec_elapsed
            row_count = len(results) if results else 0
            total_rows += row_count
            logger.info(f"[execute_sql] {label}: {row_count} rows in {exec_elapsed}ms")

            all_results.append({"sql": cleaned_sql, "results": results, "rows": row_count})
            all_sqls.append(cleaned_sql)
        except Exception as e:
            exec_elapsed = round((time.time() - t1) * 1000)
            logger.error(f"[execute_sql] {label} FAILED in {exec_elapsed}ms: {e}")
            _push_step(state, config, {"step": "executing", "status": "error",
                                "message": f"查询执行失败 ({label}): {e}", "elapsed_ms": exec_elapsed})
            return {**state, "query_results": None, "final_answer": f"查询执行失败: {e}"}

    _push_step(state, config, {"step": "executing", "status": "done",
                        "message": f"查询完成: {len(sql_list)} 条SQL, 共 {total_rows} 条记录",
                        "elapsed_ms": elapsed_total})

    # Zero-result check for single SQL
    typo_suggestions = None
    if len(sql_list) == 1 and total_rows == 0:
        question = state.get("normalized_question") or state["question"]
        typo_suggestions = quick_typo_check(question)
        if typo_suggestions:
            logger.info(f"[execute_sql] zero-result typo check: {len(typo_suggestions)} suggestion(s)")

    # 计算结果分组（多SQL时保留分组供前端分别展示）
    display_sql = f"\n{MULTI_SQL_SEPARATOR}\n".join(all_sqls)
    flat_results = []
    for r in all_results:
        flat_results.extend(r["results"] or [])
    result_groups = None
    if len(all_results) > 1:
        result_groups = [{"sql": s, "results": r["results"], "rows": r["rows"]}
                         for s, r in zip(all_sqls, all_results)]

    # 存储 last_query 到 session_memory
    session_memory = state.get("session_memory") or {}

    # 判断分析价值并生成具体建议（无论意图类型都生成，供后续分析使用）
    analysis_suggestions = None
    suggestion_result = _get_analysis_suggestions(
        state.get("normalized_question") or state["question"], all_results, display_sql
    )
    if suggestion_result.get("has_value"):
        analysis_suggestions = suggestion_result.get("suggestions", [])

    session_memory["last_query"] = {
        "question": state.get("normalized_question") or state["question"],
        "sql": display_sql,
        "results": flat_results,
        "result_groups": result_groups,  # 多SQL时保留分组，方便分析agent选用正确的数据
        "total_rows": total_rows,
    }
    session_memory["analysis_suggestions"] = analysis_suggestions

    # Step: summarize
    _push_step(state, config, {"step": "summarizing", "status": "in_progress",
                        "message": "正在生成自然语言回答..."})
    t2 = time.time()
    answer = _format_answer(state["question"], all_results, typo_suggestions)
    sum_elapsed = round((time.time() - t2) * 1000)
    _push_step(state, config, {"step": "summarizing", "status": "done",
                        "message": f"回答生成完成 ({sum_elapsed}ms)", "elapsed_ms": sum_elapsed})

    return {**state, "sql": display_sql, "query_results": flat_results,
            "result_groups": result_groups, "analysis_suggestions": analysis_suggestions,
            "final_answer": answer, "session_memory": session_memory}


ANALYSIS_SUGGESTION_PROMPT = """根据查询结果判断是否有数据分析价值，如果有，给出具体的分析建议。

## 数据摘要
原始问题: {question}
执行的SQL: {sql}
结果行数: {row_count}
列名: {columns}
前几行: {sample}

## 任务
1. 判断这些数据是否有分析价值（有分类维度/时间字段可趋势分析/可对比等）
2. 如果有价值，生成2-3条具体建议，**每条必须保留原SQL中的实体过滤和时间范围条件**
3. **禁止建议查询与原数据无关的内容**（如原查询是故障记录，禁建议查设备效率）
4. 如果数据无分析维度（仅1列/无时间字段/无分类字段），直接返回无价值

## 输出JSON
{{"has_value": true/false, "suggestions": ["建议1", "建议2"], "data_description": "数据的一句话概括"}}
只输出JSON"""


def _get_analysis_suggestions(question: str, all_results: list, sql: str = "") -> dict:
    """LLM 判断数据价值并生成具体分析建议"""
    total_rows = sum(r["rows"] for r in all_results)
    if total_rows <= 1:
        return {"has_value": False, "suggestions": [], "data_description": ""}

    all_cols = []
    sample_rows = []
    for entry in all_results:
        results = entry["results"]
        if results:
            all_cols = list(results[0].keys())
            sample_rows = results[:3]
            break

    if not all_cols:
        return {"has_value": False, "suggestions": [], "data_description": ""}

    sample_json = json.dumps(sample_rows, ensure_ascii=False, default=str)

    prompt = ANALYSIS_SUGGESTION_PROMPT.format(
        question=question,
        sql=sql[:500] if sql else "(无)",
        row_count=total_rows,
        columns=", ".join(all_cols),
        sample=sample_json[:1500],
    )

    try:
        response = llm.chat_once_with_retry(
            user_prompt="请判断数据价值并生成分析建议。",
            system_prompt=prompt,
            temperature=0.1,
            max_tokens=4096,
        )
        logger.info(f"[analysis] LLM raw: {response.strip()[:200]}")
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```\w*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
        result = json.loads(cleaned)
        result.setdefault("has_value", False)
        result.setdefault("suggestions", [])
        result.setdefault("data_description", "")
        logger.info(f"[analysis] suggestions: has_value={result['has_value']}, "
                    f"{len(result['suggestions'])} suggestions")
        return result
    except Exception as e:
        logger.warning(f"[analysis] suggestion generation failed: {e}")
        return {"has_value": False, "suggestions": [], "data_description": ""}


def _format_answer(question: str, all_query_results: list,
                   typo_suggestions: list = None) -> str:
    """使用 LLM 将查询结果包装为自然语言回答

    all_query_results:
      单SQL时为 [{"sql": "...", "results": [...], "rows": N}]
      多SQL时为多个上述对象的列表
    """
    if not all_query_results:
        return "未查询到相关数据，请检查查询条件。"

    # 检查是否所有结果都为空
    total_rows = sum(r["rows"] for r in all_query_results)
    if total_rows == 0:
        if typo_suggestions:
            return _format_typo_suggestion(typo_suggestions)
        return "未查询到相关数据，请检查查询条件。"

    # 构建多SQL结果摘要
    parts = []
    for i, entry in enumerate(all_query_results):
        sql = entry["sql"]
        results = entry["results"]
        rows = entry["rows"]
        label = f"SQL{i+1}" if len(all_query_results) > 1 else "SQL"
        sample = results[:20] if results else []
        sample_json = json.dumps(sample, ensure_ascii=False, default=str)
        truncated = sample_json if len(sample_json) < 2000 else sample_json[:2000] + "..."
        parts.append(f"{label}: {sql}\n结果 ({rows} 条):\n{truncated}")

    prompt = """根据查询结果生成简洁的中文回答。

用户问题: {}
{}

要求:
1. 用自然语言直接回答用户问题
2. 如果有多条SQL，综合所有结果回答
3. 提到关键数字和名称
4. 不要输出JSON，直接输出回答文本""".format(question, chr(10).join(parts))

    try:
        response = llm.chat_once_with_retry(user_prompt=prompt, temperature=0.3, max_tokens=4096)
        answer = response.strip()
        logger.info(f"[format_answer] LLM response ({len(answer)} chars): {answer[:200]}")
    except Exception as e:
        logger.error(f"[format_answer] LLM failed: {e}")
        return f"AI 回答生成失败：{e}"

    if not answer:
        logger.error(f"[format_answer] LLM returned empty string, prompt preview: {prompt[:300]}")
        return "AI 回答生成失败，返回内容为空，请重试。"

    return answer


def _format_typo_suggestion(suggestions: list) -> str:
    """将疑似错别字建议格式化为用户友好的提示"""
    lines = ["未查询到相关数据。"]
    for s in suggestions:
        mention = s.get("mention", s.get("keyword", ""))
        suggestion = s.get("suggestion", "")
        candidates = s.get("candidates", [])
        if suggestion and suggestion != s.get("keyword", ""):
            lines.append(f"💡 您输入的「{mention}」可能是「{suggestion}」？")
        if len(candidates) > 1:
            cand_names = "、".join(c["label"] for c in candidates[:5])
            lines.append(f"   相关候选: {cand_names}")
    lines.append("请确认后重新输入正确的名称。")
    return "\n".join(lines)


def _format_answer_simple(all_results: list, total_rows: int = None) -> str:
    """兜底：简单格式化（支持单/多SQL）"""
    if total_rows is None:
        total_rows = sum(r["rows"] for r in all_results)

    if total_rows == 0:
        return "未查询到相关数据。"

    all_lines = []
    for i, entry in enumerate(all_results):
        results = entry["results"]
        rows = entry["rows"]
        if len(all_results) > 1:
            all_lines.append(f"--- 第{i+1}条查询结果 ({rows} 条) ---")
        for r in results[:20]:
            name = r.get("name") or r.get("fault_type") or ""
            count = r.get("count") or r.get("cnt") or r.get("fault_count") or ""
            if name and count:
                all_lines.append(f"- {name}: {count}次")
            elif name:
                status = r.get("status", "")
                extra = f" ({status})" if status else ""
                all_lines.append(f"- {name}{extra}")
            else:
                all_lines.append(str(r))

    header = f"查询到 {total_rows} 条记录:\n" if total_rows <= 20 else f"查询到 {total_rows} 条记录（显示前20条）:\n"
    return header + "\n".join(all_lines)


# ============================================================
# 纯函数（不依赖 AgentState）— 供外部直接调用
# ============================================================

def _normalize_entity_context_direct(entity_context: dict = None) -> list:
    """将多种 entity_context 格式统一为 sql_agent 期望的列表格式。

    期望输出: [{"entity_type": "device", "entity_label": "设备", "values": ["和膏机1号"]}]

    支持的输入格式:
    1. list of candidates — [{"entity_type": ..., "entity_label": ..., "candidates": [...]}]
    2. dict with "candidates" — 同上但外层为 dict
    3. confirmed_entities 格式 — [{"entity_type": ..., "value": ..., "label": ...}]
    4. 已经是期望格式 — [{"entity_type": ..., "entity_label": ..., "values": [...]}]
    """
    if not entity_context:
        return []

    # 如果是列表，逐项处理
    if isinstance(entity_context, list):
        result = []
        for item in entity_context:
            normalized = _normalize_single_entity(item)
            if normalized:
                result.append(normalized)
        return result

    # 如果是 dict，可能是单个实体或包含 candidates 的结构
    if isinstance(entity_context, dict):
        # 可能是 {"candidates": [...]} 格式
        if "candidates" in entity_context:
            return _normalize_entity_context_direct(entity_context.get("candidates", []))
        # 单个实体
        normalized = _normalize_single_entity(entity_context)
        return [normalized] if normalized else []

    return []


def _normalize_single_entity(item: dict) -> dict | None:
    """规范化单个实体条目"""
    if not isinstance(item, dict):
        return None

    # 已经是期望格式
    if "values" in item and "entity_type" in item:
        return item

    entity_type = item.get("entity_type", "")
    entity_label = item.get("entity_label", "")

    # confirmed_entities 格式: {entity_type, value, label, mention}
    if "value" in item and "label" in item:
        return {
            "entity_type": entity_type,
            "entity_label": entity_label or entity_type,
            "values": [item["label"]],
            "table": item.get("table"),
            "column": item.get("column", "name"),
            "sql_hint": item.get("sql_hint"),
        }

    # candidates 格式: {entity_type, entity_label, candidates: [{label, value, ...}]}
    if "candidates" in item:
        candidates = item.get("candidates", [])
        values = []
        table = None
        column = "name"
        for c in candidates:
            label = c.get("label", "")
            if label:
                values.append(label)
            if not table and c.get("table"):
                table = c["table"]
            if not column and c.get("column"):
                column = c["column"]
        return {
            "entity_type": entity_type,
            "entity_label": entity_label or entity_type,
            "values": values,
            "count": len(candidates),
            "table": table,
            "column": column,
            "sql_hint": item.get("sql_hint"),
        }

    return None


def generate_sql_direct(
    question: str,
    entity_context: dict = None,
    conversation_history: list = None,
) -> dict:
    """纯 SQL 生成函数，不依赖 AgentState。

    Args:
        question: 用户问题
        entity_context: 实体上下文，支持多种格式（见 _normalize_entity_context_direct）
        conversation_history: 对话历史，格式: [{"question": ..., "answer": ..., "sql": ...}]

    Returns:
        {"sql":  Union[str, list], "success": bool, "error": str | None}
    """
    # 1. 规范化 entity_context
    normalized_entities = _normalize_entity_context_direct(entity_context)

    # 2. 构造最小的 AgentState dict
    session_memory = {}
    if normalized_entities:
        session_memory["entity_context"] = normalized_entities
    if conversation_history:
        session_memory["history"] = conversation_history

    minimal_state = {
        "question": question,
        "normalized_question": question,
        "session_memory": session_memory,
        "steps": [],
    }

    # 3. 调用已有的 generate_sql
    try:
        result = generate_sql(minimal_state, {})
        sql = result.get("sql")
        success = result.get("sql_valid", False)
        error = result.get("sql_error")
        return {"sql": sql, "success": success, "error": error}
    except Exception as e:
        logger.error(f"[generate_sql_direct] failed: {e}")
        return {"sql": None, "success": False, "error": str(e)}
