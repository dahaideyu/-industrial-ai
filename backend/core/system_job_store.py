# cython: annotation_typing=False, infer_types=False, language_level=3
"""system_jobs（JOB_CATALOG 调度任务）的表驱动配置 + 运行记录。

两件事：
1) cron/enabled 存 `system_job_config`（UI 可改；首次以 env `*_CRON` 为初值播种，之后表为准）。
2) 每次运行(手动/定时)复用现成 `analysis_job_run`(PostgresDB.start_job/end_job) 落
   status/耗时/result_summary/error_message —— **不新建运行表**；与 device_warning 的
   analysis 任务靠 job_name 命名空间共存。

设计：懒导入 `PostgresDB`（避免 core→device_warning 顶层依赖）；每个操作自开短连接、
不在长任务期间持连；记录一律 best-effort，绝不因记录失败阻断任务本身。
"""

import os
import json
import logging
import traceback
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_run_tables_ready = False


def _db():
    """打开 PostgresDB（懒导入）。连接失败返回 None。"""
    try:
        try:
            from modules.device_warning.ai_analysis.postgres_loader import PostgresDB
        except ImportError:
            from backend.modules.device_warning.ai_analysis.postgres_loader import PostgresDB
    except Exception as e:
        logger.error(f"[system_job_store] 导入 PostgresDB 失败: {e}")
        return None
    db = PostgresDB()
    if not db.connect_with_fallback():
        logger.error("[system_job_store] 数据库连接失败")
        return None
    return db


def _ensure_run_tables(db) -> None:
    """确保 analysis_job_*（运行记录）存在（每进程一次）。"""
    global _run_tables_ready
    if _run_tables_ready:
        return
    try:
        db.create_job_tables()
        _run_tables_ready = True
    except Exception as e:
        logger.warning(f"[system_job_store] create_job_tables: {e}")


