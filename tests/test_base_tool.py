"""Unit tests for backend/services/agentic_qa/base_tool.py"""
import asyncio
import pytest
from dataclasses import fields
from typing import Any, Dict

from backend.services.agentic_qa.base_tool import (
    BaseTool,
    StepBuilder,
    ToolContext,
    ToolRegistry,
    TOOL_TITLES,
)


# ── Helpers ──

class _DummyTool(BaseTool):
    """Minimal concrete subclass for testing."""

    def __init__(self, when_to_use: str = "", when_not_to_use: str = ""):
        self._when_to_use = when_to_use
        self._when_not_to_use = when_not_to_use

    @property
    def name(self) -> str:
        return "dummy_tool"

    @property
    def description(self) -> str:
        return "A dummy tool for testing"

    @property
    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The query string"},
            },
            "required": ["query"],
        }

    @property
    def when_to_use(self) -> str:
        return self._when_to_use

    @property
    def when_not_to_use(self) -> str:
        return self._when_not_to_use

    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        return {"answer": f"processed: {kwargs.get('query', '')}"}


class _IncompleteTool(BaseTool):
    """Subclass that only partially implements abstract methods."""

    @property
    def name(self) -> str:
        return "incomplete"

    # Missing: description, schema, run


# ── ToolContext tests ──

class TestToolContext:
    def test_create_with_defaults(self):
        ctx = ToolContext(session_id="s1", memory_hub=None)
        assert ctx.session_id == "s1"
        assert ctx.memory_hub is None
        assert ctx.step_callback is None
        assert ctx.confirmed_entities == []
        assert ctx.entity_candidates == {}

    def test_create_with_all_fields(self):
        callback = lambda: None
        ctx = ToolContext(
            session_id="s2",
            memory_hub="hub_instance",
            step_callback=callback,
            confirmed_entities=[{"name": "设备A"}],
            entity_candidates={"device": ["设备A"]},
        )
        assert ctx.session_id == "s2"
        assert ctx.memory_hub == "hub_instance"
        assert ctx.step_callback is callback
        assert ctx.confirmed_entities == [{"name": "设备A"}]
        assert ctx.entity_candidates == {"device": ["设备A"]}

    def test_fields_are_independent(self):
        """Ensure default mutable fields are not shared across instances."""
        ctx1 = ToolContext(session_id="s1", memory_hub=None)
        ctx2 = ToolContext(session_id="s2", memory_hub=None)
        ctx1.confirmed_entities.append({"name": "X"})
        assert ctx2.confirmed_entities == []

    def test_dataclass_fields(self):
        field_names = {f.name for f in fields(ToolContext)}
        assert field_names == {
            "session_id", "memory_hub", "step_callback",
            "confirmed_entities", "entity_candidates",
        }


# ── BaseTool ABC tests ──

class TestBaseTool:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            BaseTool()

    def test_incomplete_subclass_cannot_instantiate(self):
        with pytest.raises(TypeError):
            _IncompleteTool()

    def test_concrete_subclass_instantiation(self):
        tool = _DummyTool()
        assert tool.name == "dummy_tool"
        assert tool.description == "A dummy tool for testing"
        assert isinstance(tool.schema, dict)

    def test_run_async(self):
        tool = _DummyTool()
        ctx = ToolContext(session_id="s1", memory_hub=None)
        result = asyncio.run(tool.run(ctx, query="hello"))
        assert result == {"answer": "processed: hello"}


# ── to_openai_schema tests ──

class TestToOpenAISchema:
    def test_schema_structure(self):
        tool = _DummyTool()
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert "function" in schema
        func = schema["function"]
        assert func["name"] == "dummy_tool"
        assert func["description"] == "A dummy tool for testing"
        assert "parameters" in func
        assert func["parameters"]["type"] == "object"
        assert "properties" in func["parameters"]
        assert "query" in func["parameters"]["properties"]
        assert func["parameters"]["required"] == ["query"]

    def test_schema_matches_tool_schema_property(self):
        tool = _DummyTool()
        schema = tool.to_openai_schema()
        assert schema["function"]["parameters"] == tool.schema


# ── when_to_use / when_not_to_use tests ──

class TestWhenToUse:
    def test_default_empty(self):
        tool = _DummyTool()
        assert tool.when_to_use == ""
        assert tool.when_not_to_use == ""

    def test_custom_values(self):
        tool = _DummyTool(when_to_use="When you need X", when_not_to_use="When you don't need X")
        assert tool.when_to_use == "When you need X"
        assert tool.when_not_to_use == "When you don't need X"


# ── ToolRegistry tests ──

