# cython: annotation_typing=False, infer_types=False, language_level=3
"""Vanna LifecycleHook — SQL 安全监护"""
from typing import Union
import re
import time
from typing import Optional, Any
from vanna.core import LifecycleHook
from vanna.core.tool.models import ToolResult, ToolContext
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("vanna.guard")


class SqlSecurityHook(LifecycleHook):
    """SQL 安全监护 Hook"""

    MAX_ROWS = 1000

    async def before_tool(self, tool: Any, context: ToolContext) -> None:
        tool_name = getattr(tool, 'name', '') or tool.__class__.__name__
        if 'sql' not in tool_name.lower():
            return
        logger.debug(f"[guard] before_tool: {tool_name}")

    def before_tool_sync(self, tool: Any, context: ToolContext) -> Optional[str]:
        tool_name = getattr(tool, 'name', '') or tool.__class__.__name__
        if 'sql' not in tool_name.lower():
            return None
        return None

    async def after_tool(self, result: ToolResult) -> Optional[ToolResult]:
        if result.success:
            logger.info(f"[guard] SQL execution OK")
        else:
            logger.error(f"[guard] SQL execution FAILED: {result.error}")
        return None


# 允许执行的只读语句首关键词（NL2SQL 只产出查询类语句）
READ_ONLY_LEADING = frozenset({"select", "with", "show", "desc", "describe", "explain"})


def _strip_sql_literals(sql: str) -> str:
    """移除字符串字面量、标识符引用与注释，仅用于安全关键词扫描。

    返回值**不**用于实际执行，只用于让 `\\bkeyword\\b` 之类的扫描不会被
    字符串内容（如 ``LIKE '%update%'``）或反引号列名误触发。

    处理：块注释 / 行注释 / 单引号串 / 双引号串 / 反引号标识符 → 替换为空格。
    """
    s = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)   # 块注释
    s = re.sub(r"(--|#)[^\n]*", " ", s)                    # 行注释
    s = re.sub(r"'(?:[^'\\]|\\.|'')*'", " ", s)            # 单引号字符串
    s = re.sub(r'"(?:[^"\\]|\\.|"")*"', " ", s)            # 双引号字符串
    s = re.sub(r"`[^`]*`", " ", s)                         # 反引号标识符
    return s


def validate_sql(sql: str) -> tuple[bool, str]:
    """验证 SQL 安全性。

    返回 (is_safe, sql_or_msg)：安全时返回（可能自动补了 LIMIT 的）SQL，
    不安全时返回拦截原因。所有关键词扫描都在**剥离字符串字面量/注释**后的
    副本上进行，避免把 ``WHERE remark='please delete later'`` 这类正常查询误拦。
    """
    if not sql or not sql.strip():
        return False, "空 SQL"

    scan = _strip_sql_literals(sql).lower()

    # 1. DML 禁止词（在剥离字面量后的副本上匹配独立单词，不误伤函数/列名/字符串）
    forbidden = ["insert", "update", "delete", "drop", "alter", "truncate", "create"]
    for kw in forbidden:
        if re.search(r'\b' + kw + r'\b', scan):
            logger.warning(f"[guard] blocked {kw.upper()} in SQL")
            return False, f"禁止执行 {kw.upper()} 操作"

    # REPLACE 只禁止 DML 语句（REPLACE INTO），允许函数调用 REPLACE()
    if re.search(r'\breplace\s+into\b', scan):
        logger.warning("[guard] blocked REPLACE INTO")
        return False, "禁止执行 REPLACE INTO 操作"

    # 2. 文件读写向量（依赖 DB 账号 FILE 权限，必须显式拦截）
    if re.search(r'\binto\s+(out|dump)file\b', scan):
        logger.warning("[guard] blocked INTO OUTFILE/DUMPFILE")
        return False, "禁止执行文件导出（INTO OUTFILE/DUMPFILE）操作"
    if re.search(r'\bload_file\s*\(', scan):
        logger.warning("[guard] blocked LOAD_FILE()")
        return False, "禁止执行文件读取（LOAD_FILE）操作"
    if re.search(r'\bload\s+data\b', scan):
        logger.warning("[guard] blocked LOAD DATA")
        return False, "禁止执行 LOAD DATA 操作"

    # 3. 多语句拦截（防止 SELECT ...; <其他语句> 堆叠注入）
    if ";" in scan.strip().rstrip(";").strip():
        logger.warning("[guard] blocked multi-statement SQL")
        return False, "禁止多语句执行"

    # 4. 只读语句白名单（首关键词必须是查询类；忽略前导括号，如 (SELECT ...) UNION ...）
    m = re.match(r'^\s*\(*\s*([a-z_]+)', scan)
    leading = m.group(1) if m else ""
    if leading not in READ_ONLY_LEADING:
        logger.warning(f"[guard] blocked non-readonly leading keyword: {leading!r}")
        return False, f"只允许只读查询（SELECT/WITH/SHOW/DESCRIBE/EXPLAIN），检测到: {leading.upper() or '空语句'}"

    # 5. 自动补 LIMIT（仅 SELECT/WITH；用词边界判断，避免 credit_limit 等列名误判）。
    #    SHOW/DESC/EXPLAIN 不接受 LIMIT，不处理。
    if leading in ("select", "with"):
        has_limit = re.search(r'\blimit\b', scan)
        has_count = re.search(r'\bcount\s*\(', scan)
        if not has_limit and not has_count:
            sql = _add_limit(sql, 1000)
            logger.debug("[guard] auto-added LIMIT 1000")

    return True, sql