def _ensure_config_table(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS system_job_config (
            job_id     VARCHAR(64) PRIMARY KEY,
            cron       VARCHAR(64),
            enabled    BOOLEAN     DEFAULT TRUE,
            updated_at TIMESTAMP   DEFAULT now(),
            updated_by VARCHAR(128)
        )
    """)


# ═══════════════════════════════════════════════════════
# 配置（cron / enabled）
# ═══════════════════════════════════════════════════════

def ensure(catalog: Optional[List[Dict[str, str]]] = None) -> bool:
    """建运行记录表 + system_job_config，并按目录首次播种。幂等、best-effort。"""
    db = _db()
    if db is None:
        return False
    try:
        _ensure_run_tables(db)
        _ensure_config_table(db)
        if catalog:
            _seed(db, catalog)
        return True
    finally:
        db.close()


def _seed(db, catalog: List[Dict[str, str]]) -> None:
    """首次把每个目录任务以当前 env cron 为初值写入（已存在则不动，迁移现有配置不丢）。"""
    for c in catalog:
        env_cron = os.getenv(c.get("cron_env", ""), "").strip()
        db.execute("""
            INSERT INTO system_job_config (job_id, cron, enabled, updated_by)
            VALUES (%s, %s, %s, 'seed')
            ON CONFLICT (job_id) DO NOTHING
        """, (c["id"], env_cron or None, bool(env_cron)))


def upsert_config(job_id: str, cron: Optional[str], enabled: bool,
                  updated_by: Optional[str] = None) -> bool:
    db = _db()
    if db is None:
        return False
    try:
        _ensure_config_table(db)
        return db.execute("""
            INSERT INTO system_job_config (job_id, cron, enabled, updated_at, updated_by)
            VALUES (%s, %s, %s, now(), %s)
            ON CONFLICT (job_id) DO UPDATE SET
              cron=EXCLUDED.cron, enabled=EXCLUDED.enabled,
              updated_at=now(), updated_by=EXCLUDED.updated_by
        """, (job_id, (cron or "").strip() or None, bool(enabled), updated_by))
    finally:
        db.close()


def get_configs() -> Dict[str, Dict[str, Any]]:
    db = _db()
    if db is None:
        return {}
    try:
        _ensure_config_table(db)
        df = db.query("SELECT job_id, cron, enabled, updated_at, updated_by FROM system_job_config")
        out: Dict[str, Dict[str, Any]] = {}
        if df is not None and not df.empty:
            for r in df.to_dict(orient="records"):
                out[r["job_id"]] = {
                    "cron": _clean(r.get("cron")),
                    "enabled": bool(r.get("enabled")),
                    "updated_at": _clean(r.get("updated_at"), as_str=True),
                    "updated_by": _clean(r.get("updated_by")),
                }
        return out
    finally:
        db.close()


def get_config(job_id: str) -> Optional[Dict[str, Any]]:
    return get_configs().get(job_id)


# ═══════════════════════════════════════════════════════
# 运行记录（复用 analysis_job_run）
# ═══════════════════════════════════════════════════════

def run_and_record(job_id: str, runner: Callable[[], Any]) -> Any:
    """跑 runner 并把结果/异常记入 analysis_job_run。记录 best-effort，绝不因记录失败阻断任务。"""
    run_id = _start(job_id)
    try:
        result = runner()
        _end(run_id, "success", result_summary=_json_safe(result))
        return result
    except Exception as e:
        err = f"{e}\n{traceback.format_exc()}"
        _end(run_id, "failed", error_message=err[:8000])
        raise


def _start(job_id: str) -> Optional[int]:
    db = _db()
    if db is None:
        return None
    try:
        _ensure_run_tables(db)
        return db.start_job(job_id)
    except Exception as e:
        logger.warning(f"[system_job_store] start_job 失败: {e}")
        return None
    finally:
        db.close()


def _end(run_id: Optional[int], status: str, result_summary=None, error_message=None) -> None:
    if run_id is None:
        return
    db = _db()
    if db is None:
        return
    try:
        db.end_job(run_id, status=status, result_summary=result_summary,
                   error_message=error_message)
    except Exception as e:
        logger.warning(f"[system_job_store] end_job 失败: {e}")
    finally:
        db.close()


def latest_runs() -> Dict[str, Dict[str, Any]]:
    """每个 job 最近一次运行（供 GET /system/jobs 合并显示）。"""
    db = _db()
    if db is None:
        return {}
    try:
        _ensure_run_tables(db)
        df = db.get_latest_run_per_job()
        out: Dict[str, Dict[str, Any]] = {}
        if df is not None and not df.empty:
            for r in df.to_dict(orient="records"):
                out[r["job_name"]] = _run_row(r)
        return out
    finally:
        db.close()


def job_runs(job_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """某 job 最近 N 次运行历史。"""
    db = _db()
    if db is None:
        return []
    try:
        _ensure_run_tables(db)
        df = db.get_job_status(job_id, limit=limit)
        if df is None or df.empty:
            return []
        return [_run_row(r) for r in df.to_dict(orient="records")]
    finally:
        db.close()


# ── 小工具 ──

def _clean(v, as_str: bool = False):
    """NaN/NaT → None；as_str 时非空转字符串。"""
    if v is None:
        return None
    if isinstance(v, float) and v != v:   # NaN
        return None
    return str(v) if as_str else v


def _run_row(r: Dict[str, Any]) -> Dict[str, Any]:
    dur = r.get("duration_seconds")
    return {
        "id": int(r["id"]) if r.get("id") is not None else None,
        "status": _clean(r.get("status")),
        "start_time": _clean(r.get("start_time"), as_str=True),
        "end_time": _clean(r.get("end_time"), as_str=True),
        "duration_seconds": int(dur) if dur is not None and dur == dur else None,
        "error_message": _clean(r.get("error_message")),
    }


def _json_safe(obj):
    """把 runner 返回值转成可 JSON 序列化的值（日期/Decimal 等 → str）；end_job 会再 json.dumps。"""
    if obj is None:
        return None
    try:
        return json.loads(json.dumps(obj, default=str, ensure_ascii=False))
    except Exception:
        return {"result": str(obj)}
