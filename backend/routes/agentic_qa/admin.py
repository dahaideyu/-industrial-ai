# cython: annotation_typing=False, infer_types=False, language_level=3
"""管理后台 API — 训练管理、记忆库管理、统计监控、实体管理"""
from fastapi import APIRouter, Depends, HTTPException, Query, Body, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import asyncio
import time
import json
import re

from backend.services.agentic_qa.vanna.agent import get_vanna_manager, _make_context
from backend.services.agentic_qa.batch_generator import get_batch_generator
from backend.services.agentic_qa.db.mysql import db
from backend.services.agentic_qa.agents.entity_resolver import (
    get_registry, index_entities,
    load_alias_map, load_custom_metrics,
    add_entity_alias, update_entity_alias, delete_entity_alias,
    add_custom_metric, update_custom_metric, delete_custom_metric,
    search_entity_vector,
)
from backend.core.agentic_qa.logger import get_logger
from backend.routes.agentic_qa.dependencies import get_current_user

logger = get_logger("api.admin")
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_user)])


# ---- 请求模型 ----

class TrainRequest(BaseModel):
    type: str  # "documentation", "sql_pair"
    content: str  # 文档内容 / 问题描述
    sql: Optional[str] = None  # 仅在 sql_pair 时使用
    question: Optional[str] = None  # 仅在 sql_pair 时使用
    theme: Optional[str] = None  # 训练主题（可选）


class PresetRequest(BaseModel):
    question: str
    category: Optional[str] = "general"


# ---- 记忆库管理 ----

@router.get("/memories")
async def list_memories(
    type: Optional[str] = Query(None, description="sql_pair / documentation / all"),
    search: Optional[str] = Query(None),
    theme: Optional[str] = Query(None, description="按主题筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页数量"),
    random: bool = Query(False, description="随机排序结果"),
):
    """列出记忆库内容（服务端分页）"""
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")

    # 内部使用大 limit 获取全部数据，再分页
    fetch_limit = 10000
    results = []

    if type == "sql_pair" or type is None:
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                recent = ex.submit(
                    asyncio.run,
                    manager._memory.get_recent_memories(ctx, limit=fetch_limit)
                ).result(timeout=30)
        except RuntimeError:
            recent = asyncio.run(
                manager._memory.get_recent_memories(ctx, limit=fetch_limit)
            )
        for mem in recent:
            q = mem.question if hasattr(mem, 'question') else ''
            if q.startswith('[待审核]') or q.startswith('[待审核-反馈]'):
                continue
            meta = mem.metadata if hasattr(mem, 'metadata') and mem.metadata else {}
            results.append({
                "id": mem.memory_id,
                "type": "sql_pair",
                "question": mem.question,
                "tool_name": mem.tool_name,
                "args": mem.args,
                "success": mem.success,
                "timestamp": mem.timestamp,
                "metadata": meta,
                "theme": meta.get("theme", ""),
            })

    if type == "documentation" or type is None:
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                text_mems = ex.submit(
                    asyncio.run,
                    manager._memory.get_recent_text_memories(ctx, limit=fetch_limit)
                ).result(timeout=30)
        except RuntimeError:
            text_mems = asyncio.run(
                manager._memory.get_recent_text_memories(ctx, limit=fetch_limit)
            )
        for mem in text_mems:
            results.append({
                "id": mem.memory_id,
                "type": "documentation",
                "content": mem.content,
                "timestamp": mem.timestamp,
                "theme": "",
            })

    # 搜索过滤
    if search:
        search_lower = search.lower()
        results = [
            r for r in results
            if search_lower in str(r.get("question", "")).lower()
            or search_lower in str(r.get("content", "")).lower()
            or search_lower in str(r.get("args", "")).lower()
        ]

    # 主题过滤
    if theme:
        results = [r for r in results if r.get("theme") == theme]

    # 按时间倒序
    results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    if random:
        import random as _random
        _random.shuffle(results)

    total = len(results)
    # 服务端分页
    start = (page - 1) * page_size
    paged = results[start:start + page_size]

    return {"success": True, "memories": paged, "total": total, "page": page, "page_size": page_size}


@router.get("/memories/themes")
async def list_memory_themes():
    """获取所有已使用的主题列表"""
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            recent = ex.submit(
                asyncio.run,
                manager._memory.get_recent_memories(ctx, limit=10000)
            ).result(timeout=30)
    except RuntimeError:
        recent = asyncio.run(
            manager._memory.get_recent_memories(ctx, limit=10000)
        )
    themes = set()
    for mem in recent:
        meta = getattr(mem, 'metadata', None) or {}
        t = meta.get("theme", "")
        if t:
            themes.add(t)
    return {"themes": sorted(themes)}


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str):
    """删除指定记忆"""
    logger.info(f"[admin] deleting memory: {memory_id}")
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            ok = ex.submit(
                asyncio.run,
                manager._memory.delete_by_id(ctx, memory_id)
            ).result(timeout=10)
    except RuntimeError:
        ok = asyncio.run(manager._memory.delete_by_id(ctx, memory_id))
    return {"success": ok}


class BatchDeleteRequest(BaseModel):
    ids: List[str]


@router.post("/memories/batch-delete")
async def batch_delete_memories(req: BatchDeleteRequest):
    """批量删除记忆"""
    if not req.ids:
        raise HTTPException(400, "ids 不能为空")
    logger.info(f"[admin] batch deleting {len(req.ids)} memories")
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")
    deleted = 0
    failed = 0
    for mid in req.ids:
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                ok = ex.submit(
                    asyncio.run,
                    manager._memory.delete_by_id(ctx, mid)
                ).result(timeout=10)
        except RuntimeError:
            ok = asyncio.run(manager._memory.delete_by_id(ctx, mid))
        if ok:
            deleted += 1
        else:
            failed += 1
    return {"success": True, "deleted": deleted, "failed": failed}


