# cython: annotation_typing=False, infer_types=False, language_level=3
"""班次分析结果的持久化。

为什么按班次存而不是按任意时间窗存：任意时间窗的组合是无穷的，缓存永远打不中；
班次是有限、离散、对齐现场作业的单位，**同一个班次的分析结果只需要算一次**。

缓存有效性由班次是否结束决定：
- 班次已结束 → 原始数据不会再变，结果永久有效，直接读库
- 班次进行中 → 结果只是当下快照，标 partial=TRUE，前端要显示计算时刻并允许刷新

这解决的是精益里的"重复搬运"：原来用户每切一次 Tab、每调一次时间范围，
同一份数据就要从库里重新拉一遍、重新算一遍。
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from psycopg2.extras import Json, RealDictCursor

from .shift import ShiftWindow

# 分析类型：与前端 4 个 Tab 对应（stage_recipe 是④阶段Tab里独立的"配方/周期排列/
# 跨周期对比"组件 StageAnalysis.vue，跟 TYPE_STAGE 的阶段CPK是两个不同的分析，
# 不能共用同一个 key，否则同一个班次/天的缓存行会互相覆盖）
TYPE_STATE = "state"        # ①状态&效率
TYPE_ENERGY = "energy"      # ②能耗
TYPE_KPI = "kpi"            # ③KPI
TYPE_STAGE = "stage"        # ④阶段CPK/公差/能耗逐段
TYPE_STAGE_RECIPE = "stage_recipe"  # ④阶段配方总览/周期排列/跨周期对比
ALL_TYPES = (TYPE_STATE, TYPE_ENERGY, TYPE_KPI, TYPE_STAGE, TYPE_STAGE_RECIPE)


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_param_shift_analysis (
                id            BIGSERIAL PRIMARY KEY,
                device_code   VARCHAR(64)  NOT NULL,
                shift_date    DATE         NOT NULL,
                shift_type    VARCHAR(8)   NOT NULL,
                analysis_type VARCHAR(24)  NOT NULL,
                pulse_param   VARCHAR(64)  NOT NULL DEFAULT '',
                result        JSONB        NOT NULL,
                partial       BOOLEAN      NOT NULL DEFAULT FALSE,
                computed_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
                CONSTRAINT uq_shift_analysis
                    UNIQUE (device_code, shift_date, shift_type, analysis_type, pulse_param)
            )
        """)
        # 常用查询：某设备某段时间的全部班次结果
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_shift_analysis_lookup
            ON device_param_shift_analysis (device_code, shift_date DESC, shift_type)
        """)
    conn.commit()


def load(conn, device_code: str, shift: ShiftWindow, analysis_type: str,
         pulse_param: str = "", allow_partial: bool = True) -> Optional[Dict[str, Any]]:
    """读一个班次某类分析的缓存结果。未命中返回 None。

    allow_partial=False 时，进行中班次存下的快照视为未命中（强制重算）。
    """
    ensure_table(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT result, partial, computed_at
            FROM device_param_shift_analysis
            WHERE device_code=%s AND shift_date=%s AND shift_type=%s
              AND analysis_type=%s AND pulse_param=%s
        """, (device_code, shift.shift_date, shift.shift_type, analysis_type, pulse_param or ""))
        row = cur.fetchone()
    if not row:
        return None
    if row["partial"] and not allow_partial:
        return None
    result = row["result"] or {}
    result["_cache"] = {
        "hit": True,
        "partial": row["partial"],
        "computed_at": row["computed_at"].strftime("%Y-%m-%d %H:%M:%S") if row["computed_at"] else None,
    }
    return result


def load_many(conn, device_code: str, shifts: List[ShiftWindow], analysis_type: str,
              pulse_param: str = "") -> Dict[str, Dict[str, Any]]:
    """批量读多个班次的同类结果，返回 {shift.key: result}。一次查询，不逐班次往返。"""
    if not shifts:
        return {}
    ensure_table(conn)
    pairs = [(s.shift_date, s.shift_type) for s in shifts]
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT shift_date, shift_type, result, partial, computed_at
            FROM device_param_shift_analysis
            WHERE device_code=%s AND analysis_type=%s AND pulse_param=%s
              AND (shift_date, shift_type) IN %s
        """, (device_code, analysis_type, pulse_param or "", tuple(pairs)))
        rows = cur.fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f"{r['shift_date']:%Y%m%d}-{r['shift_type']}"
        res = r["result"] or {}
        res["_cache"] = {
            "hit": True,
            "partial": r["partial"],
            "computed_at": r["computed_at"].strftime("%Y-%m-%d %H:%M:%S") if r["computed_at"] else None,
        }
        out[key] = res
    return out


def save(conn, device_code: str, shift: ShiftWindow, analysis_type: str,
         result: Dict[str, Any], pulse_param: str = "",
         partial: Optional[bool] = None, now: Optional[datetime] = None) -> None:
    """写入/覆盖一个班次的分析结果。

    partial 默认由班次是否结束推导：进行中的班次天然是 partial，
    因为后面还会有新数据进来，这份结果只是当下快照。
    """
    if partial is None:
        partial = not shift.is_closed(now)
    # 缓存元信息不入库，避免二次读取时嵌套累积
    clean = {k: v for k, v in (result or {}).items() if k != "_cache"}
    ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO device_param_shift_analysis
                (device_code, shift_date, shift_type, analysis_type, pulse_param, result, partial, computed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT ON CONSTRAINT uq_shift_analysis DO UPDATE SET
                result = EXCLUDED.result,
                partial = EXCLUDED.partial,
                computed_at = now()
        """, (device_code, shift.shift_date, shift.shift_type, analysis_type,
              pulse_param or "", Json(clean), partial))
    conn.commit()


def invalidate(conn, device_code: str, shift: Optional[ShiftWindow] = None,
               analysis_type: Optional[str] = None) -> int:
    """删除缓存（"重新分析"按钮走这里）。返回删除行数。"""
    ensure_table(conn)
    sql = "DELETE FROM device_param_shift_analysis WHERE device_code=%s"
    params: List[Any] = [device_code]
    if shift is not None:
        sql += " AND shift_date=%s AND shift_type=%s"
        params.extend([shift.shift_date, shift.shift_type])
    if analysis_type:
        sql += " AND analysis_type=%s"
        params.append(analysis_type)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        n = cur.rowcount
    conn.commit()
    return n
