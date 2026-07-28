"""Unit tests for backend/services/agentic_qa/preprocess.py — assemble_context + format_pre_context"""
import asyncio
from unittest.mock import patch, MagicMock

from backend.services.agentic_qa.preprocess import (
    assemble_context,
    format_pre_context,
)


# ── Helpers ──

def _run(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.run(coro)


# ── assemble_context tests ──


class TestAssembleContextSkipExtraction:
    """skip_extraction=True 时不应调用 _extract_entity_mentions"""

    @patch("backend.services.agentic_qa.preprocess.build_query_blueprint", return_value=None)
    @patch("backend.services.agentic_qa.preprocess.labels_from_confirmed", return_value=[])
    @patch("backend.services.agentic_qa.preprocess.extract_entity_labels", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._search_similar_queries", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._match_schemas", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._extract_entity_mentions")
    def test_skip_extraction_true_no_mention_call(self, mock_mentions, mock_schemas, mock_history, mock_ext_labels, mock_conf_labels, mock_blueprint):
        mock_mentions.return_value = [{"type": "device", "keyword": "和膏机"}]
        result = _run(assemble_context("和膏机1号温度", skip_extraction=True))

        # _extract_entity_mentions should NOT be called
        mock_mentions.assert_not_called()
        # entity_mentions should be empty
        assert result["entity_mentions"] == []
        # entity_candidates should be empty
        assert result["entity_candidates"] == {}


class TestAssembleContextConfirmedEntities:
    """有 confirmed_entities 时自动跳过提取"""

    @patch("backend.services.agentic_qa.preprocess.build_query_blueprint", return_value={"tables": ["t1"]})
    @patch("backend.services.agentic_qa.preprocess.labels_from_confirmed", return_value=["和膏机1号"])
    @patch("backend.services.agentic_qa.preprocess.extract_entity_labels", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._search_similar_queries", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._match_schemas", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._extract_entity_mentions")
    def test_confirmed_entities_skip_extraction(self, mock_mentions, mock_schemas, mock_history, mock_ext_labels, mock_conf_labels, mock_blueprint):
        mock_mentions.return_value = [{"type": "device", "keyword": "和膏机"}]
        session_memory = {
            "confirmed_entities": [
                {"field": "device_name", "values": ["和膏机1号"]}
            ]
        }
        result = _run(assemble_context("和膏机1号温度", session_memory=session_memory))

        # _extract_entity_mentions should NOT be called
        mock_mentions.assert_not_called()
        # entity_mentions should be empty
        assert result["entity_mentions"] == []
        # confirmed_entities should be passed through
        assert result["confirmed_entities"] == [{"field": "device_name", "values": ["和膏机1号"]}]
        # labels_from_confirmed should be called with confirmed entities
        mock_conf_labels.assert_called_once_with([{"field": "device_name", "values": ["和膏机1号"]}])


class TestAssembleContextNormalFlow:
    """正常流程调用关键词提取"""

    @patch("backend.services.agentic_qa.preprocess.build_query_blueprint", return_value=None)
    @patch("backend.services.agentic_qa.preprocess.labels_from_confirmed", return_value=[])
    @patch("backend.services.agentic_qa.preprocess.extract_entity_labels", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._search_with_fallback", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._search_similar_queries", return_value=[{"question": "历史问题", "answer": "答案"}])
    @patch("backend.services.agentic_qa.preprocess._match_schemas", return_value=[{"table": "device_data", "schema": "CREATE TABLE device_data..."}])
    @patch("backend.services.agentic_qa.preprocess._extract_entity_mentions")
    def test_normal_flow_calls_mentions(self, mock_mentions, mock_schemas, mock_history, mock_search, mock_ext_labels, mock_conf_labels, mock_blueprint):
        mock_mentions.return_value = [
            {"type": "device", "keyword": "和膏机"},
        ]
        result = _run(assemble_context("和膏机1号温度"))

        # _extract_entity_mentions should be called
        mock_mentions.assert_called_once_with("和膏机1号温度")
        # entity_mentions should be populated
        assert result["entity_mentions"] == [{"type": "device", "keyword": "和膏机"}]
        # _search_with_fallback should be called for the keyword
        mock_search.assert_called_once_with("和膏机", "device")
        # entity_candidates should contain the keyword
        assert "和膏机" in result["entity_candidates"]

    @patch("backend.services.agentic_qa.preprocess.build_query_blueprint", return_value=None)
    @patch("backend.services.agentic_qa.preprocess.labels_from_confirmed", return_value=[])
    @patch("backend.services.agentic_qa.preprocess.extract_entity_labels", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._search_with_fallback", return_value=[{"label": "和膏机1号"}])
    @patch("backend.services.agentic_qa.preprocess._search_similar_queries", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._match_schemas", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._extract_entity_mentions")
    def test_normal_flow_entity_candidates_populated(self, mock_mentions, mock_schemas, mock_history, mock_search, mock_ext_labels, mock_conf_labels, mock_blueprint):
        mock_mentions.return_value = [
            {"type": "device", "keyword": "和膏机"},
            {"type": "metric", "keyword": "温度"},
        ]
        result = _run(assemble_context("和膏机1号温度"))

        assert "和膏机" in result["entity_candidates"]
        assert "温度" in result["entity_candidates"]
        assert result["entity_candidates"]["和膏机"] == [{"label": "和膏机1号"}]

    @patch("backend.services.agentic_qa.preprocess.build_query_blueprint", return_value=None)
    @patch("backend.services.agentic_qa.preprocess.labels_from_confirmed", return_value=[])
    @patch("backend.services.agentic_qa.preprocess.extract_entity_labels", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._search_with_fallback", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._search_similar_queries", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._match_schemas", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._extract_entity_mentions")
    def test_normal_flow_empty_keyword_skipped(self, mock_mentions, mock_schemas, mock_history, mock_search, mock_ext_labels, mock_conf_labels, mock_blueprint):
        mock_mentions.return_value = [
            {"type": "device", "keyword": ""},
            {"type": "metric", "keyword": "温度"},
        ]
        result = _run(assemble_context("温度是多少"))

        # empty keyword should not trigger _search_with_fallback
        mock_search.assert_called_once_with("温度", "metric")
        assert "" not in result["entity_candidates"]
        assert "温度" in result["entity_candidates"]


class TestAssembleContextSchemasAndHistory:
    """返回 relevant_schemas 和 similar_queries"""

    @patch("backend.services.agentic_qa.preprocess.build_query_blueprint", return_value=None)
    @patch("backend.services.agentic_qa.preprocess.labels_from_confirmed", return_value=[])
    @patch("backend.services.agentic_qa.preprocess.extract_entity_labels", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._search_with_fallback", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._search_similar_queries")
    @patch("backend.services.agentic_qa.preprocess._match_schemas")
    @patch("backend.services.agentic_qa.preprocess._extract_entity_mentions", return_value=[])
    def test_returns_schemas_and_history(self, mock_mentions, mock_schemas, mock_history, mock_search, mock_ext_labels, mock_conf_labels, mock_blueprint):
        mock_schemas.return_value = [
            {"table": "device_data", "schema": "CREATE TABLE device_data (id INT, name VARCHAR)"},
            {"table": "sensor_data", "schema": "CREATE TABLE sensor_data (id INT, value FLOAT)"},
        ]
        mock_history.return_value = [
            {"question": "和膏机温度", "answer": "85度", "sql": "SELECT temperature FROM device_data"},
        ]
        result = _run(assemble_context("和膏机1号温度"))

        assert len(result["relevant_schemas"]) == 2
        assert result["relevant_schemas"][0]["table"] == "device_data"
        assert len(result["similar_queries"]) == 1
        assert result["similar_queries"][0]["question"] == "和膏机温度"

    @patch("backend.services.agentic_qa.preprocess.build_query_blueprint", return_value=None)
    @patch("backend.services.agentic_qa.preprocess.labels_from_confirmed", return_value=[])
    @patch("backend.services.agentic_qa.preprocess.extract_entity_labels", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._search_similar_queries")
    @patch("backend.services.agentic_qa.preprocess._match_schemas")
    @patch("backend.services.agentic_qa.preprocess._extract_entity_mentions")
    def test_skip_extraction_still_fetches_schemas_and_history(self, mock_mentions, mock_schemas, mock_history, mock_ext_labels, mock_conf_labels, mock_blueprint):
        """skip_extraction=True 场景仍然获取 schema 和 history"""
        mock_mentions.return_value = [{"type": "device", "keyword": "和膏机"}]
        mock_schemas.return_value = [{"table": "t1", "schema": "s1"}]
        mock_history.return_value = [{"question": "q1", "answer": "a1"}]

        result = _run(assemble_context("和膏机1号温度", skip_extraction=True))

        assert result["relevant_schemas"] == [{"table": "t1", "schema": "s1"}]
        assert result["similar_queries"] == [{"question": "q1", "answer": "a1"}]
        mock_schemas.assert_called_once_with("和膏机1号温度")
        mock_history.assert_called_once_with("和膏机1号温度")


class TestAssembleContextErrorHandling:
    """_search_with_fallback 异常时 entity_candidates 对应 key 为空列表"""

    @patch("backend.services.agentic_qa.preprocess.build_query_blueprint", return_value=None)
    @patch("backend.services.agentic_qa.preprocess.labels_from_confirmed", return_value=[])
    @patch("backend.services.agentic_qa.preprocess.extract_entity_labels", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._search_with_fallback", side_effect=Exception("search error"))
    @patch("backend.services.agentic_qa.preprocess._search_similar_queries", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._match_schemas", return_value=[])
    @patch("backend.services.agentic_qa.preprocess._extract_entity_mentions")
    def test_search_fallback_exception_handled(self, mock_mentions, mock_schemas, mock_history, mock_search, mock_ext_labels, mock_conf_labels, mock_blueprint):
        mock_mentions.return_value = [{"type": "device", "keyword": "和膏机"}]
        # The exception is caught inside assemble_context via try/except
        # so entity_candidates[keyword] should be []
        result = _run(assemble_context("和膏机1号温度"))
        assert result["entity_candidates"]["和膏机"] == []


# ── format_pre_context tests ──


class TestFormatPreContext:
    """format_pre_context 格式化输出正确"""

    def test_empty_pre_context(self):
        result = format_pre_context({})
        assert result == ""

    def test_confirmed_entities(self):
        pre = {
            "confirmed_entities": [
                {"field": "device_name", "values": ["和膏机1号", "和膏机2号"]},
                {"entity_type": "metric", "selected_values": ["温度"]},
            ]
        }
        result = format_pre_context(pre)
        assert "已确认实体:" in result
        assert "device_name: 和膏机1号, 和膏机2号" in result
        assert "metric: 温度" in result

    def test_entity_candidates(self):
        pre = {
            "entity_candidates": {
                "和膏机": [
                    {"label": "和膏机1号"},
                    {"label": "和膏机2号"},
                ],
                "温度": [
                    {"label": "温度传感器A"},
                ],
            }
        }
        result = format_pre_context(pre)
        assert "候选实体 '和膏机': 和膏机1号, 和膏机2号" in result
        assert "候选实体 '温度': 温度传感器A" in result

    def test_entity_candidates_empty_skipped(self):
        pre = {
            "entity_candidates": {
                "和膏机": [],
                "温度": [{"label": "温度传感器A"}],
            }
        }
        result = format_pre_context(pre)
        assert "和膏机" not in result
        assert "候选实体 '温度': 温度传感器A" in result

    def test_entity_candidates_truncated_to_five(self):
        pre = {
            "entity_candidates": {
                "设备": [{"label": f"设备{i}"} for i in range(8)],
            }
        }
        result = format_pre_context(pre)
        # Should only include first 5 labels
        labels = [f"设备{i}" for i in range(5)]
        assert ", ".join(labels) in result
        assert "设备5" not in result

    def test_relevant_schemas(self):
        pre = {
            "relevant_schemas": [
                {"table": "device_data", "schema": "A" * 300},
            ]
        }
        result = format_pre_context(pre)
        assert "相关表Schema:" in result
        assert "device_data:" in result
        # Schema should be truncated to 200 chars
        assert "A" * 200 in result

    @patch("backend.services.agentic_qa.blueprint.format_blueprint_section", return_value="查询蓝图内容")
    def test_all_sections_combined(self, mock_bp_format):
        pre = {
            "confirmed_entities": [
                {"field": "device_name", "values": ["和膏机1号"]},
            ],
            "entity_candidates": {
                "温度": [{"label": "温度传感器A"}],
            },
            "relevant_schemas": [
                {"table": "device_data", "schema": "CREATE TABLE device_data..."},
            ],
            "query_blueprint": {"tables": ["device_data"]},
        }
        result = format_pre_context(pre)
        assert "已确认实体:" in result
        assert "候选实体 '温度': 温度传感器A" in result
        assert "相关表Schema:" in result
        assert "查询蓝图内容" in result
        # Sections are separated by double newline
        assert "\n\n" in result

    def test_confirmed_entities_empty_values_skipped(self):
        pre = {
            "confirmed_entities": [
                {"field": "device_name", "values": []},
            ],
        }
        result = format_pre_context(pre)
        assert "已确认实体" not in result

    def test_query_blueprint_none_skipped(self):
        pre = {
            "query_blueprint": None,
        }
        result = format_pre_context(pre)
        # No blueprint section should appear when blueprint is None
        assert "蓝图" not in result

    @patch("backend.services.agentic_qa.blueprint.format_blueprint_section", return_value="")
    def test_query_blueprint_empty_text_skipped(self, mock_bp_format):
        pre = {
            "query_blueprint": {"tables": ["t1"]},
        }
        result = format_pre_context(pre)
        # format_blueprint_section returns empty string, so no section added
        assert result == ""
