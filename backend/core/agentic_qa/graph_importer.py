# cython: annotation_typing=False, infer_types=False, language_level=3
"""Neo4j 知识图谱导入 — 读取 YAML + MySQL → 写入 Neo4j

所有表→Label 映射从 YAML nodes 动态派生，不做硬编码。
"""
import yaml
import time
from typing import Dict, Any, List, Tuple, Optional
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("core.graph_importer")


def load_mapping(path: str) -> dict:
    """加载并验证 graph_mapping.yaml"""
    with open(path, "r", encoding="utf-8") as f:
        mapping = yaml.safe_load(f)

    required_keys = ["nodes", "relationships"]
    for key in required_keys:
        if key not in mapping:
            raise ValueError(f"graph_mapping.yaml 缺少必要字段: {key}")

    node_fields = ["table", "label", "type_key", "label_zh", "id_field", "name_field"]
    for i, node_def in enumerate(mapping.get("nodes", [])):
        for field in node_fields:
            if field not in node_def:
                raise ValueError(f"nodes[{i}] 缺少必要字段: {field}")

    rel_fields = ["from_table", "fk_field", "to_table", "rel_type"]
    for i, rel_def in enumerate(mapping.get("relationships", [])):
        for field in rel_fields:
            if field not in rel_def:
                raise ValueError(f"relationships[{i}] 缺少必要字段: {field}")

    manual_fields = ["label", "type_key", "label_zh", "id", "name"]
    for i, mn in enumerate(mapping.get("manual_nodes", [])):
        for field in manual_fields:
            if field not in mn:
                raise ValueError(f"manual_nodes[{i}] 缺少必要字段: {field}")

    return mapping


def _build_table_label_map(nodes: list) -> Dict[str, str]:
    """从 nodes 配置构建 table → label 映射"""
    return {n["table"]: n["label"] for n in nodes if n.get("table")}


def import_to_neo4j(graph_client, mysql_db, mapping: dict = None,
                    mapping_path: str = None) -> Dict[str, Any]:
    """主入口：从 MySQL 导入实体和关系到 Neo4j

    返回: {"success": bool, "nodes_created": int, "relationships_created": int,
            "manual_nodes": int, "manual_relationships": int, "errors": List[str]}
    """
    if mapping is None and mapping_path:
        mapping = load_mapping(mapping_path)
    if mapping is None:
        return {"success": False, "errors": ["没有提供 mapping 数据"]}

    if not graph_client.is_available():
        return {"success": False, "errors": ["Neo4j 不可用"]}

    errors = []
    nodes_created = 0
    rels_created = 0
    manual_nodes = 0
    manual_rels = 0

    t0 = time.time()
    nodes_config = mapping.get("nodes", [])
    manual_config = mapping.get("manual_nodes", [])
    table_label_map = _build_table_label_map(nodes_config)

    # 1. Create constraints and indexes (dynamic from YAML)
    try:
        _create_constraints(graph_client, nodes_config, manual_config)
    except Exception as e:
        errors.append(f"创建约束失败: {e}")

    try:
        _create_fulltext_index(graph_client, nodes_config, manual_config)
    except Exception as e:
        errors.append(f"创建全文索引失败: {e}")

    # 2. Import nodes from MySQL tables
    node_filters = {n["table"]: n.get("filter", "") for n in nodes_config}

    for node_def in nodes_config:
        try:
            count, errs = _merge_nodes(graph_client, node_def, mysql_db)
            nodes_created += count
            errors.extend(errs)
        except Exception as e:
            errors.append(f"导入节点 {node_def.get('label', '?')} 失败: {e}")

    # 3. Import relationships (uses node configs for id_field / label resolution)
    for rel_def in mapping.get("relationships", []):
        try:
            from_filter = node_filters.get(rel_def["from_table"], "")
            count, errs = _merge_relationships(
                graph_client, rel_def, from_filter, mysql_db, table_label_map, nodes_config
            )
            rels_created += count
            errors.extend(errs)
        except Exception as e:
            errors.append(f"导入关系 {rel_def.get('rel_type', '?')} 失败: {e}")

    # 4. Import manual nodes
    for mn in manual_config:
        try:
            _merge_manual_node(graph_client, mn)
            manual_nodes += 1
        except Exception as e:
            errors.append(f"导入手工节点 {mn.get('label', '?')} 失败: {e}")

    # 5. Import manual relationships
    for mr in mapping.get("manual_relationships", []):
        try:
            _merge_manual_relationship(graph_client, mr)
            manual_rels += 1
        except Exception as e:
            errors.append(f"导入手工关系 {mr.get('rel_type', '?')} 失败: {e}")

    elapsed = time.time() - t0
    success = len([e for e in errors if "失败" in e or "错误" in e]) == 0

    logger.info(
        f"[graph] 导入完成 ({elapsed:.1f}s): "
        f"节点={nodes_created} 关系={rels_created} "
        f"手工节点={manual_nodes} 手工关系={manual_rels} "
        f"错误={len(errors)}"
    )

    return {
        "success": success,
        "nodes_created": nodes_created,
        "relationships_created": rels_created,
        "manual_nodes": manual_nodes,
        "manual_relationships": manual_rels,
        "errors": errors,
    }


