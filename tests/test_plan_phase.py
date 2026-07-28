"""Plan 阶段测试"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.services.agentic_qa.agent_state import AgentState


def _make_llm_response(content: str):
    """构造模拟的 LLM 响应对象"""
    from types import SimpleNamespace
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))]
    )


class TestGeneratePlan:
    @pytest.mark.asyncio
    async def test_returns_plan_text(self):
        from backend.services.agentic_qa.master_loop import _generate_plan

        state = AgentState(question="最近一个月制带机的维修情况", session_id="s1")
        messages = [{"role": "system", "content": "你是助手"}, {"role": "user", "content": "问题"}]

        plan_text = "**问题理解**：查询制带机维修记录\n**查询策略**：查 dev_repair_order 表"

        with patch("backend.services.agentic_qa.master_loop.llm") as mock_llm:
            mock_llm.model = "test-model"
            mock_llm.client.chat.completions.create.return_value = _make_llm_response(plan_text)

            result = await _generate_plan(state, messages)

        assert "问题理解" in result
        assert state.plan_text == result

    @pytest.mark.asyncio
    async def test_plan_messages_exclude_tools(self):
        from backend.services.agentic_qa.master_loop import _generate_plan

        state = AgentState(question="test", session_id="s1")
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]

        with patch("backend.services.agentic_qa.master_loop.llm") as mock_llm:
            mock_llm.model = "test-model"
            mock_llm.client.chat.completions.create.return_value = _make_llm_response("计划")

            await _generate_plan(state, messages)

        call_kwargs = mock_llm.client.chat.completions.create.call_args[1]
        # Plan 调用不应传 tools 参数（或 tools 为 None）
        assert call_kwargs.get("tools") is None

    @pytest.mark.asyncio
    async def test_plan_injected_into_state(self):
        from backend.services.agentic_qa.master_loop import _generate_plan

        state = AgentState(question="test", session_id="s1")
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]

        with patch("backend.services.agentic_qa.master_loop.llm") as mock_llm:
            mock_llm.model = "test-model"
            mock_llm.client.chat.completions.create.return_value = _make_llm_response("我的计划")

            await _generate_plan(state, messages)

        assert state.plan_text == "我的计划"
