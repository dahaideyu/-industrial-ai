"""
单元测试：实体上下文传递链路 — 验证 entity_type 不会丢失。

覆盖：
1. format_pre_context 显示候选实体时包含 entity_type
2. _normalize_entity_context 正确转换
3. _normalize_dict_context 正确转换
"""
import pytest


class TestFormatPreContextEntityType:
    """format_pre_context 在渲染候选实体时应包含 entity_type。"""

    def test_candidates_include_entity_type(self):
        from backend.services.agentic_qa.preprocess import format_pre_context

        pre = {
            "entity_candidates": {
                "制带机": [
                    {"label": "1#制带线", "entity_type": "device", "entity_label": "设备", "score": 0.95},
                    {"label": "2#制带线", "entity_type": "device", "entity_label": "设备", "score": 0.90},
                ],
            },
        }
        text = format_pre_context(pre)
        assert text is not None
        assert "1#制带线(设备)" in text, f"应显示 '1#制带线(设备)'，实际: {text}"
        assert "2#制带线(设备)" in text

    def test_candidates_use_entity_label_over_entity_type(self):
        from backend.services.agentic_qa.preprocess import format_pre_context

        pre = {
            "entity_candidates": {
                "制带线": [
                    {"label": "1#制带线", "entity_type": "line", "entity_label": "产线", "score": 0.80},
                ],
            },
        }
        text = format_pre_context(pre)
        assert "1#制带线(产线)" in text

    def test_candidates_without_type_still_work(self):
        from backend.services.agentic_qa.preprocess import format_pre_context

        pre = {
            "entity_candidates": {
                "某设备": [
                    {"label": "设备A", "score": 0.70},
                ],
            },
        }
        text = format_pre_context(pre)
        assert "设备A" in text
        # 没有 entity_type 时不显示括号
        assert "设备A(" not in text


class TestNormalizeEntityContext:
    """_normalize_entity_context 将 Planner 格式转为 sql_agent 格式。"""

    def test_basic_conversion(self):
        from backend.services.agentic_qa.tool_impls.sql_tools import _normalize_entity_context

        candidates = [
            {"name": "1#制带线", "type": "device", "label": "1#制带线"},
            {"name": "2#制带线", "type": "device", "label": "2#制带线"},
            {"name": "和膏机", "type": "device", "label": "和膏机"},
        ]
        result = _normalize_entity_context(candidates)
        assert len(result) == 1
        assert result[0]["entity_type"] == "device"
        assert set(result[0]["values"]) == {"1#制带线", "2#制带线", "和膏机"}
        assert result[0]["count"] == 3

    def test_multiple_types(self):
        from backend.services.agentic_qa.tool_impls.sql_tools import _normalize_entity_context

        candidates = [
            {"name": "1#制带线", "type": "device"},
            {"name": "A产线", "type": "line"},
        ]
        result = _normalize_entity_context(candidates)
        types = {r["entity_type"] for r in result}
        assert types == {"device", "line"}

    def test_empty(self):
        from backend.services.agentic_qa.tool_impls.sql_tools import _normalize_entity_context
        assert _normalize_entity_context([]) == []
        assert _normalize_entity_context(None) == []

    def test_missing_name_skipped(self):
        from backend.services.agentic_qa.tool_impls.sql_tools import _normalize_entity_context

        candidates = [
            {"type": "device", "label": ""},  # no name, no label
            {"name": "有效设备", "type": "device"},
        ]
        result = _normalize_entity_context(candidates)
        assert len(result) == 1
        assert result[0]["values"] == ["有效设备"]


class TestNormalizeDictContext:
    """_normalize_dict_context 将 LLM 的 dict 格式转为 sql_agent list 格式。"""

    def test_basic_dict(self):
        from backend.services.agentic_qa.tool_impls.sql_tools import _normalize_dict_context

        ctx = {"lines": ["1#制带线", "2#制带线"], "device": ["制带机"]}
        result = _normalize_dict_context(ctx)
        assert len(result) == 2
        lines_group = next(r for r in result if r["entity_type"] == "lines")
        assert lines_group["values"] == ["1#制带线", "2#制带线"]
        assert lines_group["count"] == 2

    def test_string_value(self):
        from backend.services.agentic_qa.tool_impls.sql_tools import _normalize_dict_context

        ctx = {"device": "制带机"}
        result = _normalize_dict_context(ctx)
        assert len(result) == 1
        assert result[0]["values"] == ["制带机"]

    def test_empty_and_none_skipped(self):
        from backend.services.agentic_qa.tool_impls.sql_tools import _normalize_dict_context

        ctx = {"empty_list": [], "device": ["制带机"], "none_val": None}
        result = _normalize_dict_context(ctx)
        assert len(result) == 1
        assert result[0]["entity_type"] == "device"


class TestMasterPromptExample:
    """master_prompt.py 中的示例不应将设备称为产线。"""

    def test_example_not_calling_device_line(self):
        from backend.services.agentic_qa.master_prompt import build_system_prompt

        prompt = build_system_prompt("tool_guidance", "test_session")
        # 不应出现 "制带机对应...产线" 这种错误表述
        assert "制带机对应" not in prompt or "两条产线" not in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