@router.delete("/memories")
async def clear_memories(type: Optional[str] = None):
    """清空记忆库并重置 Vanna Agent（确保新数据写入新集合）"""
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")
    tool_filter = "run_sql" if type == "sql_pair" else None
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            count = ex.submit(
                asyncio.run,
                manager._memory.clear_memories(ctx, tool_name=tool_filter)
            ).result(timeout=10)
    except RuntimeError:
        count = asyncio.run(
            manager._memory.clear_memories(ctx, tool_name=tool_filter)
        )
    manager.reset()
    return {"success": True, "deleted": count}


# ---- 手动训练 ----

@router.post("/memories/train")
async def train_memory(req: TrainRequest):
    """手动注入训练数据"""
    logger.info(f"[admin] manual training: type={req.type} question='{(req.question or '')[:60]}'")
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")

    if req.type == "documentation":
        await _train_async(manager._memory.save_text_memory(
            content=req.content, context=ctx
        ))
        return {"success": True, "message": "文档已注入"}

    elif req.type == "sql_pair":
        if not req.sql or not req.question:
            raise HTTPException(400, "SQL 对训练需要 question 和 sql 字段")
        save_meta = {"theme": req.theme} if req.theme else None
        await _train_async(manager._memory.save_tool_usage(
            question=req.question,
            tool_name="run_sql",
            args={"sql": req.sql},
            context=ctx,
            success=True,
            metadata=save_meta,
        ))
        return {"success": True, "message": "SQL 对已注入"}

    raise HTTPException(400, f"未知训练类型: {req.type}")


# ---- 记忆库导入导出 ----


