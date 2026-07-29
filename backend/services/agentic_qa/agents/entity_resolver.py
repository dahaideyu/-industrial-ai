# cython: annotation_typing=False, infer_types=False, language_level=3
"""实体检索与消歧模块

存储策略：全部使用 ChromaDB 向量库。
- entity_index: 核心实体索引（dev_device + sys_line）
- entity_aliases: 用户定义的别名 → 标准实体映射
- custom_metrics: 用户自定义指标定义

增强：Neo4j 图数据库实体检索（别名 → 图查询 → LLM 评估 → 向量 → 全量DB）
"""
import re
import json
import uuid
from typing import Optional, List, Dict, Any
import chromadb
from chromadb.config import Settings as ChromaSettings
from backend.services.agentic_qa.db.mysql import db
from backend.core.agentic_qa.llm import llm
from backend.core.agentic_qa.config import settings
from backend.core.agentic_qa.logger import get_logger
from backend.services.agentic_qa.models.entity_config import validate_identifier, validate_filter_condition

logger = get_logger("agents.entity_resolver")

# ============================================================
# ChromaDB 客户端
# ============================================================

_chroma_client: Optional[chromadb.PersistentClient] = None
_ENTITY_COLLECTION = "entity_index"
_ALIAS_COLLECTION = "entity_aliases"
_METRIC_COLLECTION = "custom_metrics"


def _get_chroma() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        path = getattr(settings, 'entity_chroma_path', None) or "./backend/data/agentic_qa/entity-knowledge"
        from backend.core.agentic_qa.embeddings import get_embedding_function
        _chroma_client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        logger.info(f"[entity] ChromaDB at {path}")
    return _chroma_client


def _get_collection(name: str) -> chromadb.Collection:
    from backend.core.agentic_qa.embeddings import get_embedding_function
    return _get_chroma().get_or_create_collection(
        name=name,
        embedding_function=get_embedding_function()
    )


# ============================================================
# 默认兜底配置（数据库不可用时使用）
_DEFAULT_REGISTRY: Dict[str, dict] = {
    "production_line": {
        "label": "产线", "table": "sys_line", "search_columns": ["name"],
        "label_column": "name", "value_column": "id", "context_columns": ["type"],
        "keyword_hints": ["产线", "线", "车间", "线体", "生产线"]
    },
    "device": {
        "label": "设备", "table": "dev_device", "search_columns": ["name", "short_no"],
        "label_column": "name", "value_column": "id",
        "context_columns": ["device_type", "factory", "status", "position"],
        "keyword_hints": ["设备", "机", "仪", "装置"],
    },
}


def get_registry() -> dict:
    """从数据库加载实体注册表，数据库不可用时回退到硬编码默认值"""
    try:
        from backend.services.agentic_qa.models.entity_config import EntityConfig
        from backend.core.agentic_qa.database import SessionLocal
        db = SessionLocal()
        try:
            configs = db.query(EntityConfig).all()
            if configs:
                return {c.entity_type: c.to_registry_entry() for c in configs}
        finally:
            db.close()
    except Exception:
        pass
    return dict(_DEFAULT_REGISTRY)


# ============================================================
# 实体索引
# ============================================================

_indexed_tables: set = set()


def index_entities(force: bool = False) -> int:
    """扫描注册表中所有实体表的 name 列，写入 ChromaDB entity_index"""
    global _indexed_tables
    collection = _get_collection(_ENTITY_COLLECTION)
    total = 0

    for key, cfg in get_registry().items():
        table = cfg["table"]
        if table in _indexed_tables and not force:
            continue

        label_col = cfg["label_column"]
        value_col = cfg["value_column"]
        context_cols = cfg.get("context_columns", [])
        filter_cond = cfg.get("filter_condition", "del_flag = 0")

        try:
            # 表名/列名/filter_condition 来自实体配置（管理接口可写），拼进 SQL 前
            # 兜底校验一遍，防止配置里混进分号/注释符等注入手法（写入时 admin.py
            # 已经校验过，这里是防止绕过写入路径直接改库的第二道保险）
            validate_identifier(table, "table")
            validate_identifier(label_col, "label_column")
            validate_identifier(value_col, "value_column")
            for c in context_cols:
                validate_identifier(c, "context_columns")
            validate_filter_condition(filter_cond)
        except ValueError as e:
            logger.warning(f"[entity] 实体配置校验失败，跳过索引 {table}: {e}")
            continue

        try:
            cols = ", ".join([f"`{label_col}`", f"`{value_col}`"] +
                             [f"`{c}`" for c in context_cols if c != label_col])
            rows = db.execute_query(f"SELECT {cols} FROM `{table}` WHERE {filter_cond} LIMIT 5000")
        except Exception as e:
            logger.debug(f"[entity] skip index {table}: {e}")
            continue

        if not rows:
            _indexed_tables.add(table)
            continue

        # 清除旧索引
        try:
            existing = collection.get(where={"entity_type": key})
            if existing and existing["ids"]:
                collection.delete(ids=existing["ids"])
        except Exception:
            pass

        ids, docs, metadatas = [], [], []
        for row in rows:
            label = str(row.get(label_col, "")).strip()
            value = str(row.get(value_col, ""))
            if not label:
                continue

            sublabel_parts = []
            for c in context_cols:
                v = row.get(c)
                if v is not None and str(v).strip():
                    sublabel_parts.append(str(v))

            doc_id = f"{key}:{value}"
            ids.append(doc_id)
            docs.append(label)
            metadatas.append({
                "entity_type": key,
                "entity_label": cfg.get("label", key),
                "table": table,
                "label": label,
                "value": value,
                "sublabel": " · ".join(sublabel_parts[:3]),
                "source": "database",
            })
            total += 1

        if ids:
            collection.add(ids=ids, documents=docs, metadatas=metadatas)

        _indexed_tables.add(table)
        logger.info(f"[entity] indexed {len(ids)} entities from {table}")

    return total