class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = _DummyTool()
        registry.register(tool)
        assert registry.get("dummy_tool") is tool

    def test_get_missing_raises_keyerror(self):
        registry = ToolRegistry()
        with pytest.raises(KeyError, match="Tool not found: nonexistent"):
            registry.get("nonexistent")

    def test_all_schemas_empty(self):
        registry = ToolRegistry()
        assert registry.all_schemas() == []

    def test_all_schemas_returns_list(self):
        registry = ToolRegistry()
        registry.register(_DummyTool())
        schemas = registry.all_schemas()
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "dummy_tool"

    def test_prompt_section_contains_tool_info(self):
        registry = ToolRegistry()
        registry.register(_DummyTool())
        prompt = registry.prompt_section()
        assert "dummy_tool" in prompt
        assert "A dummy tool for testing" in prompt

    def test_prompt_section_with_when_to_use(self):
        registry = ToolRegistry()
        registry.register(_DummyTool(when_to_use="当需要测试时", when_not_to_use="当不需要测试时"))
        prompt = registry.prompt_section()
        assert "当需要测试时" in prompt
        assert "当不需要测试时" in prompt

    def test_prompt_section_uses_chinese_title(self):
        registry = ToolRegistry()

        class _SearchTool(BaseTool):
            @property
            def name(self): return "search_entities"
            @property
            def description(self): return "Search entities"
            @property
            def schema(self): return {"type": "object", "properties": {}}
            async def run(self, ctx, **kwargs): return {}

        registry.register(_SearchTool())
        prompt = registry.prompt_section()
        assert "实体搜索" in prompt

    def test_tools_property(self):
        registry = ToolRegistry()
        tool = _DummyTool()
        registry.register(tool)
        assert "dummy_tool" in registry.tools
        assert registry.tools["dummy_tool"] is tool

    def test_register_overwrites(self):
        registry = ToolRegistry()
        tool1 = _DummyTool()
        tool2 = _DummyTool()
        registry.register(tool1)
        registry.register(tool2)
        assert registry.get("dummy_tool") is tool2


# ── StepBuilder tests ──

class TestStepBuilder:
    def test_build_basic(self):
        step = StepBuilder.build("generate_sql", "success", "生成了SQL")
        assert step["tool"] == "generate_sql"
        assert step["title"] == "生成SQL查询"
        assert step["status"] == "success"
        assert step["detail"] == "生成了SQL"
        assert step["elapsed_ms"] == 0
        assert step["attempt"] == 1
        assert "error" not in step

    def test_build_with_error(self):
        step = StepBuilder.build("execute_sql", "error", "执行失败", error="Syntax error")
        assert step["status"] == "error"
        assert step["error"] == "Syntax error"

    def test_build_with_all_params(self):
        step = StepBuilder.build(
            "search_entities", "running", "搜索中...",
            elapsed_ms=150, attempt=2,
        )
        assert step["elapsed_ms"] == 150
        assert step["attempt"] == 2

    def test_detail_for_result_answer(self):
        result = {"answer": "这是答案"}
        detail = StepBuilder.detail_for_result("answer_general", result)
        assert detail == "这是答案"

    def test_detail_for_result_sql(self):
        result = {"sql": "SELECT * FROM t"}
        detail = StepBuilder.detail_for_result("generate_sql", result)
        assert "SELECT * FROM t" in detail

    def test_detail_for_result_error(self):
        result = {"success": False, "error": "连接超时"}
        detail = StepBuilder.detail_for_result("execute_sql", result)
        assert "连接超时" in detail

    def test_detail_for_result_row_count(self):
        result = {"success": True, "row_count": 42}
        detail = StepBuilder.detail_for_result("execute_sql", result)
        assert "42" in detail

    def test_detail_for_result_fallback(self):
        result = {"some_key": "some_value"}
        detail = StepBuilder.detail_for_result("unknown_tool", result)
        assert "执行完成" in detail

    def test_running_detail(self):
        detail = StepBuilder.running_detail("generate_sql")
        assert "正在执行" in detail
        assert "生成SQL查询" in detail

    def test_running_detail_unknown_tool(self):
        detail = StepBuilder.running_detail("unknown_tool")
        assert "正在执行" in detail
        assert "unknown_tool" in detail

    def test_tool_titles_completeness(self):
        """Ensure all expected tools have Chinese titles."""
        expected = [
            "search_entities", "get_schema", "generate_sql", "execute_sql",
            "diagnose_sql_error", "typo_check", "analyze_data", "query_rag",
            "answer_general", "read_memory", "ask_clarification",
        ]
        for name in expected:
            assert name in TOOL_TITLES, f"Missing title for {name}"
