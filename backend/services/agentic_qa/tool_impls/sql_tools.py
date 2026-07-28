# cython: annotation_typing=False, infer_types=False, language_level=3
"""SQL-related tools: generate_sql, execute_sql, diagnose_sql_error, typo_check."""
import json
from typing import Any, Dict, List, Optional

from backend.core.agentic_qa.logger import get_logger
from backend.services.agentic_qa.base_tool import BaseTool, ToolContext

logger = get_logger("agentic_qa.tool_impls.sql_tools")


# ── helper ──

def _normalize_entity_context(candidates: list) -> list:
    """Convert Planner's entity candidates to sql_agent's entity-group format.

    Planner format: [{"name": "和膏机", "type": "device", "label": "和膏机"}, ...]
    sql_agent expects: [{"entity_type": "device", "entity_label": "设备", "values": ["和膏机", ...]}, ...]
    """
    if not candidates:
        return []
    by_type: dict = {}
    for c in candidates:
        etype = c.get("type", "unknown")
        name = c.get("name", "") or c.get("label", "")
        if not name:
            continue
        if etype not in by_type:
            by_type[etype] = []
        by_type[etype].append(name)
    result = []
    for etype, names in by_type.items():
        result.append({
            "entity_type": etype,
            "entity_label": etype,
            "values": names,
            "count": len(names),
        })
    return result


def _normalize_dict_context(ctx: dict) -> list:
    """Convert LLM's dict-format entity_context to sql_agent's list format.

    Handles: {'lines': ['1#制带线', '2#制带线'], 'device': ['制带机']}
    Returns: [{'entity_type': 'lines', 'entity_label': 'lines', 'values': ['1#制带线', '2#制带线']}, ...]
    """
    result = []
    for key, vals in ctx.items():
        if isinstance(vals, list) and vals:
            result.append({
                "entity_type": key,
                "entity_label": key,
                "values": [str(v) for v in vals],
                "count": len(vals),
            })
        elif isinstance(vals, str) and vals.strip():
            result.append({
                "entity_type": key,
                "entity_label": key,
                "values": [vals.strip()],
                "count": 1,
            })
    return result


# ── GenerateSqlTool ──

class GenerateSqlTool(BaseTool):
    """Generate SQL from natural language using Vanna enhancers + LLM. Does NOT execute."""

    name = "generate_sql"
    description = (
        "根据自然语言问题生成 SQL 查询语句。仅生成 SQL，不会执行。"
        "生成后应先审查再调用 execute_sql 执行。"
    )
    schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "自然语言查询描述，需包含已解析的实体名称",
            },
            "entity_context": {
                "type": "object",
                "description": "可选，已解析的设备/产线等实体上下文",
            },
        },
        "required": ["question"],
    }
    when_to_use = "用户问题需要查询数据库时，先调用此工具生成 SQL"
    when_not_to_use = "用户只是闲聊、概念解释或文档检索，不需要查库"

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        import json as _json
        question = kwargs.get("question", "")
        entity_context = kwargs.get("entity_context")

        # LLM 可能传 JSON 字符串或 Python dict repr，解析为 dict
        if isinstance(entity_context, str) and entity_context.strip():
            try:
                entity_context = _json.loads(entity_context)
            except (_json.JSONDecodeError, TypeError):
                try:
                    import ast
                    entity_context = ast.literal_eval(entity_context)
                except (ValueError, SyntaxError):
                    pass

        # 优先从 ToolContext 获取已确认实体
        if not entity_context and ctx.confirmed_entities:
            entity_context = {"candidates": ctx.confirmed_entities}

        # 暂用旧的 generate_sql + AgentState 方式（后续改为 generate_sql_direct）
        from backend.services.agentic_qa.agents.sql_agent import generate_sql as _gen_sql
        from backend.services.agentic_qa.state import AgentState

        state: AgentState = {
            "question": question,
            "normalized_question": question,
            "session_memory": {
                "entity_context": entity_context or {},
                "history": [],
            },
            "session_id": ctx.session_id,
            "sql": None,
            "sql_valid": True,
            "sql_error": None,
            "query_results": None,
            "result_groups": None,
            "analysis_suggestions": None,
            "final_answer": None,
            "messages": [],
            "steps": [],
            "intent": None,
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
            "analysis_chart": None,
            "user_role": "admin",
            "use_rag": False,
        }

        if entity_context and isinstance(entity_context, dict):
            raw_candidates = entity_context.get("candidates") or entity_context.get("candidate_entities")
            if raw_candidates:
                normalized = _normalize_entity_context(raw_candidates)
                if normalized:
                    state["session_memory"]["entity_context"] = normalized
            else:
                # LLM 传了非标准格式（如 {'lines': ['1#制带线']}），转换为标准 list 格式
                normalized = _normalize_dict_context(entity_context)
                if normalized:
                    state["session_memory"]["entity_context"] = normalized

        try:
            state = _gen_sql(state, {})
            if not state.get("sql_valid"):
                return {
                    "success": False,
                    "error": state.get("sql_error", "SQL generation failed"),
                    "sql": state.get("sql"),
                }
            return {"success": True, "sql": state.get("sql")}
        except Exception as e:
            logger.error(f"[GenerateSqlTool] error: {e}")
            return {"success": False, "error": str(e)}