@router.get("/memories/export")
async def export_memories(
    type: Optional[str] = Query(None, description="sql_pair / documentation / all"),
):
    """导出记忆库数据为 JSON"""
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")
    entries = []

    if type == "sql_pair" or type is None:
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                recent = ex.submit(
                    asyncio.run,
                    manager._memory.get_recent_memories(ctx, limit=10000)
                ).result(timeout=60)
        except RuntimeError:
            recent = asyncio.run(
                manager._memory.get_recent_memories(ctx, limit=10000)
            )
        for mem in recent:
            q = mem.question if hasattr(mem, 'question') else ''
            if q.startswith('[待审核]') or q.startswith('[待审核-反馈]'):
                continue
            meta = getattr(mem, 'metadata', None) or {}
            entries.append({
                "type": "sql_pair",
                "question": mem.question,
                "sql": mem.args.get("sql", "") if mem.args else "",
                "theme": meta.get("theme", ""),
            })

    if type == "documentation" or type is None:
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                text_mems = ex.submit(
                    asyncio.run,
                    manager._memory.get_recent_text_memories(ctx, limit=10000)
                ).result(timeout=60)
        except RuntimeError:
            text_mems = asyncio.run(
                manager._memory.get_recent_text_memories(ctx, limit=10000)
            )
        for mem in text_mems:
            entries.append({
                "type": "documentation",
                "content": mem.content,
                "theme": "",
            })

    export_data = {
        "version": 2,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "entity": "memories",
        "entries": entries,
    }
    return Response(
        content=json.dumps(export_data, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=memories-export.json"},
    )


@router.post("/memories/import")
async def import_memories(body: Dict[str, Any] = Body(...)):
    """导入记忆库 JSON 数据（Merge 模式：与已有数据去重，跳过重复条目）"""
    if body.get("entity") != "memories":
        raise HTTPException(400, "文件 entity 类型不匹配，期望 'memories'")

    entries = body.get("entries", [])
    if not isinstance(entries, list) or len(entries) == 0:
        raise HTTPException(400, "entries 为空或格式错误")

    try:
        manager = get_vanna_manager()
        ctx = _make_context(manager._memory, "admin")

        # 预加载已有记忆，构建指纹集合用于去重
        existing_fingerprints: set = set()
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                existing_sql = ex.submit(
                    asyncio.run,
                    manager._memory.get_recent_memories(ctx, limit=10000)
                ).result(timeout=60)
                existing_docs = ex.submit(
                    asyncio.run,
                    manager._memory.get_recent_text_memories(ctx, limit=10000)
                ).result(timeout=60)
        except RuntimeError:
            existing_sql = asyncio.run(manager._memory.get_recent_memories(ctx, limit=10000))
            existing_docs = asyncio.run(manager._memory.get_recent_text_memories(ctx, limit=10000))

        for mem in existing_sql:
            q = (mem.question or "").strip() if hasattr(mem, 'question') else ""
            s = (mem.args.get("sql", "") or "").strip() if hasattr(mem, 'args') and isinstance(mem.args, dict) else ""
            if q or s:
                existing_fingerprints.add(("sql_pair", q, s))
        for mem in existing_docs:
            c = (mem.content or "").strip() if hasattr(mem, 'content') else ""
            if c:
                existing_fingerprints.add(("documentation", c))

        results = []
        imported = 0
        failed = 0
        skipped = 0

        for i, entry in enumerate(entries):
            if i > 0:
                await asyncio.sleep(0.1)

            entry_type = entry.get("type", "")
            if entry_type == "sql_pair":
                question = (entry.get("question") or "").strip()
                sql = (entry.get("sql") or "").strip()
                if not question or not sql:
                    results.append({"index": i, "status": "error", "message": "缺少 question 或 sql 字段"})
                    failed += 1
                    continue
                fp = ("sql_pair", question, sql)
                if fp in existing_fingerprints:
                    results.append({"index": i, "status": "skipped", "message": "与已有数据重复，已跳过"})
                    skipped += 1
                    continue
                entry_theme = (entry.get("theme") or "").strip()
                save_meta = {"theme": entry_theme} if entry_theme else None
                ok, err = await _import_with_retry(lambda: manager._memory.save_tool_usage(
                    question=question,
                    tool_name="run_sql",
                    args={"sql": sql},
                    context=ctx,
                    success=True,
                    metadata=save_meta,
                ))
                if ok:
                    existing_fingerprints.add(fp)
                    results.append({"index": i, "status": "ok", "type": "sql_pair"})
                    imported += 1
                else:
                    results.append({"index": i, "status": "error", "message": err})
                    failed += 1
            elif entry_type == "documentation":
                content = (entry.get("content") or "").strip()
                if not content:
                    results.append({"index": i, "status": "error", "message": "缺少 content 字段"})
                    failed += 1
                    continue
                fp = ("documentation", content)
                if fp in existing_fingerprints:
                    results.append({"index": i, "status": "skipped", "message": "与已有数据重复，已跳过"})
                    skipped += 1
                    continue
                ok, err = await _import_with_retry(lambda: manager._memory.save_text_memory(
                    content=content, context=ctx
                ))
                if ok:
                    existing_fingerprints.add(fp)
                    results.append({"index": i, "status": "ok", "type": "documentation"})
                    imported += 1
                else:
                    results.append({"index": i, "status": "error", "message": err})
                    failed += 1
            else:
                results.append({"index": i, "status": "error", "message": f"未知类型: {entry_type}"})
                failed += 1

        return {"success": True, "imported": imported, "failed": failed, "skipped": skipped, "results": results}
    except Exception as e:
        logger.exception(f"[import] 记忆库导入异常: {e}")
        return {"success": False, "imported": 0, "failed": 0, "error": str(e)}


class EditMemoryRequest(BaseModel):
    memory_id: str
    type: str  # "sql_pair" | "documentation"
    question: Optional[str] = None
    sql: Optional[str] = None
    content: Optional[str] = None
    theme: Optional[str] = None


@router.put("/memories/edit")
async def edit_memory(req: EditMemoryRequest):
    """编辑记忆库条目：删除旧向量 → 重新向量化"""
    logger.info(f"[admin] edit memory: id={req.memory_id} type={req.type}")
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")

    # 1. 删除旧条目
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            ex.submit(asyncio.run, manager._memory.delete_by_id(ctx, req.memory_id)).result(timeout=10)
    except RuntimeError:
        await asyncio.wait_for(manager._memory.delete_by_id(ctx, req.memory_id), timeout=10)

    # 2. 重新向量化保存
    if req.type == "sql_pair":
        if not req.sql or not req.question:
            raise HTTPException(400, "SQL 对需要 question 和 sql")
        save_meta = {"theme": req.theme} if req.theme else None
        await _train_async(manager._memory.save_tool_usage(
            question=req.question, tool_name="run_sql",
            args={"sql": req.sql}, context=ctx, success=True,
            metadata=save_meta,
        ))
    elif req.type == "documentation":
        if not req.content:
            raise HTTPException(400, "文档需要 content")
        await _train_async(manager._memory.save_text_memory(
            content=req.content, context=ctx
        ))

    return {"success": True, "message": "记忆已更新并重新向量化"}


async def _train_async(coro):
    try:
        await coro
    except RuntimeError as e:
        logger.warning(f"[train] RuntimeError ignored: {e}")


async def _import_with_retry(fn, max_retries=3):
    """带指数退避的重试（fn 是无参 callable，每次调用返回全新协程）"""
    for attempt in range(max_retries):
        try:
            await fn()
            return True, None
        except RuntimeError as e:
            logger.warning(f"[import] RuntimeError (协程异常，不重试): {e}")
            return False, str(e)
        except Exception as e:
            if attempt < max_retries - 1:
                delay = 0.15 * (2 ** attempt)
                logger.warning(f"[import] 第{attempt+1}次尝试失败: {e}, {delay:.2f}s 后重试")
                await asyncio.sleep(delay)
            else:
                logger.error(f"[import] 重试{max_retries}次全部失败: {e}")
                return False, str(e)


# ---- 统计监控 ----

@router.get("/stats")
async def get_stats():
    """获取使用统计"""
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")

    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            sql_mems = ex.submit(
                asyncio.run,
                manager._memory.get_recent_memories(ctx, limit=1000)
            ).result(timeout=30)
    except RuntimeError:
        sql_mems = asyncio.run(
            manager._memory.get_recent_memories(ctx, limit=1000)
        )

    total = len(sql_mems)
    successful = sum(1 for m in sql_mems if m.success)

    return {
        "success": True,
        "stats": {
            "total_queries": total,
            "successful_queries": successful,
            "success_rate": round(successful / total * 100, 1) if total > 0 else 0,
            "queries_today": 0
        }
    }


# ---- 预置问题管理 ----

_presets: List[Dict[str, str]] = [
    {"question": "所有产线列表", "category": "设备查询"},
    {"question": "查询设备数量", "category": "设备查询"},
    {"question": "最近添加的设备", "category": "设备查询"},
]


@router.get("/presets")
async def get_presets():
    return {"success": True, "presets": _presets}


@router.post("/presets")
async def add_preset(req: PresetRequest):
    _presets.append({"question": req.question, "category": req.category or "general"})
    return {"success": True, "presets": _presets}


# ============================================================
# 实体管理 API
# ============================================================

class EntityAliasRequest(BaseModel):
    entity_type: str
    alias: str
    canonical_name: str
    canonical_value: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class EntityAliasUpdate(BaseModel):
    entity_type: Optional[str] = None
    alias: Optional[str] = None
    canonical_name: Optional[str] = None
    canonical_value: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class CustomMetricRequest(BaseModel):
    name: str
    description: Optional[str] = None
    sql_expression: Optional[str] = None
    entity_type: Optional[str] = None
    keywords: Optional[str] = None


class CustomMetricUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sql_expression: Optional[str] = None
    entity_type: Optional[str] = None
    keywords: Optional[str] = None


class EntitySearchRequest(BaseModel):
    entity_type: str
    keyword: str
    limit: int = 10


# —— 实体注册表 ——

@router.get("/entities/registry")
async def get_entity_registry():
    """获取实体注册表配置"""
    registry = get_registry()
    return {
        "success": True,
        "registry": {
            key: {
                "label": cfg.get("label", key),
                "table": cfg.get("table", ""),
                "search_columns": cfg.get("search_columns", []),
                "label_column": cfg.get("label_column", ""),
                "value_column": cfg.get("value_column", ""),
                "context_columns": cfg.get("context_columns", []),
                "keyword_hints": cfg.get("keyword_hints", []),
                "discovered": cfg.get("discovered", False),
            }
            for key, cfg in registry.items()
        }
    }


@router.post("/entities/search")
async def search_entities(req: EntitySearchRequest):
    """搜索实体（使用完整回退链：别名→图→向量→LIKE→全量DB）"""
    from backend.services.agentic_qa.agents.entity_resolver import _search_with_fallback
    results = _search_with_fallback(req.keyword, entity_type=req.entity_type, original_text=req.keyword)
    return {"success": True, "results": results, "total": len(results)}


@router.post("/entities/index")
async def rebuild_entity_index():
    """重建实体向量索引（扫描所有已配置的表并写入 ChromaDB）"""
    count = index_entities(force=True)
    # 更新索引状态
    try:
        from backend.services.agentic_qa.models.entity_config import EntityConfig
        from backend.core.agentic_qa.database import SessionLocal
        db = SessionLocal()
        try:
            db.query(EntityConfig).update({"is_indexed": True})
            db.commit()
        finally:
            db.close()
    except Exception:
        pass
    return {"success": True, "message": f"已索引 {count} 个实体", "count": count}


# ── 实体配置 CRUD ──

class EntityConfigCreate(BaseModel):
    entity_type: str
    label: str
    table_name: str
    search_columns: List[str] = []
    label_column: str = "name"
    value_column: str = "id"
    context_columns: List[str] = []
    keyword_hints: List[str] = []
    filter_condition: str = "del_flag = 0"


class EntityConfigUpdate(BaseModel):
    label: Optional[str] = None
    search_columns: Optional[List[str]] = None
    label_column: Optional[str] = None
    value_column: Optional[str] = None
    context_columns: Optional[List[str]] = None
    keyword_hints: Optional[List[str]] = None
    filter_condition: Optional[str] = None


@router.get("/entities/configs")
async def list_entity_configs():
    from backend.services.agentic_qa.models.entity_config import EntityConfig
    from backend.core.agentic_qa.database import SessionLocal
    db = SessionLocal()
    try:
        configs = db.query(EntityConfig).all()
        return {"success": True, "configs": [c.to_dict() for c in configs]}
    finally:
        db.close()


@router.post("/entities/configs")
async def create_entity_config(req: EntityConfigCreate):
    import json
    from backend.services.agentic_qa.models.entity_config import EntityConfig
    from backend.core.agentic_qa.database import SessionLocal
    db = SessionLocal()
    try:
        existing = db.query(EntityConfig).filter(EntityConfig.entity_type == req.entity_type).first()
        if existing:
            raise HTTPException(400, f"实体类型 '{req.entity_type}' 已存在")
        cfg = EntityConfig(
            entity_type=req.entity_type, label=req.label, table_name=req.table_name,
            search_columns=json.dumps(req.search_columns, ensure_ascii=False),
            label_column=req.label_column, value_column=req.value_column,
            context_columns=json.dumps(req.context_columns, ensure_ascii=False),
            keyword_hints=json.dumps(req.keyword_hints, ensure_ascii=False),
            filter_condition=req.filter_condition,
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
        return {"success": True, "config": cfg.to_dict()}
    finally:
        db.close()


@router.put("/entities/configs/{config_id}")
async def update_entity_config(config_id: int, req: EntityConfigUpdate):
    import json
    from backend.services.agentic_qa.models.entity_config import EntityConfig
    from backend.core.agentic_qa.database import SessionLocal
    db = SessionLocal()
    try:
        cfg = db.query(EntityConfig).filter(EntityConfig.id == config_id).first()
        if not cfg:
            raise HTTPException(404, "配置不存在")
        if req.label is not None: cfg.label = req.label
        if req.search_columns is not None: cfg.search_columns = json.dumps(req.search_columns, ensure_ascii=False)
        if req.label_column is not None: cfg.label_column = req.label_column
        if req.value_column is not None: cfg.value_column = req.value_column
        if req.context_columns is not None: cfg.context_columns = json.dumps(req.context_columns, ensure_ascii=False)
        if req.keyword_hints is not None: cfg.keyword_hints = json.dumps(req.keyword_hints, ensure_ascii=False)
        if req.filter_condition is not None: cfg.filter_condition = req.filter_condition
        cfg.is_indexed = False
        db.commit()
        return {"success": True, "config": cfg.to_dict()}
    finally:
        db.close()


@router.delete("/entities/configs/{config_id}")
async def delete_entity_config(config_id: int):
    from backend.services.agentic_qa.models.entity_config import EntityConfig
    from backend.core.agentic_qa.database import SessionLocal
    db = SessionLocal()
    try:
        cfg = db.query(EntityConfig).filter(EntityConfig.id == config_id).first()
        if not cfg:
            raise HTTPException(404, "配置不存在")
        db.delete(cfg)
        db.commit()
        return {"success": True}
    finally:
        db.close()


class GenerateKeywordsRequest(BaseModel):
    label: str
    table_name: str
    columns: List[str] = []


@router.post("/entities/configs/generate-keywords")
async def generate_keywords(req: GenerateKeywordsRequest):
    try:
        from backend.core.agentic_qa.llm import llm
        prompt = """为数据库实体生成中文搜索关键词（5-10个）。每个关键词2-4个字。
实体标签: {}
数据库表: {}
包含的列: {}

要求: 关键词应覆盖用户可能的叫法（简称、别名、口语化表达）
只输出JSON数组: ["关键词1","关键词2",...]""".format(req.label, req.table_name, ', '.join(req.columns) if req.columns else '无')
        response = llm.chat_once(user_prompt=prompt, temperature=0.3, max_tokens=2048)
        logger.info(f"[admin] keyword LLM raw ({len(response)} chars): {response[:300]}")
        cleaned = response.strip()
        keywords = []
        if cleaned:
            if cleaned.startswith("```"): cleaned = re.sub(r"^```\w*\n?", "", cleaned); cleaned = re.sub(r"\n?```$", "", cleaned)
            match = re.search(r'\[.*\]', cleaned, re.DOTALL)
            if match:
                try:
                    keywords = json.loads(match.group())
                except (json.JSONDecodeError, TypeError):
                    inner = match.group().strip('[]')
                    keywords = [k.strip().strip('"''"').strip() for k in inner.split(',') if k.strip()]
            if not keywords:
                keywords = [line.lstrip('0123456789.、- "''"') for line in cleaned.split('\n') if len(line.strip()) >= 2]
        # LLM 返回空时的兜底关键词
        if not keywords:
            keywords = [req.label] if req.label else []
        logger.info(f"[admin] generated {len(keywords)} keywords for '{req.label}': {keywords[:5]}")
        return {"success": True, "keywords": keywords}
    except Exception as e:
        logger.warning(f"[admin] keyword generation failed: {e}")
        return {"success": True, "keywords": [req.label] if req.label else [], "error": str(e)}


# ── 数据库表/列查询 ──

@router.get("/tables")
async def list_tables():
    from backend.services.agentic_qa.db.mysql import db as mysql_db
    try:
        rows = mysql_db.execute_query("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME")
        return {"success": True, "tables": [r["TABLE_NAME"] for r in rows]}
    except Exception as e:
        return {"success": False, "tables": [], "error": str(e)}


@router.get("/tables/{table_name}/columns")
async def list_columns(table_name: str):
    from backend.services.agentic_qa.db.mysql import db as mysql_db
    try:
        rows = mysql_db.execute_query(
            "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
            (table_name,)
        )
        return {"success": True, "columns": [{"name": r["COLUMN_NAME"], "type": r["DATA_TYPE"], "comment": r.get("COLUMN_COMMENT", "")} for r in rows]}
    except Exception as e:
        return {"success": False, "columns": [], "error": str(e)}


class TableIndexRequest(BaseModel):
    table_names: List[str]


@router.get("/schemas/status")
async def get_schema_index_status():
    """获取所有表的索引状态"""
    manager = get_vanna_manager()
    return {"success": True, **manager.get_index_status()}


@router.post("/schemas/index")
async def index_tables(req: TableIndexRequest):
    """索引选中的表结构到 Vanna 记忆库"""
    if not req.table_names:
        raise HTTPException(400, "请选择要索引的表")
    manager = get_vanna_manager()
    result = manager.index_table_schemas(req.table_names)
    return {"success": True, **result}


# —— 训练审核队列（从 Vanna 记忆中检索 [待审核] 标记的条目） ——

@router.get("/training-review")
async def list_reviews(
    review_type: Optional[str] = Query("all", description="pending / feedback / all"),
):
    """获取待审核的训练条目

    review_type:
      - pending: 正确反馈 [待审核]
      - feedback: 错误反馈 [待审核-反馈]
      - all: 全部
    """
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            memories = ex.submit(
                asyncio.run,
                manager._memory.get_recent_memories(ctx, limit=200)
            ).result(timeout=30)
    except RuntimeError:
        memories = asyncio.run(manager._memory.get_recent_memories(ctx, limit=200))

    reviews = []
    for m in memories:
        q = m.question if hasattr(m, 'question') else ''
        args = m.args if hasattr(m, 'args') else {}

        is_feedback = q.startswith('[待审核-反馈]')
        is_pending = '[待审核]' in q and not is_feedback

        if not is_pending and not is_feedback:
            continue

        # 按类型筛选
        if review_type == 'pending' and not is_pending:
            continue
        if review_type == 'feedback' and not is_feedback:
            continue

        meta = getattr(m, 'metadata', None) or {}
        entry = {
            "id": m.memory_id,
            "question": q.replace('[待审核-反馈] ', '').replace('[待审核] ', ''),
            "sql": args.get("sql", "") if isinstance(args, dict) else "",
            "type": "feedback" if is_feedback else "pending",
            "status": "pending",
            "created_at": getattr(m, 'timestamp', ''),
            "theme": meta.get("theme", ""),
        }

        # 错误反馈附加信息
        if is_feedback:
            entry["answer"] = args.get("answer", "") if isinstance(args, dict) else ""
            entry["user_feedback"] = args.get("user_feedback", "") if isinstance(args, dict) else ""

        reviews.append(entry)

    return {"success": True, "reviews": reviews, "total": len(reviews)}


class ReviewAction(BaseModel):
    review_id: str
    action: str  # "approve", "edit", "delete"
    question: Optional[str] = None
    sql: Optional[str] = None
    theme: Optional[str] = None


@router.post("/training-review/action")
async def handle_review_action(req: ReviewAction):
    """处理审核"""
    manager = get_vanna_manager()
    ctx = _make_context(manager._memory, "admin")

    if req.action == "delete":
        await _train_async(manager._memory.delete_by_id(ctx, req.review_id))
        return {"success": True, "message": "已删除"}

    # approve/edit: 先删旧条目（含 [待审核] 前缀），再保存干净版本
    try:
        await _train_async(manager._memory.delete_by_id(ctx, req.review_id))
    except Exception:
        pass

    q = (req.question or "").strip()
    s = (req.sql or "").strip()
    if not q and not s:
        raise HTTPException(400, "问题和 SQL 不能同时为空")
    save_meta = {"theme": req.theme} if req.theme else None
    await _train_async(manager._memory.save_tool_usage(
        question=q, tool_name="run_sql",
        args={"sql": s}, context=ctx, success=True,
        metadata=save_meta,
    ))
    return {"success": True, "message": "已审核入库"}


@router.post("/schemas/unindex")
async def unindex_tables(req: TableIndexRequest):
    """从 Vanna 记忆中删除指定表的索引"""
    if not req.table_names:
        raise HTTPException(400, "请选择要取消索引的表")
    manager = get_vanna_manager()
    result = manager.unindex_tables(req.table_names)
    return {"success": True, **result}


# —— 实体别名 ——

@router.get("/entities/aliases")
async def list_aliases(
    entity_type: Optional[str] = Query(None),
):
    """列出实体别名"""
    aliases = load_alias_map(entity_type)
    return {"success": True, "aliases": aliases, "total": len(aliases)}


@router.post("/entities/aliases")
async def create_alias(req: EntityAliasRequest):
    """添加实体别名映射"""
    ok = add_entity_alias(
        entity_type=req.entity_type,
        alias=req.alias,
        canonical_name=req.canonical_name,
        canonical_value=req.canonical_value,
        context=req.context,
    )
    if not ok:
        raise HTTPException(500, "添加别名失败")
    return {"success": True, "message": f"别名 '{req.alias}' -> '{req.canonical_name}' 已添加"}


@router.put("/entities/aliases/{alias_id}")
async def edit_alias(alias_id: str, req: EntityAliasUpdate):
    """修改实体别名"""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "没有需要更新的字段")
    ok = update_entity_alias(alias_id, **updates)
    if not ok:
        raise HTTPException(500, "更新别名失败")
    return {"success": True, "message": f"别名 {alias_id} 已更新"}


@router.delete("/entities/aliases/{alias_id}")
async def remove_alias(alias_id: str):
    """删除实体别名"""
    ok = delete_entity_alias(alias_id)
    if not ok:
        raise HTTPException(500, "删除别名失败")
    return {"success": True, "message": f"别名 {alias_id} 已删除"}


@router.get("/entities/aliases/export")
async def export_aliases():
    """导出实体别名为 JSON"""
    aliases = load_alias_map()
    entries = []
    for a in aliases:
        entries.append({
            "entity_type": a.get("entity_type", ""),
            "alias": a.get("alias", ""),
            "canonical_name": a.get("canonical_name", ""),
            "canonical_value": a.get("canonical_value", ""),
            "context": a.get("context", {}),
        })
    export_data = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "entity": "entity_aliases",
        "entries": entries,
    }
    return Response(
        content=json.dumps(export_data, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=entity-aliases-export.json"},
    )


@router.post("/entities/aliases/import")
async def import_aliases(body: Dict[str, Any] = Body(...)):
    """导入实体别名 JSON 数据（追加模式，不清空已有数据）"""
    if body.get("entity") != "entity_aliases":
        raise HTTPException(400, "文件 entity 类型不匹配，期望 'entity_aliases'")

    entries = body.get("entries", [])
    if not isinstance(entries, list) or len(entries) == 0:
        raise HTTPException(400, "entries 为空或格式错误")

    try:
        results = []
        imported = 0
        failed = 0

        for i, entry in enumerate(entries):
            if i > 0:
                await asyncio.sleep(0.1)

            try:
                entity_type = (entry.get("entity_type") or "").strip()
                alias = (entry.get("alias") or "").strip()
                canonical_name = (entry.get("canonical_name") or "").strip()
                if not entity_type or not alias or not canonical_name:
                    results.append({"index": i, "status": "error", "message": "缺少必填字段 (entity_type/alias/canonical_name)"})
                    failed += 1
                    continue
                ok = add_entity_alias(
                    entity_type=entity_type,
                    alias=alias,
                    canonical_name=canonical_name,
                    canonical_value=entry.get("canonical_value") or "",
                    context=entry.get("context") or {},
                )
                if ok:
                    results.append({"index": i, "status": "ok", "alias": alias})
                    imported += 1
                else:
                    results.append({"index": i, "status": "error", "message": "添加别名失败"})
                    failed += 1
            except Exception as e:
                results.append({"index": i, "status": "error", "message": str(e)})
                failed += 1

        return {"success": True, "imported": imported, "failed": failed, "results": results}
    except Exception as e:
        logger.exception(f"[import] 别名导入异常: {e}")
        return {"success": False, "imported": 0, "failed": 0, "error": str(e)}


# —— 自定义指标 ——

@router.get("/entities/metrics")
async def list_metrics():
    """列出自定义指标"""
    metrics = load_custom_metrics()
    return {"success": True, "metrics": metrics, "total": len(metrics)}


@router.post("/entities/metrics")
async def create_metric(req: CustomMetricRequest):
    """添加自定义指标"""
    ok = add_custom_metric(
        name=req.name,
        description=req.description,
        sql_expression=req.sql_expression,
        entity_type=req.entity_type,
        keywords=req.keywords,
    )
    if not ok:
        raise HTTPException(500, "添加指标失败")
    return {"success": True, "message": f"指标 '{req.name}' 已添加"}


@router.put("/entities/metrics/{metric_id}")
async def edit_metric(metric_id: str, req: CustomMetricUpdate):
    """修改自定义指标"""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "没有需要更新的字段")
    ok = update_custom_metric(metric_id, **updates)
    if not ok:
        raise HTTPException(500, "更新指标失败")
    return {"success": True, "message": f"指标 {metric_id} 已更新"}


