"""并行工具调用测试"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.services.agentic_qa.agent_state import AgentState


class TestExecuteToolsParallel:
    @pytest.mark.asyncio
    async def test_executes_multiple_tools_in_parallel(self):
        from backend.services.agentic_qa.master_loop import _execute_tools_parallel

        state = AgentState(question="q", session_id="s1")
        tool_context = MagicMock()

        tc1 = MagicMock()
        tc1.function.name = "generate_sql"
        tc1.function.arguments = '{"question": "test"}'
        tc1.id = "call_1"

        tc2 = MagicMock()
        tc2.function.name = "get_schema"
        tc2.function.arguments = '{"tables": ["dev_device"]}'
        tc2.id = "call_2"

        mock_tool_1 = AsyncMock()
        mock_tool_1.run.return_value = {"success": True, "sql": "SELECT 1"}
        mock_tool_2 = AsyncMock()
        mock_tool_2.run.return_value = {"schema": "id INT, name VARCHAR"}

        with patch("backend.services.agentic_qa.master_loop._registry") as mock_registry:
            mock_registry.get.side_effect = lambda name: {
                "generate_sql": mock_tool_1,
                "get_schema": mock_tool_2,
            }[name]
            mock_registry.tools = {"generate_sql": True, "get_schema": True}

            results = await _execute_tools_parallel([tc1, tc2], state, tool_context)

        assert len(results) == 2
        mock_tool_1.run.assert_called_once()
        mock_tool_2.run.assert_called_once()
        assert len(state.executed_steps) == 2

    @pytest.mark.asyncio
    async def test_handles_tool_exception(self):
        from backend.services.agentic_qa.master_loop import _execute_tools_parallel

        state = AgentState(question="q", session_id="s1")
        tool_context = MagicMock()

        tc = MagicMock()
        tc.function.name = "bad_tool"
        tc.function.arguments = '{}'
        tc.id = "call_err"

        mock_tool = AsyncMock()
        mock_tool.run.side_effect = RuntimeError("tool crashed")

        with patch("backend.services.agentic_qa.master_loop._registry") as mock_registry:
            mock_registry.get.return_value = mock_tool
            mock_registry.tools = {"bad_tool": True}

            results = await _execute_tools_parallel([tc], state, tool_context)

        assert len(results) == 1
        _, result = results[0]
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        from backend.services.agentic_qa.master_loop import _execute_tools_parallel

        state = AgentState(question="q", session_id="s1")
        tool_context = MagicMock()

        tc = MagicMock()
        tc.function.name = "nonexistent_tool"
        tc.function.arguments = '{}'
        tc.id = "call_unknown"

        with patch("backend.services.agentic_qa.master_loop._registry") as mock_registry:
            mock_registry.tools = {}

            results = await _execute_tools_parallel([tc], state, tool_context)

        assert len(results) == 1
        _, result = results[0]
        assert "error" in result
