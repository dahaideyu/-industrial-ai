# cython: annotation_typing=False, infer_types=False, language_level=3
# backend/services/agentic_qa/preprocess.py
"""assemble_context: 轻量预处理 — 槽位提取 + 关键词搜索 + Schema匹配，并行执行"""
import asyncio
import concurrent.futures
import json
import time
from typing import Any, Callable, Dict, List, Optional

from backend.core.agentic_qa.logger import get_logger
from backend.services.agentic_qa.blueprint import (
    build_query_blueprint,
    extract_entity_labels,
    labels_from_confirmed,
)

logger = get_logger("agentic_qa.preprocess")


async def _push_step(callback: Optional[Callable], step: dict):
    if callback:
        try:
            await callback(step)
        except Exception:
            pass

_SLOT_PROMPT = """从用户问题中提取结构化槽位信息。只返回 JSON，不要任何解释。

## 槽位定义

- entities: 实体对象列表，每个对象含 name 和 type_hint。
  - name: 从问题中提取的实体原始名称，保留用户原话（如 "和膏", "1号制带线", "3号产线"）
  - type_hint: 根据语义判断实体最可能属于哪种类型。可选值：
    "device" — 设备
    "production_line" — 产线
    "workshop" — 车间
    "department" — 部门
    null — 无法判断或不确定
  - 判断依据（按优先级）：
    1. 实体名本身的语义（如"制带机"是设备，"1号产线"是产线）
    2. 问题中的修饰词（如"产线和膏"中的"产线"修饰"和膏"）
    3. 注意：不要靠单个字匹配（如"制带线"含"线"但不一定是产线，"和膏一线"含"一线"但可能是产线编号）
    4. 不确定就填 null，让数据库搜索确定类型
- metrics: 指标列表（故障/温度/产量/时长/次数/告警等），如 ["故障次数", "运行时长"]，无则为 []
- time_range: 时间范围（"最近N天/小时/周"、"昨天"、"今天"、"本月"），无则为 null
- aggregation: 聚合方式（"平均"/"最大"/"最小"/"总计"/"TOP N"），无则为 null
- conditions: 筛选条件列表（如 "温度>80"、"状态=故障"），无则为 []

## 示例

问题: 和膏一线最近30天故障次数
输出: {"entities":[{"name":"和膏一线","type_hint":"production_line"}],"metrics":["故障次数"],"time_range":"最近30天","aggregation":null,"conditions":[]}

问题: 1号制带线最近有什么故障
输出: {"entities":[{"name":"1号制带线","type_hint":"device"}],"metrics":["故障"],"time_range":"最近","aggregation":null,"conditions":[]}

问题: 产线和膏最近一次出现的故障是什么怎么修复的
输出: {"entities":[{"name":"和膏","type_hint":"production_line"}],"metrics":["故障"],"time_range":"最近一次","aggregation":null,"conditions":[]}

问题: 车间一的温湿度传感器昨天数据
输出: {"entities":[{"name":"车间一","type_hint":"workshop"},{"name":"温湿度传感器","type_hint":"device"}],"metrics":["温湿度"],"time_range":"昨天","aggregation":null,"conditions":[]}

问题: 和膏是什么
输出: {"entities":[{"name":"和膏","type_hint":null}],"metrics":[],"time_range":null,"aggregation":null,"conditions":[]}"""


