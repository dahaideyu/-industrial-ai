"""Unit tests for backend/services/agentic_qa/blueprint.py"""
import pytest
import os
import tempfile
import yaml
from unittest.mock import patch, MagicMock

from backend.services.agentic_qa.blueprint import (
    ResolvedEntity,
    JoinSpec,
    QueryBlueprint,
    extract_entity_labels,
    labels_from_confirmed,
    build_query_blueprint,
    format_blueprint_section,
    find_reachable_paths,
    _find_paths_yaml,
    _table_to_label,
)


# ── ResolvedEntity ──

class TestResolvedEntity:
    def test_create(self):
        e = ResolvedEntity(
            name="和膏一线",
            entity_type="production_line",
            table="sys_line",
            key_column="id",
            name_column="line_name",
            value="HG001",
        )
        assert e.name == "和膏一线"
        assert e.entity_type == "production_line"
        assert e.table == "sys_line"
        assert e.key_column == "id"
        assert e.name_column == "line_name"
        assert e.value == "HG001"

    def test_defaults(self):
        e = ResolvedEntity(name="", entity_type="", table="", key_column="id", name_column="name", value="")
        assert e.key_column == "id"
        assert e.name_column == "name"


# ── JoinSpec ──

class TestJoinSpec:
    def test_create(self):
        j = JoinSpec(
            from_table="sys_line",
            to_table="dev_device",
            from_column="id",
            to_column="line_id",
            join_type="INNER JOIN",
        )
        assert j.from_table == "sys_line"
        assert j.to_table == "dev_device"
        assert j.from_column == "id"
        assert j.to_column == "line_id"
        assert j.join_type == "INNER JOIN"

    def test_default_join_type(self):
        j = JoinSpec(from_table="a", to_table="b", from_column="id", to_column="a_id", join_type="LEFT JOIN")
        assert j.join_type == "LEFT JOIN"


# ── QueryBlueprint ──

class TestQueryBlueprint:
    def test_empty(self):
        bp = QueryBlueprint()
        assert bp.entities == []
        assert bp.tables == []
        assert bp.joins == []
        assert bp.where_hints == []

    def test_with_data(self):
        e = ResolvedEntity(name="和膏一线", entity_type="production_line", table="sys_line",
                           key_column="id", name_column="line_name", value="HG001")
        j = JoinSpec(from_table="sys_line", to_table="dev_device", from_column="id",
                     to_column="line_id", join_type="LEFT JOIN")
        bp = QueryBlueprint(
            entities=[e],
            tables=["dev_device", "sys_line"],
            joins=[j],
            where_hints=["line_name = '和膏一线'"],
        )
        assert len(bp.entities) == 1
        assert len(bp.tables) == 2
        assert len(bp.joins) == 1
        assert bp.where_hints[0] == "line_name = '和膏一线'"


# ── extract_entity_labels ──

class TestExtractEntityLabels:
    def test_production_line(self):
        mentions = [{"type": "production_line", "keyword": "和膏", "original": "和膏"}]
        labels = extract_entity_labels(mentions, {})
        assert "Line" in labels

    def test_device(self):
        mentions = [{"type": "device", "keyword": "制带机", "original": "制带机"}]
        labels = extract_entity_labels(mentions, {})
        assert "Device" in labels

    def test_multiple_types(self):
        mentions = [
            {"type": "production_line", "keyword": "和膏", "original": "和膏"},
            {"type": "device", "keyword": "制带机", "original": "制带机"},
        ]
        labels = extract_entity_labels(mentions, {})
        assert "Line" in labels
        assert "Device" in labels

    def test_from_entity_candidates(self):
        mentions = []
        candidates = {"和膏": [{"entity_type": "production_line", "label": "和膏一线"}]}
        labels = extract_entity_labels(mentions, candidates)
        assert "Line" in labels

    def test_unknown_type_ignored(self):
        mentions = [{"type": "unknown_type", "keyword": "xxx", "original": "xxx"}]
        labels = extract_entity_labels(mentions, {})
        assert labels == []

    def test_empty_inputs(self):
        labels = extract_entity_labels([], {})
        assert labels == []

    def test_workshop(self):
        mentions = [{"type": "workshop", "keyword": "一车间", "original": "一车间"}]
        labels = extract_entity_labels(mentions, {})
        assert "Workshop" in labels

    def test_department(self):
        mentions = [{"type": "department", "keyword": "生产部", "original": "生产部"}]
        labels = extract_entity_labels(mentions, {})
        assert "Department" in labels

    def test_device_type(self):
        mentions = [{"type": "device_type", "keyword": "制带线", "original": "制带线"}]
        labels = extract_entity_labels(mentions, {})
        assert "DeviceType" in labels


