"""自我评估 + 动态策略测试"""
import pytest
from unittest.mock import AsyncMock, patch
from backend.services.agentic_qa.agent_state import AgentState


class TestShouldReflect:
    def test_reflect_on_zero_rows(self):
        from backend.services.agentic_qa.master_loop import should_reflect
        assert should_reflect("execute_sql", {"row_count": 0}) is True

    def test_reflect_on_large_result(self):
        from backend.services.agentic_qa.master_loop import should_reflect
        assert should_reflect("execute_sql", {"row_count": 1500}) is True

    def test_no_reflect_on_normal_result(self):
        from backend.services.agentic_qa.master_loop import should_reflect
        assert should_reflect("execute_sql", {"row_count": 5}) is False

    def test_reflect_on_no_entities(self):
        from backend.services.agentic_qa.master_loop import should_reflect
        assert should_reflect("search_entities", {"entities": []}) is True

    def test_no_reflect_with_entities(self):
        from backend.services.agentic_qa.master_loop import should_reflect
        assert should_reflect("search_entities", {"entities": [{"name": "A"}]}) is False

    def test_no_reflect_on_unrelated_tool(self):
        from backend.services.agentic_qa.master_loop import should_reflect
        assert should_reflect("generate_sql", {"success": True}) is False

    def test_reflect_on_diagnose(self):
        from backend.services.agentic_qa.master_loop import should_reflect
        assert should_reflect("diagnose_sql_error", {"diagnosis": "column not found"}) is True


class TestReflect:
    @pytest.mark.asyncio
    async def test_returns_reflection_text(self):
        from backend.services.agentic_qa.master_loop import _reflect

        state = AgentState(question="q", session_id="s1")
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]

        reflection = "**判断**：返回0行，可能是实体名不匹配\n**下一步策略**：用 typo_check 检查"

        def _make_response(content):
            from types import SimpleNamespace
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))]
            )

        with patch("backend.services.agentic_qa.master_loop.llm") as mock_llm:
            mock_llm.model = "test-model"
            mock_llm.client.chat.completions.create.return_value = _make_response(reflection)

            result = await _reflect("execute_sql", {"row_count": 0}, state, messages)

        assert "判断" in result
        assert len(state.strategy_history) == 1