# ============================================================
# 向量检索
# ============================================================

def search_entity_vector(
    query: str,
    entity_type: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """在 entity_index 中做向量相似度检索"""
    collection = _get_collection(_ENTITY_COLLECTION)
    where = {"entity_type": entity_type} if entity_type else None

    try:
        results = collection.query(query_texts=[query], n_results=limit, where=where)
    except Exception:
        try:
            results = collection.query(query_texts=[query], n_results=limit)
        except Exception:
            return []

    if not results or not results.get("ids") or not results["ids"][0]:
        return []

    output = []
    ids_list = results["ids"][0]
    docs_list = results["documents"][0]
    metas_list = results["metadatas"][0]
    distances = results.get("distances", [[]])[0]

    for i, doc_id in enumerate(ids_list):
        meta = metas_list[i] if metas_list else {}
        dist = distances[i] if i < len(distances) else 0
        output.append({
            "id": doc_id,
            "label": docs_list[i] if docs_list else meta.get("label", ""),
            "sublabel": meta.get("sublabel", ""),
            "value": meta.get("value", ""),
            "entity_type": meta.get("entity_type", ""),
            "entity_label": meta.get("entity_label", ""),
            "match_type": "vector",
            "score": round(1.0 - dist, 4) if dist else 1.0,
            "source": meta.get("source", "database"),
        })
    return output


def search_entity_like(
    keyword: str,
    entity_type: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """SQL LIKE 兜底检索 — 处理向量无法区分的形近字（如 合膏 vs 和膏）"""
    registry = get_registry()
    cfg = registry.get(entity_type)
    if not cfg:
        return []

    table = cfg["table"]
    search_cols = cfg.get("search_columns", ["name"])
    label_col = cfg.get("label_column", "name")
    value_col = cfg.get("value_column", "id")
    context_cols = cfg.get("context_columns", [])

    # 表名/列名来自实体配置（管理接口可写），拼进 SQL 前兜底校验（同 index_entities）
    try:
        validate_identifier(table, "table")
        for c in search_cols:
            validate_identifier(c, "search_columns")
    except ValueError as e:
        logger.warning(f"[entity] 实体配置校验失败，跳过 LIKE 检索 {table}: {e}")
        return []

    results = []
    try:
        # Level 1: 完整关键词模糊匹配 (如 %合膏%)
        like_pattern = "%" + "%".join(keyword) + "%"
        where_clauses = " OR ".join(f"`{c}` LIKE %s" for c in search_cols)
        params = [like_pattern] * len(search_cols) + [limit]
        sql = f"SELECT * FROM `{table}` WHERE ({where_clauses}) AND del_flag = 0 LIMIT %s"
        rows = db.execute_query(sql, tuple(params))

        # Level 2: 无结果时，逐字 OR 匹配（处理形近字如 合/和）
        if not rows and len(keyword) >= 2:
            char_clauses = " OR ".join(f"`{c}` LIKE %s" for ch in keyword for c in search_cols)
            char_params = [f"%{ch}%" for ch in keyword for _ in search_cols] + [limit]
            sql2 = f"SELECT * FROM `{table}` WHERE ({char_clauses}) AND del_flag = 0 LIMIT %s"
            rows = db.execute_query(sql2, tuple(char_params))

        for r in rows:
            label = str(r.get(label_col, ""))
            value = str(r.get(value_col, ""))
            sublabel_parts = []
            for c in context_cols:
                v = r.get(c)
                if v is not None and str(v).strip():
                    sublabel_parts.append(str(v))
            results.append({
                "label": label,
                "sublabel": " · ".join(sublabel_parts[:3]),
                "value": value,
                "entity_type": entity_type,
                "entity_label": cfg.get("label", entity_type),
                "match_type": "like_fallback",
                "score": 0.5,
                "source": "database_like",
            })
    except Exception as e:
        logger.debug(f"[entity] like fallback failed for {entity_type}/{keyword}: {e}")

    return results


def search_aliases(query: str, entity_type: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """在 entity_aliases 集合中检索匹配的别名（带距离阈值过滤）"""
    collection = _get_collection(_ALIAS_COLLECTION)
    where = {"entity_type": entity_type} if entity_type else None

    try:
        results = collection.query(query_texts=[query], n_results=limit, where=where)
    except Exception:
        return []

    if not results or not results.get("ids") or not results["ids"][0]:
        return []

    # 距离阈值：cosine distance 放宽以适应短文本嵌入的不可靠性
    ALIAS_DISTANCE_THRESHOLD = 0.65
    distances = results.get("distances", [[]])[0] if results.get("distances") else []

    output = []
    for i, doc_id in enumerate(results["ids"][0]):
        distance = distances[i] if i < len(distances) else 1.0
        meta = (results["metadatas"][0] or [{}])[i] if results["metadatas"] else {}
        doc = (results["documents"][0] or [""])[i] if results["documents"] else [""]
        # 子串兼容：短文本嵌入不可靠，字符匹配兜底
        substring_match = (query in doc) or (doc in query) if len(query) >= 2 and len(doc) >= 2 else False
        if distance > ALIAS_DISTANCE_THRESHOLD and not substring_match:
            logger.info(
                f"[entity] alias skip: '{query}' candidate #{i} "
                f"distance={distance:.3f} > threshold={ALIAS_DISTANCE_THRESHOLD}"
            )
            continue
        output.append({
            "id": doc_id,
            "label": meta.get("canonical_name", doc),
            "sublabel": meta.get("context_sublabel", ""),
            "value": meta.get("canonical_value") or meta.get("canonical_name", ""),
            "entity_type": meta.get("entity_type", ""),
            "match_type": "alias",
            "alias": doc,
            "distance": distance,
        })
    return output


# ============================================================
# 指标检索
# ============================================================

DEFAULT_METRICS = [
    {"name": "设备数量", "keywords": ["数量", "几台", "多少个", "总数", "count"]},
    {"name": "故障次数", "keywords": ["故障", "故障次数", "坏了", "异常次数"]},
    {"name": "停机时长", "keywords": ["停机", "停机时长", "停了多久", "停机时间"]},
    {"name": "运行时长", "keywords": ["运行", "运行时长", "开了多久"]},
    {"name": "维修次数", "keywords": ["维修", "维修次数", "修了"]},
]


def search_metrics_vec(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """在 custom_metrics + 默认指标中检索"""
    results = []

    for m in DEFAULT_METRICS:
        for kw in m["keywords"]:
            if kw in query:
                results.append({
                    "label": m["name"], "sublabel": "预设指标",
                    "value": m["name"], "entity_type": "metric", "match_type": "keyword",
                })
                break

    collection = _get_collection(_METRIC_COLLECTION)
    try:
        vec_results = collection.query(query_texts=[query], n_results=limit)
    except Exception:
        vec_results = None

    if vec_results and vec_results.get("ids") and vec_results["ids"][0]:
        for i, doc_id in enumerate(vec_results["ids"][0]):
            meta = (vec_results["metadatas"][0] or [{}])[i]
            doc = (vec_results["documents"][0] or [""])[i]
            results.append({
                "id": doc_id, "label": meta.get("name", doc),
                "sublabel": meta.get("description", "自定义指标")[:60],
                "value": meta.get("name", doc), "entity_type": "metric", "match_type": "custom_vector",
            })

    seen = set()
    unique = []
    for r in results:
        if r["value"] not in seen:
            seen.add(r["value"])
            unique.append(r)
    return unique


# ============================================================
# 消歧主入口 — 两阶段 LLM 决策（已迁移到 master_loop）
# ============================================================

GRAPH_QUALITY_EVAL_PROMPT = """评估 Neo4j 图数据库搜索结果是否匹配用户提到的实体。

## 实体类型
{entity_label} ({entity_type})

## 用户提到的短语
"{keyword}"（原文: {mention}）

## 图数据库搜索结果（全文索引 + 关系上下文）
{results_summary}

## 任务
1. 判断这些图搜索结果是否与用户要查找的实体相关。
2. 判断依据：
   - 名称相似度：精确匹配、包含关系、简称、同音/谐音、错别字
   - 关系上下文：如果结果中包含层级路径（如"设备 → 产线 → 车间"），是否有助于确认？
   - 误匹配：明显属于不同上下文的无关结果
3. 如果用户的短语疑似错别字/简称，在 correction 中填写纠正后的形式。

## 输出格式
{{"relevant": true/false, "confidence": 0.0-1.0, "reasoning": "简要中文说明",
 "correction": "纠正形式（无则为空字符串）", "best_match_index": 0}}
只输出 JSON"""



def _load_all_entities(entity_type: str) -> list:
    """从数据库加载该实体类型的所有记录（供 LLM 全量判断）"""
    registry = get_registry()
    cfg = registry.get(entity_type)
    if not cfg:
        return []

    table = cfg["table"]
    label_col = cfg["label_column"]
    value_col = cfg["value_column"]
    context_cols = cfg.get("context_columns", [])

    try:
        cols = ", ".join([f"`{c}`" for c in [label_col, value_col] + context_cols if c != label_col])
        rows = db.execute_query(f"SELECT {cols} FROM `{table}` WHERE del_flag = 0 LIMIT 500")
    except Exception:
        return []

    results = []
    for row in rows:
        label = str(row.get(label_col, "")).strip()
        value = str(row.get(value_col, ""))
        if not label:
            continue
        sublabel_parts = []
        for c in context_cols:
            v = row.get(c)
            if v is not None and str(v).strip():
                sublabel_parts.append(str(v))
        results.append({
            "label": label, "value": value,
            "sublabel": " · ".join(sublabel_parts[:3]),
            "entity_type": entity_type, "source": "full_db",
            "score": 0.0, "match_type": "db_all",
        })
    return results


def _search_graph(keyword: str, entity_type: str) -> list:
    """在 Neo4j 图数据库中搜索实体，并富化关系上下文

    失败或不可用时返回 []，调用方自动降级到向量检索。
    """
    try:
        from backend.core.agentic_qa.graph_client import get_graph_client
        client = get_graph_client()
        if not client.is_available():
            return []

        results = client.search_entities(keyword, entity_type, limit=10)

        # 为前几条结果富化关系链上下文
        for r in results[:3]:
            try:
                ctx = client.get_entity_context(r["value"], entity_type, max_depth=2)
                if ctx.get("context_path"):
                    r["context_path"] = ctx["context_path"]
                    r["sublabel"] = ctx["context_path"]
            except Exception:
                pass

        return results
    except Exception as e:
        logger.warning(f"[entity] graph search failed for '{keyword}': {e}")
        return []


def _evaluate_graph_results_with_llm(
    keyword: str, mention: str, entity_type: str, results: list, registry: dict
) -> dict:
    """LLM 评估图搜索结果是否与用户实体相关

    返回: {"relevant": bool, "confidence": float, "reasoning": str,
           "correction": str, "best_match_index": int}
    """
    entity_label = registry.get(entity_type, {}).get("label", entity_type)

    # 规则捷径：全文索引分数 ≥ 0.8 直接信任，跳过 LLM 调用（提升稳定性）
    graph_with_score = [r for r in results if r.get("match_type") in ("graph_fulltext", "graph_fulltext_all")]
    if graph_with_score and graph_with_score[0].get("score", 0) >= 0.8:
        logger.info(
            f"[entity] graph auto-trusted: {len(results)} results for '{keyword}' "
            f"(top fulltext score={graph_with_score[0]['score']:.3f})"
        )
        return {"relevant": True, "confidence": 0.9, "reasoning": "全文索引高分匹配",
                "correction": "", "best_match_index": 0}

    summary_lines = []
    for i, r in enumerate(results[:10]):
        ctx = r.get("context_path", "") or r.get("sublabel", "")
        ctx_str = f" | 上下文: {ctx}" if ctx else ""
        summary_lines.append(
            f"[{i}] {r.get('label', '')} (匹配方式={r.get('match_type', '?')}, "
            f"分数={r.get('score', 0):.3f}){ctx_str}"
        )

    prompt = GRAPH_QUALITY_EVAL_PROMPT.format(
        entity_label=entity_label,
        entity_type=entity_type,
        keyword=keyword,
        mention=mention,
        results_summary="\n".join(summary_lines),
    )

    try:
        response = llm.chat_once(
            user_prompt="请评估这些图搜索结果是否匹配用户提到的实体。",
            system_prompt=prompt,
            temperature=0,
            max_tokens=2048,
        )
        response = response.strip()
        if response.startswith("```"):
            response = re.sub(r"^```\w*\n?", "", response)
            response = re.sub(r"\n?```$", "", response)
        result = json.loads(response)
        result.setdefault("relevant", False)
        result.setdefault("confidence", 0.0)
        result.setdefault("reasoning", "")
        result.setdefault("correction", "")
        result.setdefault("best_match_index", 0)
        logger.info(
            f"[entity] graph eval: relevant={result['relevant']} "
            f"confidence={result['confidence']:.2f} for '{keyword}' — {result['reasoning']}"
        )
        return result
    except Exception as e:
        logger.warning(f"[entity] graph quality eval failed: {e}")
        return {
            "relevant": True, "confidence": 0.5,
            "reasoning": "LLM 评估失败，默认信任图结果",
            "correction": "", "best_match_index": 0,
        }


def _merge_graph_and_vector(
    graph_results: list, vector_results: list, entity_type: str
) -> list:
    """合并图搜索结果（优先）和向量结果，按 (entity_type, value) 去重"""
    seen = set()
    merged = []

    for r in graph_results:
        key = (r.get("entity_type", entity_type), r.get("value", ""))
        if key not in seen:
            seen.add(key)
            r["match_type"] = r.get("match_type", "graph_fulltext")
            r.setdefault("score", max(r.get("score", 0.8), 0.8))
            merged.append(r)

    for r in vector_results:
        key = (r.get("entity_type", entity_type), r.get("value", ""))
        if key not in seen:
            seen.add(key)
            merged.append(r)

    logger.info(
        f"[entity] merged: {len(graph_results)} graph + {len(vector_results)} vector "
        f"= {len(merged)} unique"
    )
    return merged[:50]


def _search_with_fallback(keyword: str, entity_type: str, original_text: str = "") -> list:
    """检索：别名优先 → 图查询(Neo4j) → LLM评估 → 向量 → 全量DB"""
    # Step 1: 别名命中 → 用 canonical 名二次检索
    alias_results = search_aliases(keyword, entity_type, limit=5)
    if alias_results:
        canonical = alias_results[0].get("label", "")
        logger.info(f"[entity] alias '{keyword}' -> '{canonical}'")
        results = search_entity_vector(canonical, entity_type, limit=15)
        if not results or len(results) < 10:
            all_entities = _load_all_entities(entity_type)
            seen = {r.get("value") for r in results}
            for e in all_entities:
                if e.get("value") not in seen:
                    results.append(e)
        return results[:50]

    # Step 2: 图数据库查询(Neo4j) + LLM 评估质量
    graph_results = _search_graph(keyword, entity_type)
    if graph_results:
        quality = _evaluate_graph_results_with_llm(
            keyword, original_text or keyword, entity_type, graph_results, get_registry()
        )
        if quality.get("relevant", False):
            logger.info(
                f"[entity] graph accepted: {len(graph_results)} results for '{keyword}' "
                f"(confidence={quality.get('confidence', 0):.2f})"
            )
            # 图搜索结果可信 → 直接使用，不混合向量噪声
            # 仅当结果太少时补充全量 DB 同类型实体
            if len(graph_results) < 5:
                all_entities = _load_all_entities(entity_type)
                seen = {(r.get("entity_type"), r.get("value")) for r in graph_results}
                for e in all_entities:
                    if (e.get("entity_type"), e.get("value")) not in seen:
                        graph_results.append(e)
            return graph_results[:50]
        else:
            logger.info(
                f"[entity] graph rejected for '{keyword}': {quality.get('reasoning', '')}"
            )

    # Step 3: 向量检索
    results = search_entity_vector(keyword, entity_type, limit=15)
    seen = {r.get("value") for r in results}

    # Step 4: LIKE 字符级兜底（始终执行，不受向量分数门控）
    like_results = search_entity_like(keyword, entity_type, limit=10)
    like_hits = 0
    for lr in like_results:
        if lr.get("value") not in seen:
            seen.add(lr.get("value"))
            lr["match_type"] = "sql_like"
            lr["score"] = lr.get("score", 0.5)
            results.insert(0, lr)
            like_hits += 1
    if like_hits > 0:
        logger.info(f"[entity] LIKE fallback: {like_hits} additional candidates for '{keyword}'")

    # Step 5: 向量结果数量不足 → 补充全量 DB 实体
    if len(results) < 5:
        all_entities = _load_all_entities(entity_type)
        for e in all_entities:
            if e.get("value") not in seen:
                results.append(e)

    logger.info(f"[entity] search: {len(results)} candidates for '{keyword}' (incl. LIKE + DB)")
    return results[:50]


def _rule_based_needs_resolution(question: str) -> bool:
    """规则兜底：判断是否需要消歧"""
    # 聚合/遍历词 → 不需要
    if re.search(r"所有|全部|各|每|汇总|统计", question):
        # 但仍然检查是否有具体实体（如"所有和膏产线"不需要，"正冲网有几台"需要）
        if re.search(r"所有\S{0,3}(产线|设备|机)", question):
            return False
    return True


def _build_entity_candidates(
    entity_candidates: list,
    matches: list,
    entity_type: str,
    original_text: str,
    search_keyword: str,
    registry: dict
):
    """构建候选列表（多选已支持，不再添加 __all__ 选项）

    每个候选的 sql_hint 基于其自身的 entity_type 生成，
    而非 LLM 分类的 entity_type（LLM 分类可能不准确）。
    """
    entity_label = registry.get(entity_type, {}).get("label", entity_type)
    candidates = list(matches[:8])
    for c in candidates:
        c["mention"] = original_text
        c.setdefault("sql_hint", _entity_sql_hint(
            c.get("entity_type", entity_type), c.get("label", "")
        ))

    entity_candidates.append({
        "entity_type": entity_type,
        "entity_label": entity_label,
        "mention": original_text,
        "candidates": candidates,
        "match_count": len(matches),
        "resolved": False,
        "source": "vector_multi_select",
    })


# type_key → label_zh 映射缓存（从 graph_mapping.yaml 动态加载）
_type_label_zh_map: dict = None


def _get_type_label_zh_map() -> dict:
    """从 graph_mapping.yaml 加载 type_key → 中文名称 映射"""
    global _type_label_zh_map
    if _type_label_zh_map is None:
        _type_label_zh_map = {}
        try:
            from backend.core.agentic_qa.graph_importer import load_mapping
            from backend.core.agentic_qa.config import settings
            mapping = load_mapping(settings.graph_mapping_path)
            for nd in mapping.get("nodes", []):
                tk = nd.get("type_key", "")
                zh = nd.get("label_zh", "")
                if tk and zh:
                    _type_label_zh_map[tk] = zh
            for mn in mapping.get("manual_nodes", []):
                tk = mn.get("type_key", "")
                zh = mn.get("label_zh", "")
                if tk and zh:
                    _type_label_zh_map[tk] = zh
        except Exception:
            pass
    return _type_label_zh_map


def _entity_sql_hint(entity_type: str, label: str, is_all: bool = False) -> str:
    """根据实体类型生成正确的 SQL 提示文本

    类型的中文名从 graph_mapping.yaml 的 label_zh 动态获取，不做硬编码。
    """
    zh = _get_type_label_zh_map().get(entity_type)
    if zh:
        if is_all:
            return f"所有{zh}为 '{label}'"
        return f"{zh}名称为 '{label}'"
    return f"名称为 '{label}'"


def _add_auto_completion(completions: list, result: dict):
    entity_type = result.get("entity_type", "")
    label = result.get("label", "")
    completions.append({
        "field": entity_type,
        "field_label": result.get("entity_label", label),
        "value": result.get("value", ""),
        "label": label,
        "mention": result.get("mention", ""),
        "sublabel": result.get("sublabel", ""),
        "match_type": result.get("match_type", "vector"),
        "sql_hint": _entity_sql_hint(entity_type, label),
        "default": True,
        "editable": False,
    })


def _extract_entity_mentions_by_rules(question: str, registry: dict) -> List[dict]:
    """规则兜底：仅对有 keyword_hints 的实体类型做正则匹配"""
    mentions = []
    for key, cfg in registry.items():
        hints = cfg.get("keyword_hints", [])
        for hint in hints:
            # 找 "XX{hint}" 模式但排除纯数量问句如 "几台设备"
            pattern = rf"([一-龥\dA-Za-z#-]{{1,10}}?){re.escape(hint)}"
            matches = re.findall(pattern, question)
            for m in matches:
                keyword = m.strip()
                if len(keyword) < 1 or len(keyword) > 10:
                    continue
                skip_words = {"的", "了", "是", "在", "有", "和", "与", "或",
                              "几台", "多少", "哪些", "什么", "怎么", "如何", "查询", "统计", "列表"}
                instruction_prefixes = ("不应该", "不要", "不该", "不用", "注意", "修正",
                                       "应该", "应当", "使用", "通过", "按照", "根据")
                if keyword in skip_words:
                    continue
                if any(keyword.startswith(p) for p in instruction_prefixes):
                    continue
                mentions.append({"type": key, "keyword": keyword, "original": f"{keyword}{hint}"})

    # 去重：同一关键词可能匹配多种类型，只保留第一个
    seen_kw = set()
    result = []
    for m in mentions:
        if m["keyword"] not in seen_kw:
            seen_kw.add(m["keyword"])
            result.append(m)
    return result[:5]


def quick_typo_check(question: str) -> List[Dict[str, Any]]:
    """零结果兜底：用规则提取实体并做快速向量检索，检测可能的错别字。
    不调用 LLM，仅用向量搜索 + LIKE 兜底，延迟可控。
    返回建议列表，每个包含 {mention, keyword, suggestion, candidates}。
    """
    registry = get_registry()
    mentions = _extract_entity_mentions_by_rules(question, registry)
    if not mentions:
        return []

    suggestions = []
    for m in mentions:
        keyword = m["keyword"]
        entity_type = m["type"]
        # 用完整检索（别名→向量→LIKE兜底），但不触发 LLM 决策
        results = _search_with_fallback(keyword, entity_type)
        if not results:
            continue

        # 检查是否有精确匹配（关键词出现在候选 label 中）
        exact_match = any(keyword in str(r.get("label", "")) for r in results[:5])
        if exact_match:
            continue  # 关键词能在候选里找到，不是错别字

        # 关键词不在任何候选 label 中 → 疑似错别字
        top_candidates = []
        for r in results[:3]:
            top_candidates.append({
                "label": r.get("label", ""),
                "value": r.get("value", ""),
                "sublabel": r.get("sublabel", ""),
                "entity_type": r.get("entity_type", entity_type),
            })

        suggestion_label = top_candidates[0]["label"] if top_candidates else keyword
        suggestions.append({
            "mention": m.get("original", keyword),
            "keyword": keyword,
            "entity_type": entity_type,
            "entity_label": registry.get(entity_type, {}).get("label", entity_type),
            "suggestion": suggestion_label,
            "candidates": top_candidates,
        })

        logger.info(f"[entity] quick_typo_check: '{keyword}' may be typo, "
                    f"top suggestion='{suggestion_label}'")

    return suggestions


# ============================================================
# 别名 CRUD（ChromaDB entity_aliases）
# ============================================================

def load_alias_map(entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
    collection = _get_collection(_ALIAS_COLLECTION)
    where = {"entity_type": entity_type} if entity_type else None
    try:
        result = collection.get(where=where)
    except Exception:
        return []
    if not result or not result.get("ids"):
        return []
    items = []
    for i, doc_id in enumerate(result["ids"]):
        meta = (result["metadatas"] or [{}])[i] if result["metadatas"] else {}
        doc = (result["documents"] or [""])[i] if result["documents"] else ""
        items.append({
            "id": doc_id, "entity_type": meta.get("entity_type", ""),
            "alias": doc, "canonical_name": meta.get("canonical_name", ""),
            "canonical_value": meta.get("canonical_value", ""),
            "context": json.loads(meta.get("context_json", "{}") or "{}"),
            "created_at": meta.get("created_at", ""),
        })
    return items


def add_entity_alias(entity_type: str, alias: str, canonical_name: str,
                     canonical_value: str = None, context: dict = None,
                     created_by: str = "admin") -> bool:
    collection = _get_collection(_ALIAS_COLLECTION)
    doc_id = f"alias:{entity_type}:{uuid.uuid4().hex[:8]}"
    try:
        existing = collection.get(where={"entity_type": entity_type})
        if existing and existing["ids"]:
            for i, eid in enumerate(existing["ids"]):
                if (existing["documents"] or [""])[i] == alias:
                    collection.delete(ids=[eid])
    except Exception:
        pass
    context_json = json.dumps(context or {}, ensure_ascii=False)
    collection.add(ids=[doc_id], documents=[alias], metadatas=[{
        "entity_type": entity_type, "canonical_name": canonical_name,
        "canonical_value": canonical_value or canonical_name,
        "context_json": context_json,
        "context_sublabel": _format_context_sublabel(context or {}),
        "created_by": created_by, "created_at": "",
    }])
    logger.info(f"[entity] alias added: '{alias}' -> '{canonical_name}'")
    return True


def update_entity_alias(alias_id: str, **kwargs) -> bool:
    collection = _get_collection(_ALIAS_COLLECTION)
    try:
        existing = collection.get(ids=[alias_id])
        if not existing or not existing["ids"]:
            return False
    except Exception:
        return False
    meta = (existing["metadatas"] or [{}])[0] if existing["metadatas"] else {}
    doc = (existing["documents"] or [""])[0] if existing["documents"] else ""
    if "alias" in kwargs:
        doc = kwargs.pop("alias")
    if "context" in kwargs and isinstance(kwargs["context"], dict):
        meta["context_json"] = json.dumps(kwargs["context"], ensure_ascii=False)
        meta["context_sublabel"] = _format_context_sublabel(kwargs["context"])
        kwargs.pop("context", None)
    for k, v in kwargs.items():
        if k in ("entity_type", "canonical_name", "canonical_value", "created_by"):
            meta[k] = v
    collection.update(ids=[alias_id], documents=[doc], metadatas=[meta])
    return True


def delete_entity_alias(alias_id: str) -> bool:
    try:
        _get_collection(_ALIAS_COLLECTION).delete(ids=[alias_id])
        return True
    except Exception as e:
        logger.error(f"[entity] delete alias failed: {e}")
        return False


def _format_context_sublabel(ctx: dict) -> str:
    if not ctx:
        return ""
    parts = [f"{k}: {v}" for k, v in ctx.items() if k != "sublabel"]
    return ctx.get("sublabel", ", ".join(parts[:3]))


# ============================================================
# 自定义指标 CRUD（ChromaDB custom_metrics）
# ============================================================

def load_custom_metrics() -> List[Dict[str, Any]]:
    collection = _get_collection(_METRIC_COLLECTION)
    try:
        result = collection.get()
    except Exception:
        return []
    if not result or not result.get("ids"):
        return []
    items = []
    for i, doc_id in enumerate(result["ids"]):
        meta = (result["metadatas"] or [{}])[i] if result["metadatas"] else {}
        items.append({
            "id": doc_id, "name": meta.get("name", ""),
            "description": meta.get("description", ""),
            "sql_expression": meta.get("sql_expression", ""),
            "entity_type": meta.get("entity_type", ""),
            "keywords": meta.get("keywords", ""), "created_at": meta.get("created_at", ""),
        })
    return items


def add_custom_metric(name: str, description: str = None, sql_expression: str = None,
                      entity_type: str = None, keywords: str = None,
                      created_by: str = "admin") -> bool:
    collection = _get_collection(_METRIC_COLLECTION)
    doc_id = f"metric:{uuid.uuid4().hex[:8]}"
    try:
        existing = collection.get()
        if existing and existing["ids"]:
            for i, eid in enumerate(existing["ids"]):
                if (existing["metadatas"] or [{}])[i].get("name") == name:
                    collection.delete(ids=[eid])
    except Exception:
        pass
    doc_text = f"{name} {' '.join((keywords or '').split(','))} {description or ''}"
    collection.add(ids=[doc_id], documents=[doc_text], metadatas=[{
        "name": name, "description": description or "",
        "sql_expression": sql_expression or "", "entity_type": entity_type or "",
        "keywords": keywords or "", "created_by": created_by, "created_at": "",
    }])
    logger.info(f"[entity] metric added: '{name}'")
    return True


def update_custom_metric(metric_id: str, **kwargs) -> bool:
    collection = _get_collection(_METRIC_COLLECTION)
    try:
        existing = collection.get(ids=[metric_id])
        if not existing or not existing["ids"]:
            return False
    except Exception:
        return False
    meta = (existing["metadatas"] or [{}])[0] if existing["metadatas"] else {}
    for k, v in kwargs.items():
        if k in ("name", "description", "sql_expression", "entity_type", "keywords"):
            meta[k] = v
    doc_text = f"{meta.get('name', '')} {' '.join((meta.get('keywords', '') or '').split(','))} {meta.get('description', '')}"
    collection.update(ids=[metric_id], documents=[doc_text], metadatas=[meta])
    return True


def delete_custom_metric(metric_id: str) -> bool:
    try:
        _get_collection(_METRIC_COLLECTION).delete(ids=[metric_id])
        return True
    except Exception as e:
        logger.error(f"[entity] delete metric failed: {e}")
        return False


# ============================================================
# 轻量实体提取（纯函数，不依赖消歧决策）
# ============================================================

EXTRACT_MENTIONS_PROMPT = """从用户问题中提取可能引用的实体关键词。

## 实体类型（供参考）
{entity_hints}

## 任务
1. 找出用户问题中可能指代具体实体（产线、设备等）的词语
2. 只提取关键词，不做决策（不判断是否需要消歧）
3. 区分：具体指代（如"和膏机1号"）vs 聚合/泛指（如"所有设备"、"几台"）
4. 注意错别字/同音字/简称，不要因为不认识就跳过

## 输出格式
[
  {{"type": "实体类型key", "keyword": "搜索词", "original": "原文中的短语"}}
]

## 规则
- 只提取疑似专有名词，忽略数量词、疑问词
- 每个实体只提取最核心的关键词
- 如果没有实体关键词，返回空数组 []
- 只输出 JSON 数组，不要其他文本"""


def _extract_entity_mentions(question: str) -> list:
    """轻量 LLM 调用，只提取实体关键词，不做决策。

    Args:
        question: 用户问题

    Returns:
        [{"type": "device", "keyword": "和膏机1号", "original": "和膏机1号"}, ...]
    """
    registry = get_registry()

    # 构建 entity_hints
    hints = []
    for key, cfg in registry.items():
        hints.append(f"- {key} ({cfg.get('label', key)}): 触发词={cfg.get('keyword_hints', [])}")

    prompt = EXTRACT_MENTIONS_PROMPT.format(entity_hints="\n".join(hints))

    try:
        response = llm.chat_once(
            user_prompt=question,
            system_prompt=prompt,
            temperature=0,
            max_tokens=1024,
        )
        response = response.strip()
        if response.startswith("```"):
            response = re.sub(r"^```\w*\n?", "", response)
            response = re.sub(r"\n?```$", "", response)
        result = json.loads(response)
        if not isinstance(result, list):
            result = []
        logger.info(f"[entity] _extract_entity_mentions: {len(result)} mentions from '{question[:50]}'")
        return result
    except Exception as e:
        logger.warning(f"[entity] _extract_entity_mentions LLM failed: {e}, fallback to rules")
        return _extract_entity_mentions_by_rules(question, registry)