def _add_limit(sql: str, limit: int = 1000) -> str:
    sql = sql.rstrip().rstrip(";").rstrip()
    return f"{sql} LIMIT {limit}"


# ── 维修类大表时间范围兜底 ──
#
# dev_repair_order / dev_alarm / dev_maintenance 等带时间戳的大表，无时间范围极易
# 触发全表扫描。sql_agent 提示词（规则 9）已要求强制时间范围，但那是“软提示”，
# LLM 偶尔会漏加。此处在执行层加一道兜底：检测到引用这些表却完全没有任何时间过滤
# 信号时，让上层要求 LLM 补时间范围后重试——**不改写 SQL**（拿不到各表真实时间
# 列名，且多表 JOIN/子查询注入风险高），零破坏。
MAINTENANCE_TABLES = ("dev_repair_order", "dev_alarm", "dev_maintenance")

MAINTENANCE_TIME_HINT = (
    "查询维修类表（dev_repair_order / dev_alarm / dev_maintenance）必须带时间范围，"
    "禁止无时间限制的全表扫描。请在 WHERE 中补充时间范围条件"
    "（如 report_time >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)，时间列名以该表实际结构为准），"
    "用户未指定范围时默认最近 30 天，然后重新生成并执行 SQL。"
)

# 时间过滤信号：时间函数/关键字，或形如 xxx_time / xxx_date / created_at 的时间列。
# 故意从宽匹配——宁可误认为“已带时间”而放行（最多漏补一次），也绝不误拦正常查询。
_TIME_SIGNAL_RE = re.compile(
    r"\b(?:interval|curdate|current_date|current_timestamp|now|sysdate|"
    r"date_sub|date_add|adddate|subdate|timestampdiff|datediff|unix_timestamp|between)\b"
    r"|\b\w*(?: Union[time, date])\b"        # 含 time/date 结尾的列名：report_time、create_date …
    r"|\b\w+_(?: Union[at, ts, dt])\b",       # created_at / updated_ts / start_dt
    re.IGNORECASE,
)


def needs_maintenance_time_range(sql: str) -> bool:
    """SQL 引用维修类大表却完全无时间过滤信号时返回 True（应让 LLM 补时间范围重试）。

    判定在剥离字符串字面量/注释后的副本上进行；时间信号从宽匹配，保证不误拦——
    只有“明确引用维修表 + 完全没有任何时间相关条件”才触发。
    """
    scan = _strip_sql_literals(sql).lower()
    if not any(re.search(r'\b' + t + r'\b', scan) for t in MAINTENANCE_TABLES):
        return False
    if _TIME_SIGNAL_RE.search(scan):
        return False
    return True