def _create_constraints(graph_client, nodes: list, manual_nodes: list):
    """为每个节点 Label 创建 id 唯一约束（从 YAML 动态派生）"""
    all_labels = {n["label"] for n in nodes}
    all_labels.update(mn["label"] for mn in manual_nodes)

    for label in all_labels:
        safe_label = _safe_identifier(label)
        query = (
            f"CREATE CONSTRAINT IF NOT EXISTS "
            f"FOR (n:{safe_label}) REQUIRE n.id IS UNIQUE"
        )
        try:
            with graph_client.driver.session() as session:
                session.run(query)
                logger.info(f"[graph] 约束创建/确认: {label}.id")
        except Exception as e:
            logger.warning(f"[graph] 约束创建失败 {label}: {e}")


def _create_fulltext_index(graph_client, nodes: list, manual_nodes: list):
    """创建 CJK 全文索引，覆盖所有节点 Label 的 name 和 aliases（从 YAML 动态派生）"""
    all_labels = sorted({n["label"] for n in nodes} | {mn["label"] for mn in manual_nodes})
    label_expr = "|".join(all_labels)

    query = (
        f"CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS "
        f"FOR (n:{label_expr}) "
        f"ON EACH [n.name, n.aliases] "
        f"OPTIONS {{indexConfig: {{`fulltext.analyzer`: 'cjk'}}}}"
    )
    try:
        with graph_client.driver.session() as session:
            session.run(query)
            logger.info("[graph] CJK 全文索引创建/确认: entity_fulltext")
    except Exception as e:
        logger.warning(f"[graph] 全文索引创建失败: {e}")


def _merge_nodes(graph_client, node_def: dict, mysql_db) -> Tuple[int, List[str]]:
    """从 MySQL 查询数据并批量 MERGE 到 Neo4j"""
    table = node_def["table"]
    label = node_def["label"]
    id_field = node_def["id_field"]
    name_field = node_def["name_field"]
    alias_fields = node_def.get("alias_fields", [])
    manual_aliases = node_def.get("manual_aliases", {})
    filter_clause = node_def.get("filter", "")

    safe_label = _safe_identifier(label)

    select_fields = [id_field, name_field] + [f for f in alias_fields if f != name_field]
    select_str = ", ".join(set(select_fields))
    sql = f"SELECT {select_str} FROM {table}"
    if filter_clause:
        sql += f" WHERE {filter_clause}"

    logger.info(f"[graph] 查询 {label}: {sql}")
    try:
        rows = mysql_db.execute_query(sql)
    except Exception as e:
        return 0, [f"查询表 {table} 失败: {e}"]

    if not rows:
        logger.warning(f"[graph] {label} 表无数据")
        return 0, []

    alias_columns = [f for f in alias_fields if f != name_field]

    safe_id = _safe_identifier(id_field)
    safe_name = _safe_identifier(name_field)
    cypher = """
        UNWIND $rows AS row
        MERGE (n:{} {{}})
        SET n.name = row.{},
            n.last_update = timestamp(),
            n.source = 'mysql'
        WITH n, row
        UNWIND coalesce(n.aliases, []) + [row.{}] + row._alias_extras + row._manual_aliases AS alias_item
        WITH n, row, collect(DISTINCT alias_item) AS new_aliases
        SET n.aliases = [x IN new_aliases WHERE x IS NOT NULL AND x <> '']
    """.format(safe_label, id, safe_name, safe_name)

    batch_rows = []
    for row in rows:
        alias_extras = [str(row[c]) for c in alias_columns if row.get(c)]
        row_manual = manual_aliases.get(str(row.get(id_field, "")), [])
        batch_rows.append({
            _safe_identifier(k): str(v) if v is not None else ""
            for k, v in row.items()
        })
        batch_rows[-1]["_alias_extras"] = alias_extras
        batch_rows[-1]["_manual_aliases"] = row_manual

    batch_size = 500
    total = 0
    for i in range(0, len(batch_rows), batch_size):
        batch = batch_rows[i:i + batch_size]
        try:
            with graph_client.driver.session() as session:
                session.run(cypher, rows=batch)
                total += len(batch)
        except Exception as e:
            return total, [f"导入 {label} batch {i} 失败: {e}"]

    logger.info(f"[graph] {label}: 导入 {total} 个节点")
    return total, []