async def assemble_context(
    question: str,
    session_memory: dict = None,
    skip_extraction: bool = False,
    step_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """轻量预处理：槽位提取 + 关键词搜索 + Schema匹配，并行执行。

    Args:
        question: 用户问题
        session_memory: 会话记忆
        skip_extraction: 跳过实体关键词提取（/query/confirm 场景）
        step_callback: 可选的步骤推送回调，用于向前端输出预处理过程
    """
    sm = session_memory or {}
    confirmed = sm.get("confirmed_entities", [])

    if skip_extraction or confirmed:
        # /query/confirm 场景：实体已确认，只做 schema + 历史 + 槽位
        mentions = []
        entity_candidates = {}
        slots = {"entities": [], "metrics": [], "time_range": None, "aggregation": None, "conditions": []}
    else:
        # 正常场景：并行执行 槽位提取(含实体+类型) + schema搜索 + 历史搜索 + 主题检索
        t0 = time.time()
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            slot_future = loop.run_in_executor(pool, lambda: _extract_slots(question))
            schema_future = loop.run_in_executor(pool, lambda: _match_schemas(question))
            history_future = loop.run_in_executor(pool, lambda: _search_similar_queries(question))
            themes_future = loop.run_in_executor(pool, lambda: _search_themes())

            slots = await slot_future
            schemas = await schema_future
            similar = await history_future
            trained_themes = await themes_future

        # 推送槽位提取结果
        slot_ents = slots.get("entities", [])
        slot_metrics = slots.get("metrics", [])
        slot_time = slots.get("time_range")
        slot_parts = []
        if slot_ents:
            ent_strs = [f"{e.get('name','')}({e.get('type_hint','')})" if isinstance(e, dict) else str(e) for e in slot_ents]
            slot_parts.append(f"实体: {', '.join(ent_strs)}")
        if slot_metrics:
            slot_parts.append(f"指标: {', '.join(slot_metrics)}")
        if slot_time:
            slot_parts.append(f"时间: {slot_time}")
        agg = slots.get("aggregation")
        if agg:
            slot_parts.append(f"聚合: {agg}")
        elapsed_ms = round((time.time() - t0) * 1000)
        await _push_step(step_callback, {
            "tool": "preprocess",
            "title": "信息提取",
            "status": "done",
            "detail": " | ".join(slot_parts) if slot_parts else "未提取到有效信息",
            "elapsed_ms": elapsed_ms,
        })

        # 从 slots 提取实体（一次 LLM 调用替代原来的 _extract_entity_mentions）
        mentions = _slots_to_mentions(slots)
        entity_candidates = {}
        t1 = time.time()
        for m in mentions:
            keyword = m.get("keyword", "")
            etype = m.get("type", "")
            if keyword:
                try:
                    results = _search_with_fallback(keyword, etype)
                    # 主类型高分时跳过跨类型搜索，避免不必要的 LLM 调用
                    top_score = max((r.get("score", 0) for r in results), default=0) if results else 0
                    if results and (len(results) < 3 and top_score < 0.6):
                        extra = _search_cross_type(keyword, exclude_type=etype, limit=5)
                        seen = {r.get("value") for r in results}
                        for r in extra:
                            if r.get("value") not in seen:
                                results.append(r)
                                seen.add(r.get("value"))
                    entity_candidates[keyword] = results
                except Exception:
                    entity_candidates[keyword] = []

        # 推送实体检索结果
        ent_parts = []
        for kw, results in entity_candidates.items():
            count = len(results)
            if count > 0:
                top = results[0]
                top_name = top.get("value", "")
                top_score = top.get("score", 0)
                ent_parts.append(f"'{kw}' → {count}个候选 (最佳: {top_name}, 相似度={top_score:.2f})")
            else:
                ent_parts.append(f"'{kw}' → 未找到匹配")
        elapsed_ms1 = round((time.time() - t1) * 1000)
        if ent_parts:
            await _push_step(step_callback, {
                "tool": "entity_resolve",
                "title": "实体检索",
                "status": "done",
                "detail": " | ".join(ent_parts),
                "elapsed_ms": elapsed_ms1,
            })

    # confirmed 场景需要额外获取 schema 和历史
    if skip_extraction or confirmed:
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            schema_future = loop.run_in_executor(pool, lambda: _match_schemas(question))
            history_future = loop.run_in_executor(pool, lambda: _search_similar_queries(question))
            themes_future = loop.run_in_executor(pool, lambda: _search_themes())
            schemas = await schema_future
            similar = await history_future
            trained_themes = await themes_future

    # 生成查询蓝图
    blueprint = None
    if confirmed:
        entity_labels = labels_from_confirmed(confirmed)
    elif mentions:
        entity_labels = extract_entity_labels(mentions, entity_candidates)
    else:
        entity_labels = []

    if entity_labels:
        blueprint = build_query_blueprint(
            entity_labels=entity_labels,
            entity_candidates=entity_candidates,
            confirmed_entities=confirmed,
        )

    return {
        "slots": slots,
        "entity_mentions": mentions,
        "entity_candidates": entity_candidates,
        "confirmed_entities": confirmed,
        "relevant_schemas": schemas,
        "similar_queries": similar,
        "trained_themes": trained_themes,
        "query_blueprint": blueprint,
    }


def _slots_to_mentions(slots: dict) -> list:
    """将槽位中的实体转换为 entity mention 格式，供 _search_with_fallback 使用。"""
    mentions = []
    for e in slots.get("entities", []):
        if isinstance(e, dict):
            mentions.append({
                "type": e.get("type_hint") or "",
                "keyword": e.get("name", ""),
                "original": e.get("name", ""),
            })
        elif isinstance(e, str):
            mentions.append({"type": "", "keyword": e, "original": e})
    return mentions


def _extract_slots(question: str) -> dict:
    """LLM 提取槽位：实体、指标、时间、聚合、条件。"""
    try:
        from backend.core.agentic_qa.llm import llm
        response = llm.chat_once(
            user_prompt=question,
            system_prompt=_SLOT_PROMPT,
            temperature=0,
            max_tokens=2048,
        )
        response = response.strip()
        if response.startswith("```"):
            import re
            response = re.sub(r"^```\w*\n?", "", response)
            response = re.sub(r"\n?```$", "", response)
        result = json.loads(response)
        if not isinstance(result, dict):
            return {"entities": [], "metrics": [], "time_range": None, "aggregation": None, "conditions": []}
        logger.info(f"[preprocess] slots: entities={result.get('entities',[])} metrics={result.get('metrics',[])} "
                     f"time={result.get('time_range')} agg={result.get('aggregation')} conds={result.get('conditions',[])}")
        return result
    except Exception as e:
        logger.warning(f"[preprocess] _extract_slots failed: {e}")
        return {"entities": [], "metrics": [], "time_range": None, "aggregation": None, "conditions": []}


def _extract_entity_mentions(question: str) -> list:
    """从问题中提取实体关键词（轻量 LLM 调用，只提取不做决策）。"""
    try:
        from backend.services.agentic_qa.agents.entity_resolver import _extract_entity_mentions as _extract
        return _extract(question)
    except Exception as e:
        logger.warning(f"[assemble_context] _extract_entity_mentions failed: {e}")
        return []


def _match_schemas(question: str, limit: int = 3) -> List[Dict]:
    """关键词匹配找出相关表及其Schema摘要"""
    try:
        from backend.services.agentic_qa.vanna.agent import get_vanna_manager
        manager = get_vanna_manager()
        schemas = manager.search_table_schemas(question, limit=limit)
        result = []
        for s in (schemas or []):
            content = s.content if hasattr(s, 'content') else str(s)
            result.append({"table": s.table_name if hasattr(s, 'table_name') else "", "schema": content})
        return result
    except Exception:
        return []


def _search_similar_queries(question: str, top_k: int = 5) -> list:
    """搜索相似历史查询"""
    try:
        from backend.services.agentic_qa.memory import get_memory_hub
        hub = get_memory_hub("default")
        return hub.search_similar_queries(question, top_k=top_k)
    except Exception:
        return []


def _search_themes() -> list:
    """从记忆库中提取所有已训练的主题（去重）"""
    try:
        from backend.services.agentic_qa.vanna.agent import get_vanna_manager
        manager = get_vanna_manager()
        collection = manager.memory._get_collection()
        results = collection.get(include=["metadatas"])
        themes = set()
        for meta in (results.get("metadatas") or []):
            t = (meta or {}).get("theme", "")
            if t:
                themes.add(t)
        return sorted(themes)
    except Exception:
        return []


_ALL_ENTITY_TYPES = ["device", "production_line", "workshop", "department", "device_type", "company"]


def _search_cross_type(keyword: str, exclude_type: str = "", limit: int = 5) -> list:
    """跨类型搜索兜底 — 并行搜索排除已搜类型外的所有类型。"""
    types_to_search = [t for t in _ALL_ENTITY_TYPES if t != exclude_type]
    all_results = []

    def _search_one(etype):
        try:
            results = _search_with_fallback(keyword, etype)
            return results[:2] if results else []
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(types_to_search)) as pool:
        futures = {pool.submit(_search_one, t): t for t in types_to_search}
        for future in concurrent.futures.as_completed(futures):
            try:
                all_results.extend(future.result())
            except Exception:
                pass

    all_results.sort(key=lambda r: r.get("score", 0), reverse=True)
    return all_results[:limit]