@router.delete("/entities/metrics/{metric_id}")
async def remove_metric(metric_id: str):
    """删除自定义指标"""
    ok = delete_custom_metric(metric_id)
    if not ok:
        raise HTTPException(500, "删除指标失败")
    return {"success": True, "message": f"指标 {metric_id} 已删除"}


@router.get("/entities/metrics/export")
async def export_metrics():
    """导出自定义指标为 JSON"""
    metrics = load_custom_metrics()
    entries = []
    for m in metrics:
        entries.append({
            "name": m.get("name", ""),
            "description": m.get("description", ""),
            "sql_expression": m.get("sql_expression", ""),
            "entity_type": m.get("entity_type", ""),
            "keywords": m.get("keywords", ""),
        })
    export_data = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "entity": "custom_metrics",
        "entries": entries,
    }
    return Response(
        content=json.dumps(export_data, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=custom-metrics-export.json"},
    )


@router.post("/entities/metrics/import")
async def import_metrics(body: Dict[str, Any] = Body(...)):
    """导入自定义指标 JSON 数据（追加模式，不清空已有数据）"""
    if body.get("entity") != "custom_metrics":
        raise HTTPException(400, "文件 entity 类型不匹配，期望 'custom_metrics'")

    entries = body.get("entries", [])
    if not isinstance(entries, list) or len(entries) == 0:
        raise HTTPException(400, "entries 为空或格式错误")

    try:
        results = []
        imported = 0
        failed = 0

        for i, entry in enumerate(entries):
            if i > 0:
                await asyncio.sleep(0.1)

            try:
                name = (entry.get("name") or "").strip()
                if not name:
                    results.append({"index": i, "status": "error", "message": "缺少必填字段 name"})
                    failed += 1
                    continue
                ok = add_custom_metric(
                    name=name,
                    description=entry.get("description") or "",
                    sql_expression=entry.get("sql_expression") or "",
                    entity_type=entry.get("entity_type") or "",
                    keywords=entry.get("keywords") or "",
                )
                if ok:
                    results.append({"index": i, "status": "ok", "name": name})
                    imported += 1
                else:
                    results.append({"index": i, "status": "error", "message": "添加指标失败"})
                    failed += 1
            except Exception as e:
                results.append({"index": i, "status": "error", "message": str(e)})
                failed += 1

        return {"success": True, "imported": imported, "failed": failed, "results": results}
    except Exception as e:
        logger.exception(f"[import] 指标导入异常: {e}")
        return {"success": False, "imported": 0, "failed": 0, "error": str(e)}


# ============================================================
# Neo4j 知识图谱管理 API
# ============================================================

@router.post("/reload-graph")
async def reload_graph():
    """热重载知识图谱：重新从 MySQL + YAML 导入 Neo4j"""
    from backend.core.agentic_qa.graph_client import get_graph_client
    from backend.core.agentic_qa.graph_importer import import_to_neo4j, load_mapping
    from backend.services.agentic_qa.db.mysql import db
    from backend.core.agentic_qa.config import settings

    client = get_graph_client()
    if not client.is_available():
        raise HTTPException(503, "Neo4j 不可用，请检查 Neo4j 服务状态")

    try:
        mapping = load_mapping(settings.graph_mapping_path)
        result = import_to_neo4j(client, db, mapping)
        return {"success": result.get("success", False), **result}
    except FileNotFoundError:
        raise HTTPException(400, f"找不到图谱映射文件: {settings.graph_mapping_path}")
    except Exception as e:
        raise HTTPException(500, f"图谱重载失败: {e}")


@router.get("/graph-status")
async def get_graph_status():
    """获取 Neo4j 知识图谱状态（连接状态 + 各 Label 节点数）"""
    from backend.core.agentic_qa.graph_client import get_graph_client
    from backend.core.agentic_qa.config import settings

    client = get_graph_client()
    available = client.is_available()

    status = {
        "available": available,
        "uri": settings.neo4j_uri,
    }

    if available:
        try:
            from backend.core.agentic_qa.graph_importer import load_mapping
            from backend.core.agentic_qa.config import settings
            mapping = load_mapping(settings.graph_mapping_path)
            all_labels = {n["label"] for n in mapping.get("nodes", [])}
            all_labels.update(mn["label"] for mn in mapping.get("manual_nodes", []))

            # Build label_zh mapping from YAML nodes
            label_zh = {}
            for n in mapping.get("nodes", []):
                label_zh[n["label"]] = n.get("label_zh", n["label"])
            for mn in mapping.get("manual_nodes", []):
                label_zh[mn["label"]] = mn.get("label_zh", mn["label"])
            status["label_zh"] = label_zh

            counts = {}
            with client.driver.session() as session:
                for label in all_labels:
                    try:
                        result = session.run(
                            f"MATCH (n:`{label}`) RETURN count(n) AS c"
                        )
                        counts[label] = result.single()["c"]
                    except Exception:
                        counts[label] = -1
            status["node_counts"] = counts
        except Exception as e:
            status["query_error"] = str(e)

    return {"success": True, "status": status}


# ======== 图谱映射 YAML 编辑 ========


@router.get("/graph-mapping")
async def get_graph_mapping():
    """获取当前实体关系映射 YAML 内容"""
    from backend.core.agentic_qa.config import settings

    try:
        with open(settings.graph_mapping_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"success": True, "yaml": content}
    except FileNotFoundError:
        raise HTTPException(404, f"映射文件不存在: {settings.graph_mapping_path}")
    except Exception as e:
        raise HTTPException(500, f"读取映射文件失败: {e}")


@router.get("/graph-mapping/example")
async def get_graph_mapping_example():
    """获取带注释的示例 YAML 供前端展示"""
    import os
    from backend.core.agentic_qa.config import settings

    example_path = os.path.join(
        os.path.dirname(settings.graph_mapping_path), "graph_mapping.example.yaml"
    )
    try:
        with open(example_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"success": True, "yaml": content}
    except FileNotFoundError:
        raise HTTPException(404, "示例映射文件不存在")
    except Exception as e:
        raise HTTPException(500, f"读取示例文件失败: {e}")


class GraphMappingUpdateRequest(BaseModel):
    yaml: str


@router.put("/graph-mapping")
async def update_graph_mapping(data: GraphMappingUpdateRequest):
    """更新实体关系映射 YAML，校验后写入文件并导入 Neo4j

    请求体: {"yaml": "<YAML字符串>"}
    """
    yaml_content = data.yaml
    if not yaml_content or not yaml_content.strip():
        raise HTTPException(400, "YAML 内容不能为空")

    # 1. 校验 YAML 语法和字段
    from backend.core.agentic_qa.graph_importer import load_mapping as validate_mapping
    import yaml as _yaml
    from backend.core.agentic_qa.config import settings

    try:
        mapping = _yaml.safe_load(yaml_content)
    except _yaml.YAMLError as e:
        raise HTTPException(400, f"YAML 语法错误: {e}")

    if not isinstance(mapping, dict):
        raise HTTPException(400, "YAML 内容必须是字典/映射格式")

    try:
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
            tmp.write(yaml_content)
            tmp_path = tmp.name
        try:
            validate_mapping(tmp_path)
        finally:
            os.unlink(tmp_path)
    except ValueError as e:
        raise HTTPException(400, f"映射配置校验失败: {e}")

    # 2. 写入正式的映射文件
    try:
        with open(settings.graph_mapping_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)
    except Exception as e:
        raise HTTPException(500, f"写入映射文件失败: {e}")

    # 3. 导入 Neo4j
    from backend.core.agentic_qa.graph_client import get_graph_client
    from backend.core.agentic_qa.graph_importer import import_to_neo4j
    from backend.services.agentic_qa.db.mysql import db

    client = get_graph_client()
    if not client.is_available():
        raise HTTPException(503, "Neo4j 不可用，YAML 已保存但未能导入图谱")

    try:
        result = import_to_neo4j(client, db, mapping)
        return {
            "success": result.get("success", False),
            "nodes_created": result.get("nodes_created", 0),
            "relationships_created": result.get("relationships_created", 0),
            "manual_nodes": result.get("manual_nodes", 0),
            "manual_relationships": result.get("manual_relationships", 0),
            "errors": result.get("errors", []),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"图谱导入失败（YAML已保存）: {e}",
            "nodes_created": 0,
            "relationships_created": 0,
            "manual_nodes": 0,
            "manual_relationships": 0,
            "errors": [str(e)],
        }


# ======== AI批量生成SQL问答训练对 ========


class BatchGenerateRequest(BaseModel):
    theme: str
    table_names: List[str]
    count: int = 100
    schema_supplement: Optional[str] = ""
    example_sql: Optional[str] = ""


class BatchDraftApproveRequest(BaseModel):
    draft_ids: List[str]


class BatchDraftDeleteRequest(BaseModel):
    draft_ids: List[str]


class BatchDraftUpdateRequest(BaseModel):
    question: str
    sql: str
    alt_questions: Optional[List[str]] = None
    theme: Optional[str] = None


@router.post("/batch-generate")
async def start_batch_generation(req: BatchGenerateRequest):
    """启动AI批量生成任务"""
    # 参数校验
    theme = (req.theme or "").strip()
    if not theme or len(theme) > 50:
        raise HTTPException(400, "主题不能为空且不超过50字符")

    table_names = [t.strip() for t in req.table_names if t.strip()]
    if not table_names:
        raise HTTPException(400, "请至少选择一张表")

    count = req.count
    if count < 10 or count > 500:
        raise HTTPException(400, "生成数量需在10-500之间")

    # 验证表存在
    try:
        all_tables = db.execute_query("SHOW TABLES")
        existing = {list(row.values())[0] for row in all_tables}
        for t in table_names:
            if t not in existing:
                raise HTTPException(400, f"表 '{t}' 不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[batch-generate] table validation failed: {e}")

    schema_supp = (req.schema_supplement or "")[:5000]
    example_sql = (req.example_sql or "")[:10000]

    generator = get_batch_generator()
    job_id = generator.create_job(
        theme=theme,
        table_names=table_names,
        count=count,
        schema_supplement=schema_supp,
        example_sql=example_sql,
    )

    # 后台异步执行
    asyncio.create_task(generator.run_job(job_id))

    return {"success": True, "job_id": job_id, "message": f"已启动批量生成任务，目标 {count} 条"}


@router.get("/batch-generate/status/{job_id}")
async def get_batch_generation_status(job_id: str):
    """获取批量生成任务的进度"""
    generator = get_batch_generator()
    return generator.get_job_status(job_id)


@router.get("/batch-drafts/themes")
async def list_batch_draft_themes():
    """获取所有有待审核草稿的主题列表"""
    generator = get_batch_generator()
    themes = generator.list_themes()
    return {"success": True, "themes": themes}


@router.get("/batch-drafts")
async def list_batch_drafts(
    theme: str = Query(..., description="主题名称"),
    status: str = Query("pending", description="草稿状态"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """按主题分页查询草稿"""
    generator = get_batch_generator()
    result = generator.list_drafts(theme=theme, status=status, page=page, page_size=page_size)
    return {"success": True, **result}


@router.post("/batch-drafts/approve")
async def approve_batch_drafts(req: BatchDraftApproveRequest):
    """批量通过草稿 → 写入主记忆库"""
    if not req.draft_ids:
        raise HTTPException(400, "draft_ids 不能为空")
    generator = get_batch_generator()
    result = generator.approve_drafts(req.draft_ids)
    return {"success": True, **result}


@router.put("/batch-drafts/{draft_id}")
async def update_batch_draft(draft_id: str, req: BatchDraftUpdateRequest):
    """编辑单条草稿"""
    question = (req.question or "").strip()
    sql_text = (req.sql or "").strip()
    if not question or not sql_text:
        raise HTTPException(400, "question 和 sql 不能为空")
    generator = get_batch_generator()
    ok = generator.update_draft(draft_id, question, sql_text, req.alt_questions, theme=req.theme)
    if not ok:
        raise HTTPException(404, "草稿不存在")
    return {"success": True, "message": "已更新"}


@router.post("/batch-drafts/delete")
async def delete_batch_drafts(req: BatchDraftDeleteRequest):
    """批量删除草稿（软删除）"""
    if not req.draft_ids:
        raise HTTPException(400, "draft_ids 不能为空")
    generator = get_batch_generator()
    result = generator.delete_drafts(req.draft_ids)
    return {"success": True, **result}