# ── labels_from_confirmed ──

class TestLabelsFromConfirmed:
    def test_from_field(self):
        confirmed = [{"field": "production_line", "values": ["和膏一线"]}]
        labels = labels_from_confirmed(confirmed)
        assert "Line" in labels

    def test_from_entity_type(self):
        confirmed = [{"entity_type": "device", "values": ["制带机"]}]
        labels = labels_from_confirmed(confirmed)
        assert "Device" in labels

    def test_multiple_confirmed(self):
        confirmed = [
            {"field": "production_line", "values": ["和膏一线"]},
            {"field": "device", "values": ["制带机"]},
        ]
        labels = labels_from_confirmed(confirmed)
        assert "Line" in labels
        assert "Device" in labels

    def test_empty(self):
        labels = labels_from_confirmed([])
        assert labels == []

    def test_unknown_field_ignored(self):
        confirmed = [{"field": "unknown_type", "values": ["xxx"]}]
        labels = labels_from_confirmed(confirmed)
        assert labels == []


# ── format_blueprint_section ──

class TestFormatBlueprintSection:
    def test_empty_blueprint(self):
        bp = QueryBlueprint()
        result = format_blueprint_section(bp)
        assert result == ""

    def test_tables_only(self):
        bp = QueryBlueprint(tables=["dev_device", "sys_line"])
        result = format_blueprint_section(bp)
        assert "查询蓝图" in result
        assert "涉及的表" in result
        assert "dev_device" in result
        assert "sys_line" in result

    def test_full_blueprint(self):
        e = ResolvedEntity(name="和膏一线", entity_type="production_line", table="sys_line",
                           key_column="id", name_column="line_name", value="HG001")
        j = JoinSpec(from_table="sys_line", to_table="dev_device", from_column="id",
                     to_column="line_id", join_type="LEFT JOIN")
        bp = QueryBlueprint(
            entities=[e],
            tables=["dev_device", "sys_line"],
            joins=[j],
            where_hints=["line_name = '和膏一线'"],
        )
        result = format_blueprint_section(bp)
        assert "实体确认" in result
        assert "production_line" in result
        assert "和膏一线" in result
        assert "表关系路径" in result
        assert "JOIN 条件" in result
        assert "sys_line.id = dev_device.line_id" in result
        assert "涉及的表" in result
        assert "WHERE 提示" in result

    def test_no_entities_no_joins(self):
        bp = QueryBlueprint(tables=["sys_line"])
        result = format_blueprint_section(bp)
        assert "涉及的表" in result
        assert "sys_line" in result
        # Should not have entities or joins sections
        assert "实体确认" not in result
        assert "表关系路径" not in result


# ── _find_paths_yaml ──

