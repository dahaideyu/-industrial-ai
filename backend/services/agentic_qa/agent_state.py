# cython: annotation_typing=False, infer_types=False, language_level=3
"""AgentState — 统一状态管理，替代 master_loop 中的散落变量"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _summarize_result(tool_name: str, result: dict) -> str:
    """为 executed_steps 生成简短摘要"""
    if result.get("error"):
        return f"ERROR: {str(result['error'])[:80]}"
    if tool_name == "execute_sql":
        return f"rows={result.get('row_count', 0)}"
    if tool_name == "generate_sql":
        return f"success={result.get('success')}"
    if tool_name == "search_entities":
        return f"entities={len(result.get('entities', []))}"
    if tool_name == "analyze_data":
        return f"insights_len={len(result.get('insights', ''))}"
    if tool_name == "answer_general":
        return f"answer_len={len(result.get('answer', ''))}"
    return str(result)[:80]


@dataclass
class AgentState:
    """Agent 执行状态"""

    # 输入
    question: str
    session_id: str

    # 计划
    plan_text: str = ""

    # 执行追踪
    executed_steps: List[Dict[str, Any]] = field(default_factory=list)

    # 查询结果
    last_sql: str = ""
    last_query_results: Optional[List[Dict[str, Any]]] = None
    all_query_results: List[Dict[str, Any]] = field(default_factory=list)

    # 输出
    final_answer: str = ""
    final_chart: Optional[Dict[str, Any]] = None

    # 策略控制
    consecutive_failures: int = 0
    strategy_history: List[str] = field(default_factory=list)

    def record_tool_result(self, tool_name: str, result: dict):
        """统一记录工具执行结果，自动更新关联状态"""
        is_error = bool(result.get("error"))

        self.executed_steps.append({
            "tool": tool_name,
            "success": not is_error,
            "summary": _summarize_result(tool_name, result),
        })

        if is_error:
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0

        if tool_name == "generate_sql" and result.get("success") and result.get("sql"):
            self.last_sql = result["sql"]

        if tool_name == "execute_sql" and result.get("success"):
            data = result.get("query_results")
            if data and len(data) > 0:
                self.last_query_results = data
                self.all_query_results.append({"sql": result.get("sql", self.last_sql), "results": data})

        if tool_name == "analyze_data" and not is_error:
            if result.get("insights"):
                self.final_answer = result["insights"]
            if result.get("chart"):
                self.final_chart = result["chart"]

        if tool_name == "query_rag" and not is_error and result.get("answer"):
            self.final_answer = result["answer"]

        if tool_name == "answer_general" and not is_error and result.get("answer"):
            self.final_answer = result["answer"]

    def check_should_stop(self, max_steps: int = 50) -> tuple:
        """自主判断是否应停止。返回 (should_stop, reason)"""
        if self.final_answer and self.last_query_results:
            return True, "成功获取数据并生成回答"
        if self.consecutive_failures >= 3:
            return True, "连续失败3次"
        if self.detect_strategy_loop():
            return True, "检测到策略循环"
        if len(self.executed_steps) >= max_steps:
            return True, "达到最大步数"
        return False, ""

    def detect_strategy_loop(self) -> bool:
        """检测最近3步策略是否相同"""
        if len(self.strategy_history) < 3:
            return False
        recent = self.strategy_history[-3:]
        return len(set(recent)) == 1

    def build_result_groups(self) -> Optional[List[Dict]]:
        """构建多结果集（过滤空结果）"""
        valid = [r for r in self.all_query_results if r.get("results") and len(r["results"]) > 0]
        if len(valid) > 1:
            return [{"sql": r["sql"], "results": r["results"]} for r in valid]
        return None
