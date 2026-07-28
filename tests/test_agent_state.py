# tests/test_agent_state.py
"""AgentState 单元测试"""
import pytest
from backend.services.agentic_qa.agent_state import AgentState


class TestRecordToolResult:
    def test_generate_sql_updates_last_sql(self):
        state = AgentState(question="test", session_id="s1")
        result = {"success": True, "sql": "SELECT * FROM dev_device"}
        state.record_tool_result("generate_sql", result)
        assert state.last_sql == "SELECT * FROM dev_device"

    def test_execute_sql_updates_results(self):
        state = AgentState(question="test", session_id="s1")
        state.last_sql = "SELECT * FROM dev_device"
        result = {"success": True, "query_results": [{"id": 1, "name": "设备A"}], "row_count": 1}
        state.record_tool_result("execute_sql", result)
        assert state.last_query_results == [{"id": 1, "name": "设备A"}]
        assert len(state.all_query_results) == 1
        assert state.all_query_results[0]["sql"] == "SELECT * FROM dev_device"

    def test_execute_sql_empty_results_not_appended(self):
        state = AgentState(question="test", session_id="s1")
        result = {"success": True, "query_results": [], "row_count": 0}
        state.record_tool_result("execute_sql", result)
        assert state.last_query_results is None
        assert len(state.all_query_results) == 0

    def test_error_increments_consecutive_failures(self):
        state = AgentState(question="test", session_id="s1")
        result = {"error": "table not found"}
        state.record_tool_result("execute_sql", result)
        assert state.consecutive_failures == 1
        state.record_tool_result("execute_sql", result)
        assert state.consecutive_failures == 2

    def test_success_resets_consecutive_failures(self):
        state = AgentState(question="test", session_id="s1")
        state.consecutive_failures = 2
        result = {"success": True, "query_results": [{"id": 1}], "row_count": 1}
        state.record_tool_result("execute_sql", result)
        assert state.consecutive_failures == 0

    def test_records_step_history(self):
        state = AgentState(question="test", session_id="s1")
        state.record_tool_result("generate_sql", {"success": True, "sql": "SELECT 1"})
        assert len(state.executed_steps) == 1
        assert state.executed_steps[0]["tool"] == "generate_sql"
        assert state.executed_steps[0]["success"] is True

    def test_analyze_data_updates_chart(self):
        state = AgentState(question="test", session_id="s1")
        result = {"insights": "设备A故障最多", "chart": {"type": "bar"}}
        state.record_tool_result("analyze_data", result)
        assert state.final_answer == "设备A故障最多"
        assert state.final_chart == {"type": "bar"}


class TestCheckShouldStop:
    def test_stops_on_success(self):
        state = AgentState(question="q", session_id="s1")
        state.final_answer = "答案"
        state.last_query_results = [{"id": 1}]
        should_stop, reason = state.check_should_stop()
        assert should_stop is True
        assert "成功" in reason

    def test_stops_on_consecutive_failures(self):
        state = AgentState(question="q", session_id="s1")
        state.consecutive_failures = 3
        should_stop, reason = state.check_should_stop()
        assert should_stop is True
        assert "连续失败" in reason

    def test_stops_on_strategy_loop(self):
        state = AgentState(question="q", session_id="s1")
        state.strategy_history = ["same", "same", "same"]
        should_stop, reason = state.check_should_stop()
        assert should_stop is True
        assert "循环" in reason

    def test_continues_when_active(self):
        state = AgentState(question="q", session_id="s1")
        state.consecutive_failures = 1
        should_stop, _ = state.check_should_stop()
        assert should_stop is False


class TestDetectStrategyLoop:
    def test_no_loop_with_few_entries(self):
        state = AgentState(question="q", session_id="s1")
        state.strategy_history = ["a", "b"]
        assert state.detect_strategy_loop() is False

    def test_detects_loop(self):
        state = AgentState(question="q", session_id="s1")
        state.strategy_history = ["换表查询", "换表查询", "换表查询"]
        assert state.detect_strategy_loop() is True

    def test_no_loop_when_diverse(self):
        state = AgentState(question="q", session_id="s1")
        state.strategy_history = ["策略A", "策略B", "策略C"]
        assert state.detect_strategy_loop() is False


class TestBuildResultGroups:
    def test_returns_none_for_single_result(self):
        state = AgentState(question="q", session_id="s1")
        state.all_query_results = [{"sql": "SELECT 1", "results": [{"a": 1}]}]
        assert state.build_result_groups() is None

    def test_returns_groups_for_multiple(self):
        state = AgentState(question="q", session_id="s1")
        state.all_query_results = [
            {"sql": "SELECT 1", "results": [{"a": 1}]},
            {"sql": "SELECT 2", "results": [{"b": 2}]},
        ]
        groups = state.build_result_groups()
        assert groups is not None
        assert len(groups) == 2

    def test_filters_empty_results(self):
        state = AgentState(question="q", session_id="s1")
        state.all_query_results = [
            {"sql": "SELECT 1", "results": [{"a": 1}]},
            {"sql": "SELECT 2", "results": []},
        ]
        assert state.build_result_groups() is None
