# cython: annotation_typing=False, infer_types=False, language_level=3
"""Neo4j 图数据库客户端 — 实体搜索与上下文查询

所有 type_key ↔ Neo4j Label ↔ 中文名 映射均从 graph_mapping.yaml 动态派生，不做硬编码。
"""
from neo4j import GraphDatabase
from typing import Optional, List, Dict, Any
from backend.core.agentic_qa.config import settings
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("core.graph_client")


class GraphClient:
    def __init__(self, uri: str, user: str, password: str, mapping: dict = None):
        self.driver = None
        self._type_key_to_label: Dict[str, str] = {}
        self._label_to_type_key: Dict[str, str] = {}
        self._type_key_to_label_zh: Dict[str, str] = {}

        if mapping:
            self._build_mappings(mapping)

        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            self.driver.verify_connectivity()
            logger.info(f"[graph] Neo4j 连接成功: {uri}")
        except Exception as e:
            logger.warning(f"[graph] Neo4j 连接失败 ({uri}): {e}，实体消歧将使用原有向量检索")
            self.driver = None

    def _build_mappings(self, mapping: dict):
        """从 YAML 配置构建所有查找表"""
        all_nodes = list(mapping.get("nodes", []))
        all_nodes.extend(mapping.get("manual_nodes", []))

        for nd in all_nodes:
            type_key = nd.get("type_key", "")
            label = nd.get("label", "")
            label_zh = nd.get("label_zh", "")
            if type_key and label:
                self._type_key_to_label[type_key] = label
                self._label_to_type_key[label] = type_key
            if type_key and label_zh:
                self._type_key_to_label_zh[type_key] = label_zh

        logger.info(
            f"[graph] 映射加载: {len(self._type_key_to_label)} type_key→Label, "
            f"{len(self._label_to_type_key)} Label→type_key, "
            f"{len(self._type_key_to_label_zh)} type_key→中文"
        )

    def is_available(self) -> bool:
        return self.driver is not None

    def search_entities(self, keyword: str, entity_type: str, limit: int = 10) -> List[Dict[str, Any]]:
        """全文索引搜索实体

        1. 按指定 entity_type 对应的 Neo4j Label 搜索
        2. Label 特定搜索无结果时 → 不过滤 Label 的跨类型搜索
        3. 仍无结果 → CONTAINS 降级
        """
        if not self.is_available():
            return []

        label = self._type_key_to_label.get(entity_type)
        if not label:
            # entity_type 无对应 Label，直接跨类型搜索
            return self._fulltext_search_all(keyword, limit)

        # Step 1: 按指定 Label 搜索
        results = self._fulltext_search(keyword, label, limit)
        if results:
            return results

        # Step 2: 指定 Label 无结果 → 跨所有 Label 搜索
        results = self._fulltext_search_all(keyword, limit)
        if results:
            return results

        # Step 3: CONTAINS 降级
        return self._contains_search(keyword, label, limit)

    def _fulltext_search(self, keyword: str, label: str, limit: int) -> List[Dict[str, Any]]:
        query = """
            CALL db.index.fulltext.queryNodes('entity_fulltext', $keyword)
            YIELD node, score
            WHERE $label IN labels(node)
            RETURN node.name AS label, toString(node.id) AS value,
                   labels(node) AS labels, score,
                   node.aliases AS aliases
            ORDER BY score DESC LIMIT $limit
        """
        return self._run_search_query(query, keyword, label, limit, "graph_fulltext")

    def _fulltext_search_all(self, keyword: str, limit: int) -> List[Dict[str, Any]]:
        """跨所有节点类型的全文搜索（LLM 分类可能有误时的降级）"""
        query = """
            CALL db.index.fulltext.queryNodes('entity_fulltext', $keyword)
            YIELD node, score
            RETURN node.name AS label, toString(node.id) AS value,
                   labels(node) AS labels, score,
                   node.aliases AS aliases
            ORDER BY score DESC LIMIT $limit
        """
        return self._run_search_query(query, keyword, None, limit, "graph_fulltext_all")

    def _contains_search(self, keyword: str, label: str, limit: int) -> List[Dict[str, Any]]:
        query = """
            MATCH (n)
            WHERE $label IN labels(n)
              AND (n.name CONTAINS $keyword
                   OR any(alias IN coalesce(n.aliases, []) WHERE alias CONTAINS $keyword))
            RETURN n.name AS label, toString(n.id) AS value,
                   labels(n) AS labels,
                   n.aliases AS aliases
            LIMIT $limit
        """
        return self._run_search_query(query, keyword, label, limit, "graph_contains")

    def _run_search_query(self, query: str, keyword: str, label: str,
                          limit: int, match_type: str) -> List[Dict[str, Any]]:
        try:
            with self.driver.session() as session:
                result = session.run(query, keyword=keyword, label=label, limit=limit)
                records = []
                for r in result:
                    neo4j_labels = r.get("labels", [])
                    record_entity_type = self._infer_type_key(neo4j_labels)
                    records.append({
                        "label": r.get("label", ""),
                        "value": r.get("value", ""),
                        "entity_type": record_entity_type,
                        "entity_label": self._type_key_to_label_zh.get(record_entity_type, label),
                        "match_type": match_type,
                        "score": r.get("score", 0.9) if match_type == "graph_fulltext" else 0.7,
                        "source": "graph",
                        "aliases": r.get("aliases", []),
                        "sublabel": "",
                    })
                logger.info(f"[graph] {match_type}: '{keyword}' ({label}) -> {len(records)} results")
                return records
        except Exception as e:
            logger.warning(f"[graph] search error ({match_type}): {e}")
            return []

    def get_entity_context(self, entity_id: str, entity_type: str,
                           max_depth: int = 3) -> Dict[str, Any]:
        """获取实体的关系链上下文"""
        if not self.is_available():
            return {}

        label = self._type_key_to_label.get(entity_type)
        if not label:
            return {}

        query = """
            MATCH (n {id: $id})
            WHERE $label IN labels(n)
            OPTIONAL MATCH path = (n)-[*1..%d]-(related)
            RETURN n, relationships(path) AS rels, nodes(path) AS related_nodes
            LIMIT 30
        """ % max_depth
        try:
            with self.driver.session() as session:
                result = session.run(query, id=entity_id, label=label)
                record = result.single()
                if not record:
                    return {}

                rels = record.get("rels", []) or []
                related = record.get("related_nodes", []) or []

                context_path = self._build_context_path(related)
                return {"entity": record.get("n", {}), "relationships": rels,
                        "related_nodes": related, "context_path": context_path}
        except Exception as e:
            logger.warning(f"[graph] context error: {e}")
            return {}

    def _build_context_path(self, related: list) -> str:
        """从关系链节点构建可读的上下文路径（使用中文名称）"""
        parts = []
        for node in related:
            try:
                node_labels = list(node.labels) if hasattr(node, 'labels') else []
                node_name = node.get("name", "") if hasattr(node, 'get') else ""
                if node_name and node_labels:
                    label = node_labels[0]
                    label_zh = self._label_to_type_key.get(label, label)
                    label_zh = self._type_key_to_label_zh.get(label_zh, label)
                    display = f"{label_zh}/{node_name}" if label_zh else f"{label}/{node_name}"
                    if display not in parts:
                        parts.append(display)
            except Exception:
                continue
        return " → ".join(parts) if parts else ""

    def _infer_type_key(self, neo4j_labels: List[str]) -> str:
        """从 Neo4j label 推断 entity type_key"""
        for nl in neo4j_labels:
            tk = self._label_to_type_key.get(nl)
            if tk:
                return tk
        return "unknown"

    def get_all_entities(self, entity_type: str) -> List[Dict[str, Any]]:
        """获取某类型的所有实体节点"""
        if not self.is_available():
            return []

        label = self._type_key_to_label.get(entity_type)
        if not label:
            return []

        query = """
            MATCH (n)
            WHERE $label IN labels(n)
            RETURN n.name AS label, toString(n.id) AS value,
                   labels(n) AS labels, n.aliases AS aliases
            ORDER BY n.name
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, label=label)
                return [
                    {
                        "label": r.get("label", ""),
                        "value": r.get("value", ""),
                        "entity_type": self._infer_type_key(r.get("labels", [])),
                        "entity_label": self._type_key_to_label_zh.get(
                            self._infer_type_key(r.get("labels", [])), label
                        ),
                        "source": "graph",
                        "sublabel": "",
                    }
                    for r in result
                ]
        except Exception as e:
            logger.warning(f"[graph] get_all_entities error: {e}")
            return []

    def close(self):
        if self.driver:
            self.driver.close()
            self.driver = None


_graph_client: Optional[GraphClient] = None


def get_graph_client() -> GraphClient:
    global _graph_client
    if _graph_client is None:
        # Load mapping from YAML to build dynamic lookup tables
        from backend.core.agentic_qa.graph_importer import load_mapping
        try:
            mapping = load_mapping(settings.graph_mapping_path)
        except Exception as e:
            logger.warning(f"[graph] 加载 YAML 映射失败: {e}，使用空映射")
            mapping = None

        _graph_client = GraphClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            mapping=mapping,
        )
    return _graph_client