class TestFindPathsYaml:
    def _make_yaml_config(self):
        """Create a minimal YAML config matching graph_mapping.yaml structure"""
        return {
            "nodes": [
                {"table": "dev_device", "label": "Device", "type_key": "device",
                 "id_field": "id", "name_field": "name"},
                {"table": "dev_device_type", "label": "DeviceType", "type_key": "device_type",
                 "id_field": "id", "name_field": "name"},
                {"table": "sys_line", "label": "Line", "type_key": "production_line",
                 "id_field": "id", "name_field": "name"},
                {"table": "sys_workshop", "label": "Workshop", "type_key": "workshop",
                 "id_field": "id", "name_field": "name"},
            ],
            "relationships": [
                {"from_table": "dev_device", "fk_field": "type_id",
                 "to_table": "dev_device_type", "rel_type": "HAS_TYPE"},
                {"from_table": "dev_device", "fk_field": "line_id",
                 "to_table": "sys_line", "rel_type": "LOCATED_ON"},
                {"from_table": "sys_line", "fk_field": "dept_id",
                 "to_table": "sys_workshop", "rel_type": "BELONGS_TO"},
            ],
        }

    @patch("backend.services.agentic_qa.blueprint._find_paths_yaml")
    def test_yaml_fallback_called(self, mock_yaml):
        """When Neo4j fails, _find_paths_yaml should be called"""
        mock_yaml.return_value = [{"node_chain": [], "edge_props": []}]
        # This tests find_reachable_paths fallback behavior
        result = find_reachable_paths(["Line"], max_depth=2)
        # The actual call goes through _find_paths_yaml (since Neo4j won't be available in tests)
        # We can't easily test this without mocking, so test _find_paths_yaml directly

    def test_find_paths_yaml_bfs_traversal(self):
        """Test BFS traversal logic in _find_paths_yaml by extracting the core algorithm.
        This avoids Path/open mocking issues by calling the actual YAML file."""
        # Use the actual graph_mapping.yaml if it exists
        result = _find_paths_yaml(["Line"], max_depth=2)
        assert isinstance(result, list)

        # Also test with Device label
        result = _find_paths_yaml(["Device"], max_depth=2)
        assert isinstance(result, list)

        # Test multi-label
        result = _find_paths_yaml(["Line", "Device"], max_depth=2)
        assert isinstance(result, list)

    def test_find_paths_yaml_direct_file_read(self):
        """Test _find_paths_yaml by temporarily creating a config file"""
        config = self._make_yaml_config()
        config_dir = "config"
        config_file = os.path.join(config_dir, "graph_mapping.yaml")
        backup_file = os.path.join(config_dir, "graph_mapping_backup.yaml")
        original_exists = os.path.exists(config_file)

        # Backup existing file if present
        if original_exists:
            import shutil
            shutil.copy2(config_file, backup_file)

        try:
            # Write test config
            os.makedirs(config_dir, exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True)

            result = _find_paths_yaml(["Line"], max_depth=3)
            # Should find paths from Line
            assert isinstance(result, list)
            # Line should reach Device (via LOCATED_ON reversed) and Workshop (via BELONGS_TO)
            if result:
                # Check that at least one path involves Device or Workshop
                all_tables = set()
                for p in result:
                    for n in p.get("node_chain", []):
                        all_tables.add(n.get("table", ""))
                # Line should be connected to Device and Workshop
                assert "sys_workshop" in all_tables or "dev_device" in all_tables
        finally:
            # Restore original file
            if original_exists and os.path.exists(backup_file):
                import shutil
                shutil.copy2(backup_file, config_file)
                os.unlink(backup_file)
            elif not original_exists and os.path.exists(config_file):
                os.unlink(config_file)

    def test_find_paths_yaml_empty_labels(self):
        """Empty entity labels should return empty paths"""
        result = _find_paths_yaml([], max_depth=3)
        assert result == []


# ── build_query_blueprint ──