def _search_with_fallback(keyword: str, entity_type: str = "") -> list:
    """实体搜索：别名 → 图 → 向量 → LIKE 兜底"""
    try:
        from backend.services.agentic_qa.agents.entity_resolver import _search_with_fallback as _search
        return _search(keyword, entity_type)
    except Exception:
        return []


# Backward-compatible alias — master_loop.py still imports `preprocess`
async def preprocess(question: str, session_memory: dict = None) -> Dict[str, Any]:
    """DEPRECATED: Use assemble_context instead."""
    return await assemble_context(question, session_memory)


def format_pre_context(pre: Dict) -> str:
    """将预处理结果格式化为注入 system prompt 的文本"""
    parts = []

    # 槽位信息（问题结构化理解）
    slots = pre.get("slots", {})
    if slots:
        has_content = (
            slots.get("entities") or slots.get("metrics") or
            slots.get("time_range") or slots.get("aggregation") or slots.get("conditions")
        )
        if has_content:
            slot_lines = []
            entities = slots.get("entities", [])
            if entities:
                entity_texts = []
                for e in entities:
                    if isinstance(e, dict):
                        name = e.get("name", "")
                        hint = e.get("type_hint", "")
                        entity_texts.append(f"{name}({hint})" if hint else name)
                    else:
                        entity_texts.append(str(e))
                slot_lines.append(f"  实体: {', '.join(entity_texts)}")
            if slots.get("metrics"):
                slot_lines.append(f"  指标: {', '.join(slots['metrics'])}")
            if slots.get("time_range"):
                slot_lines.append(f"  时间: {slots['time_range']}")
            if slots.get("aggregation"):
                slot_lines.append(f"  聚合: {slots['aggregation']}")
            if slots.get("conditions"):
                slot_lines.append(f"  条件: {', '.join(slots['conditions'])}")
            if slot_lines:
                parts.append("## 问题槽位（用户意图的结构化理解）\n" + "\n".join(slot_lines))

    # 已确认实体
    confirmed = pre.get("confirmed_entities", [])
    if confirmed:
        lines = []
        for ec in confirmed:
            field = ec.get("field", ec.get("entity_type", "实体"))
            values = ec.get("values", ec.get("selected_values", []))
            if values:
                lines.append(f"- {field}: {', '.join(str(v) for v in values)}")
        if lines:
            parts.append("已确认实体:\n" + "\n".join(lines))

    # 实体候选
    entity_candidates = pre.get("entity_candidates", {})
    if entity_candidates:
        for keyword, candidates in entity_candidates.items():
            if candidates:
                cand_labels = []
                for c in candidates[:5]:
                    label = c.get("label", "")
                    etype = c.get("entity_label") or c.get("entity_type") or ""
                    if etype:
                        cand_labels.append(f"{label}({etype})")
                    else:
                        cand_labels.append(label)
                parts.append(f"候选实体 '{keyword}': {', '.join(cand_labels)}")

    # 相关表 Schema
    tables = pre.get("relevant_schemas", [])
    if tables:
        items = "\n".join(f"  - {t['table']}: {t['schema'][:200]}" for t in tables)
        parts.append(f"相关表Schema:\n{items}")

    # 已训练主题
    themes = pre.get("trained_themes", [])
    if themes:
        parts.append(f"已训练主题: {', '.join(themes)}")

    # 查询蓝图
    blueprint = pre.get("query_blueprint")
    if blueprint:
        from backend.services.agentic_qa.blueprint import format_blueprint_section
        blueprint_text = format_blueprint_section(blueprint)
        if blueprint_text:
            parts.append(blueprint_text)

    return "\n\n".join(parts)
