# cython: annotation_typing=False, infer_types=False, language_level=3
# backend/services/agentic_qa/blueprint.py
"""查询蓝图生成 — 从 Neo4j 语义层生成查询路径和 JOIN 映射"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("agentic_qa.blueprint")

# 实体类型 → Neo4j label 映射（extract_entity_labels / labels_from_confirmed 共用，避免重复定义）
TYPE_TO_LABEL = {
    "production_line": "Line",
    "device": "Device",
    "device_type": "DeviceType",
    "workshop": "Workshop",
    "department": "Department",
    "alarm": "Alarm",
    "repair_order": "RepairOrder",
}


@dataclass
class ResolvedEntity:
    """已解析的实体"""
    name: str            # "和膏一线"
    entity_type: str     # "production_line"
    table: str           # "sys_line"
    key_column: str      # "id"
    name_column: str     # "line_name"
    value: str           # 实际值（如数据库中的 ID 或名称）


@dataclass
class JoinSpec:
    """JOIN 规范"""
    from_table: str      # "sys_line"
    to_table: str        # "dev_device"
    from_column: str     # "id"
    to_column: str       # "line_id"
    join_type: str       # "INNER JOIN" / "LEFT JOIN"


@dataclass
class QueryBlueprint:
    """查询蓝图 — 从候选实体生成的查询路径"""
    entities: List[ResolvedEntity] = field(default_factory=list)
    tables: List[str] = field(default_factory=list)
    joins: List[JoinSpec] = field(default_factory=list)
    where_hints: List[str] = field(default_factory=list)


def find_reachable_paths(entity_labels: List[str], max_depth: int = 3) -> List[Dict]:
    """从候选实体节点出发，BFS 遍历所有可达路径。

    优先使用 Neo4j 图查询，如果 Neo4j 不可用则回退到 YAML 配置。

    Args:
        entity_labels: 候选实体的 Neo4j label 列表，如 ["Line", "Device"]
        max_depth: 最大跳数，默认3

    Returns:
        路径列表，每条包含 node_chain + edge_props
    """
    # 先尝试 Neo4j
    try:
        return _find_paths_neo4j(entity_labels, max_depth)
    except Exception as e:
        logger.debug(f"[blueprint] Neo4j query failed, falling back to YAML: {e}")
        return _find_paths_yaml(entity_labels, max_depth)


def _find_paths_neo4j(entity_labels: List[str], max_depth: int) -> List[Dict]:
    """使用 Neo4j 图查询可达路径"""
    from backend.core.agentic_qa.graph_client import get_graph_client

    client = get_graph_client()
    if not client.is_available():
        raise ConnectionError("Neo4j driver not available")

    driver = client.driver
    paths = []
    visited = set()

    with driver.session() as session:
        # Load YAML metadata for enriching Neo4j results
        yaml_nodes, yaml_rels = _load_yaml_metadata()

        for label in entity_labels:
            # Cypher: 从指定 label 出发，遍历所有关系（只查Neo4j中有的属性: name, id）
            query = """
            MATCH path = (start:%s)-[r*1..%d]-(end)
            RETURN [n IN nodes(path) | {
                label: labels(n)[0],
                name: n.name,
                id: n.id
            }] AS node_chain,
            [e IN relationships(path) | {
                rel_type: type(e)
            }] AS edge_props
            """ % (label, max_depth)

            results = session.run(query)
            for record in results:
                chain_key = tuple(n.get("label", "") for n in record["node_chain"])
                if chain_key not in visited:
                    visited.add(chain_key)
                    # Enrich Neo4j results with YAML metadata (table, key_column, name_column, join_on)
                    enriched_nodes = _enrich_nodes(record["node_chain"], yaml_nodes)
                    enriched_edges = _enrich_edges(record["edge_props"], enriched_nodes, yaml_rels)
                    paths.append({
                        "node_chain": enriched_nodes,
                        "edge_props": enriched_edges,
                    })

    return paths


def _load_yaml_metadata():
    """从 graph_mapping.yaml 加载节点和关系元数据。"""
    import yaml
    from pathlib import Path
    yaml_path = Path("backend/config/graph_mapping.yaml")
    nodes_by_label = {}
    rels = []
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        for nd in cfg.get("nodes", []):
            nodes_by_label[nd.get("label", "")] = nd
        for nd in cfg.get("manual_nodes", []):
            nodes_by_label[nd.get("label", "")] = nd
        rels = cfg.get("relationships", []) + cfg.get("manual_relationships", [])
    return nodes_by_label, rels


def _enrich_nodes(neo4j_nodes, yaml_nodes):
    """用 YAML 元数据补充 Neo4j 节点（table, key_column, name_column）。"""
    result = []
    for n in neo4j_nodes:
        label = n.get("label", "")
        yaml_info = yaml_nodes.get(label, {})
        result.append({
            "label": label,
            "name": n.get("name", ""),
            "table": yaml_info.get("table", ""),
            "key_column": yaml_info.get("id_field", ""),
            "name_column": yaml_info.get("name_field", ""),
        })
    return result


def _enrich_edges(neo4j_edges, enriched_nodes, yaml_rels):
    """用 YAML 元数据补充 Neo4j 关系边（join_on, join_type, direction）。"""
    result = []
    node_tables = {n["label"]: n for n in enriched_nodes}
    for i, e in enumerate(neo4j_edges):
        rel_type = e.get("rel_type", "")
        edge_info = {}
        for yr in yaml_rels:
            if yr.get("rel_type") == rel_type:
                edge_info = yr
                break
        # Determine direction from node positions: node i → edge i → node i+1
        join_on = edge_info.get("fk_field", "")
        join_type = "LEFT JOIN"  # default, can be refined
        result.append({
            "rel_type": rel_type,
            "join_on": join_on,
            "join_type": join_type,
            "direction": "forward",
        })
    return result


def _find_paths_yaml(entity_labels: List[str], max_depth: int) -> List[Dict]:
    """回退方案：从 YAML 配置生成可达路径"""
    import yaml
    from pathlib import Path

    yaml_path = Path("backend/config/graph_mapping.yaml")
    if not yaml_path.exists():
        logger.warning("[blueprint] graph_mapping.yaml not found")
        return []

    with open(yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    nodes_cfg = config.get("nodes", [])
    rels_cfg = config.get("relationships", [])

    # 构建 label -> node config 映射
    label_map = {}
    for n in nodes_cfg:
        label_map[n.get("label", "")] = n

    # 构建邻接表
    adjacency = {}  # label -> [(target_label, rel_props)]
    for r in rels_cfg:
        from_label = _table_to_label(r.get("from_table", ""), label_map)
        to_label = _table_to_label(r.get("to_table", ""), label_map)
        if from_label and to_label:
            # 构建 join_on 字符串: from_table.fk_field = to_table.id_field
            from_table = r.get("from_table", "")
            fk_field = r.get("fk_field", "")
            to_table = r.get("to_table", "")
            to_id_field = label_map.get(to_label, {}).get("id_field", "id")
            join_on = f"{from_table}.{fk_field} = {to_table}.{to_id_field}" if fk_field else ""

            rel_entry = {
                "rel_type": r.get("rel_type", ""),
                "join_on": join_on,
                "join_type": r.get("join_type", "LEFT JOIN"),
                "direction": r.get("direction", ""),
            }
            adjacency.setdefault(from_label, []).append((to_label, rel_entry))
            adjacency.setdefault(to_label, []).append((from_label, rel_entry))

    # BFS 遍历
    paths = []
    visited = set()

    for start_label in entity_labels:
        # BFS
        queue = [([start_label], [])]
        while queue:
            current_chain, current_edges = queue.pop(0)
            if len(current_chain) > max_depth + 1:
                continue

            current = current_chain[-1]
            chain_key = tuple(current_chain)
            if chain_key in visited:
                continue
            visited.add(chain_key)

            if len(current_chain) > 1:
                node_chain = []
                for lbl in current_chain:
                    ncfg = label_map.get(lbl, {})
                    node_chain.append({
                        "label": lbl,
                        "table": ncfg.get("table", ""),
                        "key_column": ncfg.get("id_field", "id"),
                        "name_column": ncfg.get("name_field", "name"),
                    })
                paths.append({
                    "node_chain": node_chain,
                    "edge_props": current_edges,
                })

            # 继续遍历邻居
            for next_label, rel_props in adjacency.get(current, []):
                if next_label not in current_chain:  # 避免环
                    new_edges = current_edges + [rel_props]
                    queue.append((current_chain + [next_label], new_edges))

    return paths


def _table_to_label(table_name: str, label_map: dict) -> str:
    """从表名反查 label"""
    for label, cfg in label_map.items():
        if cfg.get("table", "") == table_name:
            return label
    return ""


def build_query_blueprint(
    entity_labels: List[str],
    entity_candidates: Dict = None,
    confirmed_entities: List[Dict] = None,
) -> QueryBlueprint:
    """从候选实体生成查询蓝图。

    Args:
        entity_labels: 实体 Neo4j label 列表
        entity_candidates: 实体搜索结果
        confirmed_entities: 已确认实体列表
    """
    if not entity_labels:
        return QueryBlueprint()

    paths = find_reachable_paths(entity_labels)

    # 去重：同一 (from_table, to_table) 只保留一条 JOIN
    seen_joins = set()
    joins = []
    tables = set()

    for p in paths:
        for n in p.get("node_chain", []):
            tbl = n.get("table", "")
            if tbl:
                tables.add(tbl)

        for e in p.get("edge_props", []):
            join_on = e.get("join_on", "")
            if not join_on:
                continue
            if join_on not in seen_joins:
                seen_joins.add(join_on)
                # 解析 join_on 格式: "dev_device.line_id = sys_line.id"
                parts = join_on.split("=")
                if len(parts) == 2:
                    left = parts[0].strip()
                    right = parts[1].strip()
                    left_parts = left.split(".")
                    right_parts = right.split(".")
                    joins.append(JoinSpec(
                        from_table=left_parts[0] if len(left_parts) > 1 else "",
                        to_table=right_parts[0] if len(right_parts) > 1 else "",
                        from_column=left_parts[1] if len(left_parts) > 1 else left,
                        to_column=right_parts[1] if len(right_parts) > 1 else right,
                        join_type=e.get("join_type", "LEFT JOIN"),
                    ))

    # 构建已解析实体
    resolved = []
    if confirmed_entities:
        for ec in confirmed_entities:
            field = ec.get("field", ec.get("entity_type", ""))
            values = ec.get("values", ec.get("selected_values", []))
            for v in values:
                resolved.append(ResolvedEntity(
                    name=str(v),
                    entity_type=field,
                    table="",  # 从 blueprint 的 tables 推断
                    key_column="id",
                    name_column="name",
                    value=str(v),
                ))

    # WHERE 提示
    where_hints = []
    for ent in resolved:
        if ent.name:
            # 不臆造具体列名（resolved 实体的 name_column 此处为占位默认值，未必匹配真实列名），
            # 仅提示需按该实体过滤，由 LLM 结合 schema 选择正确的名称列。
            where_hints.append(f"{ent.entity_type} = '{ent.name}'（请在该实体对应的名称列上过滤）")

    return QueryBlueprint(
        entities=resolved,
        tables=sorted(tables),
        joins=joins,
        where_hints=where_hints,
    )


def format_blueprint_section(blueprint: QueryBlueprint) -> str:
    """将查询蓝图格式化为注入 system prompt 的文本。"""
    if not blueprint.tables and not blueprint.joins:
        return ""

    parts = ["## 查询蓝图（基于知识图谱语义层）"]

    # 实体确认
    if blueprint.entities:
        entity_lines = []
        for e in blueprint.entities:
            entity_lines.append(f"- {e.entity_type}: {e.name}")
        parts.append("\n### 实体确认\n" + "\n".join(entity_lines))

    # 表关系路径
    if blueprint.joins:
        path_parts = []
        for i, j in enumerate(blueprint.joins):
            path_parts.append(f"{j.from_table} ──[{j.from_column} = {j.to_column}]──▶ {j.to_table}")
        parts.append("\n### 表关系路径（全路径注入，LLM 自行选择需要的路径）\n" + "\n".join(f"路径{i+1}: {p}" for i, p in enumerate(path_parts)))

        # JOIN 条件
        join_lines = [f"{i+1}. {j.from_table}.{j.from_column} = {j.to_table}.{j.to_column}" for i, j in enumerate(blueprint.joins)]
        parts.append("\n### JOIN 条件\n" + "\n".join(join_lines))

    # 涉及的表
    if blueprint.tables:
        parts.append("\n### 涉及的表\n" + ", ".join(blueprint.tables))

    # WHERE 提示
    if blueprint.where_hints:
        parts.append("\n### WHERE 提示\n" + "\n".join(f"- {h}" for h in blueprint.where_hints))

    return "\n".join(parts)


def extract_entity_labels(mentions: list, entity_candidates: dict) -> List[str]:
    """从实体关键词提取结果推断 Neo4j label。

    映射关系：
    - type="production_line" -> "Line"
    - type="device" -> "Device"
    - type="device_type" -> "DeviceType"
    - type="workshop" -> "Workshop"
    - type="department" -> "Department"
    - type="alarm" -> "Alarm"
    - type="repair_order" -> "RepairOrder"
    """
    labels = set()
    for m in mentions:
        etype = m.get("type", "")
        label = TYPE_TO_LABEL.get(etype)
        if label:
            labels.add(label)

    # 从 entity_candidates 推断
    for keyword, candidates in entity_candidates.items():
        for c in candidates[:3]:
            etype = c.get("entity_type", c.get("type", ""))
            label = TYPE_TO_LABEL.get(etype)
            if label:
                labels.add(label)

    return list(labels)


def labels_from_confirmed(confirmed: list) -> List[str]:
    """从 confirmed_entities 推断 Neo4j label"""
    labels = set()
    for ec in confirmed:
        field = ec.get("field", ec.get("entity_type", ""))
        label = TYPE_TO_LABEL.get(field)
        if label:
            labels.add(label)
    return list(labels)