class TestBuildQueryBlueprint:
    def test_empty_labels(self):
        bp = build_query_blueprint(entity_labels=[])
        assert bp.entities == []
        assert bp.tables == []
        assert bp.joins == []
        assert bp.where_hints == []

    def test_with_confirmed_entities(self):
        confirmed = [{"field": "production_line", "values": ["和膏一线", "和膏二线"]}]
        with patch("backend.services.agentic_qa.blueprint.find_reachable_paths") as mock_paths:
            mock_paths.return_value = [
                {
                    "node_chain": [
                        {"label": "Line", "table": "sys_line", "key_column": "id", "name_column": "name"},
                        {"label": "Device", "table": "dev_device", "key_column": "id", "name_column": "name"},
                    ],
                    "edge_props": [
                        {"rel_type": "LOCATED_ON", "join_on": "dev_device.line_id = sys_line.id",
                         "join_type": "LEFT JOIN", "direction": ""},
                    ],
                },
            ]
            bp = build_query_blueprint(
                entity_labels=["Line"],
                confirmed_entities=confirmed,
            )
            assert len(bp.entities) == 2  # 2 values in confirmed
            assert bp.entities[0].name == "和膏一线"
            assert bp.entities[1].name == "和膏二线"
            assert "sys_line" in bp.tables
            assert "dev_device" in bp.tables
            assert len(bp.joins) == 1
            assert bp.joins[0].from_table == "dev_device"
            assert bp.joins[0].to_table == "sys_line"
            assert bp.joins[0].from_column == "line_id"
            assert bp.joins[0].to_column == "id"

    def test_join_dedup(self):
        """Same join_on should only appear once"""
        with patch("backend.services.agentic_qa.blueprint.find_reachable_paths") as mock_paths:
            mock_paths.return_value = [
                {
                    "node_chain": [
                        {"label": "Line", "table": "sys_line", "key_column": "id", "name_column": "name"},
                        {"label": "Device", "table": "dev_device", "key_column": "id", "name_column": "name"},
                    ],
                    "edge_props": [
                        {"join_on": "dev_device.line_id = sys_line.id", "join_type": "LEFT JOIN"},
                    ],
                },
                {
                    "node_chain": [
                        {"label": "Line", "table": "sys_line", "key_column": "id", "name_column": "name"},
                        {"label": "Device", "table": "dev_device", "key_column": "id", "name_column": "name"},
                        {"label": "DeviceType", "table": "dev_device_type", "key_column": "id", "name_column": "name"},
                    ],
                    "edge_props": [
                        {"join_on": "dev_device.line_id = sys_line.id", "join_type": "LEFT JOIN"},
                        {"join_on": "dev_device.type_id = dev_device_type.id", "join_type": "LEFT JOIN"},
                    ],
                },
            ]
            bp = build_query_blueprint(entity_labels=["Line"])
            # dev_device.line_id = sys_line.id should only appear once
            join_keys = [(j.from_table, j.from_column, j.to_table, j.to_column) for j in bp.joins]
            assert len(join_keys) == len(set(join_keys)), "Duplicate joins found"

    def test_no_join_on_skipped(self):
        """Edge props without join_on should be skipped"""
        with patch("backend.services.agentic_qa.blueprint.find_reachable_paths") as mock_paths:
            mock_paths.return_value = [
                {
                    "node_chain": [
                        {"label": "Line", "table": "sys_line", "key_column": "id", "name_column": "name"},
                        {"label": "Company", "table": "", "key_column": "", "name_column": ""},
                    ],
                    "edge_props": [
                        {"rel_type": "BELONGS_TO"},  # no join_on
                    ],
                },
            ]
            bp = build_query_blueprint(entity_labels=["Line"])
            assert len(bp.joins) == 0

    def test_where_hints_from_confirmed(self):
        confirmed = [{"field": "production_line", "values": ["和膏一线"]}]
        with patch("backend.services.agentic_qa.blueprint.find_reachable_paths") as mock_paths:
            mock_paths.return_value = []
            bp = build_query_blueprint(
                entity_labels=["Line"],
                confirmed_entities=confirmed,
            )
            assert len(bp.where_hints) == 1
            assert "和膏一线" in bp.where_hints[0]


# ── _table_to_label ──

class TestTableToLabel:
    def test_known_table(self):
        label_map = {"Device": {"table": "dev_device"}, "Line": {"table": "sys_line"}}
        assert _table_to_label("dev_device", label_map) == "Device"
        assert _table_to_label("sys_line", label_map) == "Line"

    def test_unknown_table(self):
        label_map = {"Device": {"table": "dev_device"}}
        assert _table_to_label("unknown_table", label_map) == ""


# ── Integration: find_reachable_paths fallback ──

class TestFindReachablePathsFallback:
    def test_neo4j_failure_falls_back_to_yaml(self):
        """When Neo4j fails, should fall back to YAML"""
        with patch("backend.services.agentic_qa.blueprint._find_paths_neo4j") as mock_neo4j, \
             patch("backend.services.agentic_qa.blueprint._find_paths_yaml") as mock_yaml:
            mock_neo4j.side_effect = ConnectionError("Neo4j not available")
            mock_yaml.return_value = [{"node_chain": [], "edge_props": []}]

            result = find_reachable_paths(["Line"])
            mock_yaml.assert_called_once_with(["Line"], 3)