# ── ExecuteSqlTool ──

class ExecuteSqlTool(BaseTool):
    """Execute a SQL query after safety validation. Writes results to session memory."""

    name = "execute_sql"
    description = (
        "执行 SQL 查询并返回结果。仅在 generate_sql 生成有效 SQL 后调用。"
        "执行前会进行安全验证，结果自动写入 session memory。"
    )
    schema = {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "要执行的 SQL 语句",
            },
        },
        "required": ["sql"],
    }
    when_to_use = "generate_sql 成功生成 SQL 后，需要执行获取数据"
    when_not_to_use = "SQL 尚未生成或生成失败时，不要执行"

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        sql = kwargs.get("sql", "")

        # 处理 LLM 各种非标准输出格式
        if isinstance(sql, dict):
            sql = sql.get("sql") or sql.get("query") or ""
        elif isinstance(sql, (tuple, list)):
            for item in sql:
                if isinstance(item, str) and item.strip().upper().startswith(("SELECT", "SHOW", "DESC", "WITH")):
                    sql = item
                    break
            else:
                sql = str(sql[0]) if sql else ""
        sql = str(sql) if sql and not isinstance(sql, str) else (sql or "")
        if not sql or not sql.strip():
            return {"success": False, "error": f"Invalid SQL input: {type(sql).__name__}", "row_count": 0}

        from backend.services.agentic_qa.vanna.guard import (
            validate_sql, needs_maintenance_time_range, MAINTENANCE_TIME_HINT,
        )

        is_safe, sql_or_msg = validate_sql(sql)
        logger.debug(f"[ExecuteSqlTool] validate_sql: is_safe={is_safe}, sql_len={len(sql_or_msg) if sql_or_msg else 0}")
        if not is_safe:
            return {"success": False, "error": sql_or_msg or "SQL failed safety validation", "row_count": 0, "sql": sql}
        sql = sql_or_msg  # use potentially modified SQL (e.g., with auto-added LIMIT)

        # 维修类大表时间范围兜底：引用维修表却无任何时间过滤时，让 LLM 补时间范围重试，防全表扫描
        if needs_maintenance_time_range(sql):
            logger.warning("[ExecuteSqlTool] maintenance-table query lacks time range, requesting LLM to add one")
            return {"success": False, "error": MAINTENANCE_TIME_HINT, "row_count": 0, "sql": sql, "needs_time_range": True}

        try:
            from vanna.capabilities.sql_runner.models import RunSqlToolArgs
            from backend.services.agentic_qa.vanna.agent import get_vanna_manager, _make_context

            manager = get_vanna_manager()
            args = RunSqlToolArgs(sql=sql)
            vctx = _make_context(manager.memory, "admin")
            df = await manager._runner.run_sql(args, vctx)
            results = df.to_dict(orient="records") if hasattr(df, "to_dict") else list(df)
            rows = results if isinstance(results, list) else []

            # 写入 session memory
            if ctx.memory_hub:
                ctx.memory_hub.update_session("last_query", {"data": rows, "sql": sql})

            return {
                "success": True,
                "row_count": len(rows),
                "query_results": rows,
                "sql": sql,
                "_hint": "数据已获取，如需分析可调用 analyze_data",
            }
        except Exception as e:
            logger.error(f"[ExecuteSqlTool] error: {e}")
            return {"success": False, "error": str(e), "row_count": 0, "sql": sql}