def _merge_relationships(graph_client, rel_def: dict, from_filter: str,
                         mysql_db, table_label_map: Dict[str, str],
                         nodes_config: list) -> Tuple[int, List[str]]:
    """从 MySQL 查询源表 PK + FK，MERGE 关系边到 Neo4j

    源节点始终用其 id_field (PK) 标识，FK 值即为目标节点的 id_field 值。
    """
    from_table = rel_def["from_table"]
    fk_field = rel_def["fk_field"]
    to_table = rel_def["to_table"]
    rel_type = rel_def["rel_type"]

    # 从 nodes_config 查找源和目标节点的 id_field
    src_id_field = "id"
    tgt_id_field = "id"
    for nd in nodes_config:
        if nd.get("table") == from_table:
            src_id_field = nd.get("id_field", "id")
        if nd.get("table") == to_table:
            tgt_id_field = nd.get("id_field", "id")

    # SQL: 只查源表，选出源 PK + FK 值（无需 JOIN）
    sql = f"SELECT DISTINCT {src_id_field} AS src_id, {fk_field} AS tgt_id FROM {from_table}"
    if from_filter:
        sql += f" WHERE {from_filter}"

    logger.info(f"[graph] 关系查询 {rel_type}: {sql}")
    try:
        rows = mysql_db.execute_query(sql)
    except Exception as e:
        return 0, [f"查询关系 {rel_type} 失败: {e}"]

    if not rows:
        logger.warning(f"[graph] {rel_type} 关系无数据")
        return 0, []

    from_label = _safe_identifier(table_label_map.get(from_table, from_table))
    to_label = _safe_identifier(table_label_map.get(to_table, to_table))

    cypher = """
        UNWIND $rows AS row
        MATCH (a:{} {{}})
        MATCH (b:{} {{}})
        MERGE (a)-[:{}]->(b)
    """.format(from_label, id, to_label, id, rel_type)

    batch_size = 500
    total = 0
    batch_rows = [{"src_id": str(r["src_id"]), "tgt_id": str(r["tgt_id"])} for r in rows]

    for i in range(0, len(batch_rows), batch_size):
        batch = batch_rows[i:i + batch_size]
        try:
            with graph_client.driver.session() as session:
                session.run(cypher, rows=batch)
                total += len(batch)
        except Exception as e:
            return total, [f"导入关系 {rel_type} batch {i} 失败: {e}"]

    logger.info(f"[graph] {rel_type}: 导入 {total} 条关系")
    return total, []


def _merge_manual_node(graph_client, node_def: dict):
    """MERGE 手工定义的节点"""
    label = _safe_identifier(node_def["label"])
    cypher = """
        MERGE (n:{} {{}})
        SET n.name = $name,
            n.full_name = $full_name,
            n.aliases = $aliases,
            n.last_update = timestamp(),
            n.source = 'manual'
    """.format(label, id)
    with graph_client.driver.session() as session:
        session.run(
            cypher,
            id=str(node_def["id"]),
            name=node_def["name"],
            full_name=node_def.get("full_name", node_def["name"]),
            aliases=node_def.get("aliases", []),
        )


def _merge_manual_relationship(graph_client, rel_def: dict):
    """MERGE 手工定义的关系"""
    from_label = _safe_identifier(rel_def["from_label"])
    to_label = _safe_identifier(rel_def["to_label"])
    rel_type = rel_def["rel_type"]

    cypher = """
        MATCH (a:{} {{}})
        MATCH (b:{} {{}})
        MERGE (a)-[:{}]->(b)
    """.format(from_label, id, to_label, id, rel_type)
    with graph_client.driver.session() as session:
        session.run(
            cypher,
            from_id=str(rel_def["from_id"]),
            to_id=str(rel_def["to_id"]),
        )


def _safe_identifier(name: str) -> str:
    """Neo4j 标识符安全化（需要时加 backtick 转义）"""
    if not name.isidentifier():
        return f"`{name}`"
    return name