# ── DiagnoseSqlErrorTool ──

class DiagnoseSqlErrorTool(BaseTool):
    """Use LLM to diagnose a SQL error and suggest a fix."""

    name = "diagnose_sql_error"
    description = (
        "分析 SQL 错误信息并给出修正建议。当 execute_sql 返回错误时调用此工具诊断原因。"
    )
    schema = {
        "type": "object",
        "properties": {
            "error_message": {
                "type": "string",
                "description": "SQL 执行时的错误信息",
            },
            "sql": {
                "type": "string",
                "description": "出错的 SQL 语句",
            },
        },
        "required": ["error_message", "sql"],
    }
    when_to_use = "execute_sql 执行失败后，需要分析错误原因并尝试修正"
    when_not_to_use = "SQL 执行成功时不需要诊断"

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        error_message = kwargs.get("error_message", "")
        sql = kwargs.get("sql", "")

        from backend.core.agentic_qa.llm import llm

        prompt = """You are a MySQL diagnostic expert. A SQL query failed.

SQL:
```sql
{}
```

Error message:
{}

Analyze the error and output JSON:
{{}}

Output ONLY the JSON, no markdown.""".format(sql, error_message, "diagnosis")
        try:
            response = llm.chat_once_with_retry(
                system_prompt="You are a MySQL diagnostic expert. Output only valid JSON.",
                user_prompt=prompt,
                temperature=0.0,
                max_tokens=4096,
            )
            if not response or not response.strip():
                logger.warning("[DiagnoseSqlErrorTool] LLM returned empty response")
                return {
                    "diagnosis": "llm_empty_response",
                    "fix_type": "other",
                    "corrected_sql": sql,
                    "explanation": "LLM返回空响应",
                }
            logger.debug(f"[DiagnoseSqlErrorTool] raw response ({len(response)} chars)")
            result = json.loads(response.strip().removeprefix("```json").removesuffix("```").strip())
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"[DiagnoseSqlErrorTool] JSON parse failed: {e}")
            return {
                "diagnosis": "parse_error",
                "fix_type": "other",
                "corrected_sql": sql,
                "explanation": f"JSON解析失败: {e}",
            }
        except Exception as e:
            logger.warning(f"[DiagnoseSqlErrorTool] failed: {e}")
            return {
                "diagnosis": "unknown",
                "fix_type": "other",
                "corrected_sql": sql,
                "explanation": str(e),
            }


# ── TypoCheckTool ──

class TypoCheckTool(BaseTool):
    """Check for typos in entity names when query returns 0 results."""

    name = "typo_check"
    description = (
        "检测用户问题中的实体名称拼写错误。当查询返回0条结果时，"
        "可能是设备/产线名称拼写有误，调用此工具检查并给出建议。"
    )
    schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "用户的原始问题",
            },
        },
        "required": ["question"],
    }
    when_to_use = "execute_sql 返回 0 行数据，怀疑是实体名称拼写错误"
    when_not_to_use = "查询已返回数据，或问题不涉及实体名称"

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        question = kwargs.get("question", "")

        from backend.services.agentic_qa.agents.entity_resolver import quick_typo_check

        try:
            suggestions = quick_typo_check(question)
            return {
                "has_typo": bool(suggestions),
                "suggestions": suggestions or [],
            }
        except Exception as e:
            logger.warning(f"[TypoCheckTool] failed: {e}")
            return {"has_typo": False, "suggestions": []}
