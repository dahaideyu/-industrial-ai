# cython: annotation_typing=False, infer_types=False, language_level=3
"""设备参数 趋势漂移 预计算/持久化层。

设计：算一次、存可叠加统计、之后只读。
  - device_param_daily_stats  可叠加汇总底表（设备×参数×阶段×天）
  - device_param_trend_alert  漂移预警快照（"逐渐变化值"落地处）
  - device_param_drift_config 盯哪些 metric + 阈值（按设备 JSONB）

关键正确性约束：中位数/百分位/方差不能由"日级结果再平均"得到。底表存可叠加量
cnt/sum_val/sum_sq/vmin/vmax —— 任意 N 天的均值、方差/标准差、极值在读取时精确
重算；每日 median/MAD 仅当天展示用，跨天汇总为近似（rollup 中标注 median_approx）。

metric 列既可是真实 p_name（参数值统计，如温度），也可是合成键 'stage_dur_min'
（阶段时长统计 → 覆盖"时间"漂移）。stage 列：NULL=整天/全部，具体码=该阶段。
"""

import json
import math
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from psycopg2.extras import RealDictCursor, execute_values

from . import trend_drift as td
from .stage_analysis import _attach, _build_segments, _fetch_long, detect_stage_param

# 阶段时长统计的合成 metric 名（覆盖"时间"漂移）
STAGE_DUR_METRIC = "stage_dur_min"


# ═══════════════════════════════════════════════════════
# 建表
# ═══════════════════════════════════════════════════════

def ensure_tables(conn) -> None:
    """建三表 + 索引（幂等）。沿用项目内联 CREATE TABLE IF NOT EXISTS 模式。"""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_param_daily_stats (
                device_code  VARCHAR(64)  NOT NULL,
                metric       VARCHAR(128) NOT NULL,
                stat_date    DATE         NOT NULL,
                stage        SMALLINT,
                running_only BOOLEAN      NOT NULL DEFAULT TRUE,
                cnt          BIGINT       NOT NULL,
                sum_val      DOUBLE PRECISION,
                sum_sq       DOUBLE PRECISION,
                vmin         DOUBLE PRECISION,
                vmax         DOUBLE PRECISION,
                mean         DOUBLE PRECISION,
                std          DOUBLE PRECISION,
                median       DOUBLE PRECISION,
                p25          DOUBLE PRECISION,
                p75          DOUBLE PRECISION,
                mad          DOUBLE PRECISION,
                first_val    DOUBLE PRECISION,
                last_val     DOUBLE PRECISION,
                updated_at   TIMESTAMPTZ  DEFAULT now()
            )
        """)
        # stage 可空，用表达式唯一索引实现 NULL 唯一性（COALESCE(stage,-1)）
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_device_param_daily_stats
            ON device_param_daily_stats
               (device_code, metric, stat_date, (COALESCE(stage, -1)), running_only)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS ix_device_param_daily_stats_lookup
            ON device_param_daily_stats (device_code, metric, stat_date)
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_param_trend_alert (
                device_code     VARCHAR(64)  NOT NULL,
                metric          VARCHAR(128) NOT NULL,
                stage           SMALLINT,
                eval_date       DATE         NOT NULL,
                baseline_days   SMALLINT     NOT NULL,
                running_only    BOOLEAN      NOT NULL DEFAULT TRUE,
                display_name    VARCHAR(256),
                unit            VARCHAR(32),
                baseline_median DOUBLE PRECISION,
                baseline_mad    DOUBLE PRECISION,
                recent_median   DOUBLE PRECISION,
                recent_n        SMALLINT,
                change_pct      DOUBLE PRECISION,
                robust_z        DOUBLE PRECISION,
                mk_trend        VARCHAR(8),
                mk_p            DOUBLE PRECISION,
                sen_slope       DOUBLE PRECISION,
                direction       VARCHAR(8),
                severity        VARCHAR(12),
                sample_days     SMALLINT,
                note            TEXT,
                updated_at      TIMESTAMPTZ  DEFAULT now()
            )
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_device_param_trend_alert
            ON device_param_trend_alert
               (device_code, metric, (COALESCE(stage, -1)), eval_date, baseline_days, running_only)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS ix_device_param_trend_alert_lookup
            ON device_param_trend_alert (device_code, eval_date, severity)
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_param_drift_config (
                device_code VARCHAR(64) PRIMARY KEY,
                config      JSONB NOT NULL,
                updated_at  TIMESTAMP DEFAULT now(),
                updated_by  VARCHAR(128)
            )
        """)
    conn.commit()


# ═══════════════════════════════════════════════════════
# 日级统计计算
# ═══════════════════════════════════════════════════════

def _stats_from_series(times: np.ndarray, vals: np.ndarray) -> Dict[str, float]:
    """从（时间, 数值）算一条统计行的所有列。vals 须已为有限值。

    cnt/sum_val/sum_sq 可叠加；median/p25/p75/mad 仅当天用；first/last 按时间序。
    """
    order = np.argsort(times, kind="stable")
    v = vals[order].astype(float)
    cnt = int(v.size)
    s = float(v.sum())
    ssq = float(np.dot(v, v))
    mean = s / cnt
    var = max(ssq / cnt - mean * mean, 0.0)
    med = float(np.median(v))
    return {
        "cnt": cnt,
        "sum_val": s,
        "sum_sq": ssq,
        "vmin": float(v.min()),
        "vmax": float(v.max()),
        "mean": mean,
        "std": math.sqrt(var),
        "median": med,
        "p25": float(np.percentile(v, 25)),
        "p75": float(np.percentile(v, 75)),
        "mad": float(np.median(np.abs(v - med))),
        "first_val": float(v[0]),
        "last_val": float(v[-1]),
    }


def _running_mask(times: pd.Series, intervals: List[Tuple[datetime, datetime]]) -> pd.Series:
    """times 落在任一运行区间内为 True。无区间时全 True（回退保留全部，同离线脚本）。"""
    if not intervals:
        return pd.Series(True, index=times.index)
    mask = pd.Series(False, index=times.index)
    for s, e in intervals:
        mask |= (times >= s) & (times < e)
    return mask


def _load_running_intervals(db, device_code: str, day0: datetime, day1: datetime
                            ) -> List[Tuple[datetime, datetime]]:
    """取该天运行时段为 [(start,end),...]。无状态信息返回 []（调用方回退保留全部）。"""
    device_id = db.get_device_id_by_code(device_code)
    status_code = db.get_running_status_code()
    if device_id is None or status_code is None:
        return []
    periods = db.get_running_periods(device_id, status_code, day0, day1)
    out: List[Tuple[datetime, datetime]] = []
    for p in periods:
        s = p.get("start_time")
        e = p.get("end_time")
        if isinstance(s, str):
            s = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        if isinstance(e, str):
            e = datetime.strptime(e, "%Y-%m-%d %H:%M:%S")
        out.append((s or day0, e or day1))
    return out


def _running_sql_filter(intervals: List[Tuple[datetime, datetime]],
                        running_only: bool) -> Tuple[str, List[Any]]:
    """构造运行时段 SQL 片段。仅运行口径且有区间时返回 AND(...OR...)，否则不过滤
    （无区间=无状态信息时回退保留全部，与 _running_mask 一致）。"""
    if not running_only or not intervals:
        return "", []
    parts, params = [], []
    for s, e in intervals:
        parts.append("(a.point_time >= %s AND a.point_time < %s)")
        params.extend([s, e])
    return " AND (" + " OR ".join(parts) + ")", params


def _whole_day_sql(db, device_code: str, day: date, day0: datetime, day1: datetime,
                   running_only: bool, intervals: List[Tuple[datetime, datetime]]
                   ) -> List[Dict[str, Any]]:
    """整天值统计(stage=NULL)纯 SQL 聚合：单次 MATERIALIZED 提取(避免 LATERAL 重算)
    + 服务端 GROUP BY，免把整日所有点位拉进 pandas。供无阶段参数的设备提速。

    可叠加量与 pandas 路径同口径：std 用 STDDEV_POP(总体)，与 sum_sq/cnt-mean² 一致。
    """
    val_expr = "COALESCE(pt.pv, a.point_value::text)"
    cast_expr = ("CASE WHEN {} ~ '^-?[0-9]+(\\.[0-9]*)?$' "
                 "THEN {}::double precision ELSE NULL END").format(val_expr, val_expr)
    run_frag, run_params = _running_sql_filter(intervals, running_only)
    sql = """
        WITH vals AS MATERIALIZED (
            SELECT a.point_id AS p_name, a.point_time AS t, {} AS v
            FROM device_alarm_info a
            LEFT JOIN LATERAL (
                SELECT pts.elem->>'point_value' AS pv
                FROM jsonb_array_elements(a.raw_json->'devices') dev
                CROSS JOIN jsonb_array_elements(dev->'points') AS pts(elem)
                WHERE pts.elem->>'point_id' = a.point_id
                LIMIT 1
            ) pt ON true
            WHERE a.device_id = %s AND a.point_time >= %s AND a.point_time < %s{}
        ),
        clean AS (SELECT p_name, t, v FROM vals WHERE v IS NOT NULL),
        agg AS (
            SELECT p_name, COUNT(*) AS cnt, SUM(v) AS sum_val, SUM(v*v) AS sum_sq,
                   MIN(v) AS vmin, MAX(v) AS vmax, AVG(v) AS mean,
                   COALESCE(STDDEV_POP(v), 0) AS std,
                   percentile_cont(0.5)  WITHIN GROUP (ORDER BY v) AS median,
                   percentile_cont(0.25) WITHIN GROUP (ORDER BY v) AS p25,
                   percentile_cont(0.75) WITHIN GROUP (ORDER BY v) AS p75
            FROM clean GROUP BY p_name
        ),
        firsts AS (SELECT DISTINCT ON (p_name) p_name, v AS first_val
                   FROM clean ORDER BY p_name, t ASC),
        lasts  AS (SELECT DISTINCT ON (p_name) p_name, v AS last_val
                   FROM clean ORDER BY p_name, t DESC),
        madg AS (
            SELECT c.p_name,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(c.v - a.median)) AS mad
            FROM clean c JOIN agg a USING (p_name) GROUP BY c.p_name
        )
        SELECT agg.p_name, agg.cnt, agg.sum_val, agg.sum_sq, agg.vmin, agg.vmax,
               agg.mean, agg.std, agg.median, agg.p25, agg.p75,
               madg.mad, firsts.first_val, lasts.last_val
        FROM agg
        LEFT JOIN firsts USING (p_name)
        LEFT JOIN lasts  USING (p_name)
        LEFT JOIN madg   USING (p_name)
    """.format(cast_expr, run_frag)
    params = [device_code, day0, day1] + run_params
    out: List[Dict[str, Any]] = []
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, tuple(params))
        for r in cur.fetchall():
            def _f(k):
                return float(r[k]) if r[k] is not None else None
            out.append({
                "device_code": device_code, "metric": r["p_name"], "stat_date": day,
                "stage": None, "running_only": running_only,
                "cnt": int(r["cnt"]), "sum_val": _f("sum_val"), "sum_sq": _f("sum_sq"),
                "vmin": _f("vmin"), "vmax": _f("vmax"), "mean": _f("mean"),
                "std": _f("std"), "median": _f("median"),
                "p25": _f("p25"), "p75": _f("p75"), "mad": _f("mad"),
                "first_val": _f("first_val"), "last_val": _f("last_val"),
            })
    return out


def _select_continuous_params(db, device_code: str, conn,
                              whole_day_rows: List[Dict[str, Any]],
                              stage_param: Optional[str]) -> List[str]:
    """挑"连续/数值类"参数做分阶段值漂移（开关/状态/计数器在阶段内漂移无意义且拉爆算量）。

    优先已确认画像(ptype∈continuous/setpoint)；无画像时从整天统计启发式回退
    （cnt 足够 + std>0 + 值域>3，剔除阶段参数本身）。返回 p_name 列表。
    画像确认后选取最精确——回退仅为兜底，可能误纳少量计数器。
    """
    try:
        from . import param_profile
        confirmed = param_profile.get_confirmed_map(conn, device_code)
        cont = [p for p, pr in confirmed.items()
                if pr.get("ptype") in ("continuous", "setpoint")]
        if cont:
            return [p for p in cont if p != stage_param]
    except Exception as e:
        print(f"[stats_store] 读画像选连续参数失败，回退启发式: {e}")

    out: List[str] = []
    for r in whole_day_rows:
        m = r.get("metric")
        if m == stage_param or m == STAGE_DUR_METRIC:
            continue
        cnt = r.get("cnt") or 0
        std, vmin, vmax = r.get("std"), r.get("vmin"), r.get("vmax")
        if (cnt >= 20 and std is not None and std > 1e-9
                and vmin is not None and vmax is not None and (vmax - vmin) > 3):
            out.append(m)
    return out


def compute_daily_stats(db, device_code: str, day: date,
                        running_only: bool = True) -> List[Dict[str, Any]]:
    """算某设备某天的统计行：
      1) 整天值统计(stage=NULL)：_whole_day_sql 服务端聚合，对所有参数一视同仁、快。
      2) 阶段时长(stage_dur_min)：只拉阶段参数，_build_segments 切段后按阶段聚时长。
      3) 分阶段·单参数值统计(metric=p_name, stage=码)：**仅连续/数值类参数**，把读数按
         阶段码归并后逐阶段算统计，供"每个参数分阶段 7 天漂移"用。

    (2)(3) 共用同一次段切分；连续参数与阶段参数合并为一次 _fetch_long 避免多轮拉数。
    非连续参数不分阶段（省算量）。返回待 upsert 的行 dict 列表。
    """
    day0 = datetime(day.year, day.month, day.day)
    day1 = day0 + timedelta(days=1)
    intervals = _load_running_intervals(db, device_code, day0, day1)

    # 1) 整天值统计(stage=NULL)：服务端 SQL，快
    out = _whole_day_sql(db, device_code, day, day0, day1, running_only, intervals)

    # 2/3) 阶段相关：能识别阶段参数才算
    name_map = db.get_point_names(device_code)
    stage_param = detect_stage_param(name_map, conn=db.conn, device_code=device_code)
    if not stage_param:
        return out

    cont_params = _select_continuous_params(db, device_code, db.conn, out, stage_param)
    fetch_points = [stage_param] + [p for p in cont_params if p != stage_param]
    long_df = _fetch_long(db.conn, device_code, day0, day1, fetch_points)
    if long_df.empty:
        return out
    long_df = long_df[long_df["gather_time"] < day1]

    stage_long = (long_df[long_df["p_name"] == stage_param]
                  [["gather_time", "p_value"]].sort_values("gather_time"))
    seg = _build_segments(stage_long)
    if seg.empty:
        return out

    # 2) 阶段时长(stage_dur_min)
    for st, g in seg.groupby("stage"):
        out.append({"device_code": device_code, "metric": STAGE_DUR_METRIC,
                    "stat_date": day, "stage": int(st),
                    "running_only": running_only,
                    **_stats_from_series(g["t_start"].astype("int64").values,
                                         g["dur_min"].astype(float).values)})

    # 3) 分阶段·单参数 值统计（仅连续参数）
    for pname in cont_params:
        pg = long_df[long_df["p_name"] == pname][["gather_time", "p_value"]]
        if pg.empty:
            continue
        attached = _attach(pg, seg)   # merge_asof 贴阶段码，'v'=数值列
        if attached.empty:
            continue
        for st, sg in attached.groupby("stage"):
            v = sg["v"].astype(float).values
            if v.size == 0:
                continue
            out.append({"device_code": device_code, "metric": pname,
                        "stat_date": day, "stage": int(st),
                        "running_only": running_only,
                        **_stats_from_series(
                            sg["gather_time"].astype("int64").values, v)})
    return out


_UPSERT_COLS = ["device_code", "metric", "stat_date", "stage", "running_only",
                "cnt", "sum_val", "sum_sq", "vmin", "vmax", "mean", "std",
                "median", "p25", "p75", "mad", "first_val", "last_val"]


def upsert_daily_stats(conn, rows: List[Dict[str, Any]]) -> int:
    """批量 upsert（幂等，重跑同日覆盖）。返回写入行数。"""
    if not rows:
        return 0
    values = [[r.get(c) for c in _UPSERT_COLS] for r in rows]
    set_clause = ", ".join(
        "{}=EXCLUDED.{}".format(c, c) for c in _UPSERT_COLS[5:]) + ", updated_at=now()"
    sql = """
        INSERT INTO device_param_daily_stats ({})
        VALUES %s
        ON CONFLICT (device_code, metric, stat_date, (COALESCE(stage, -1)), running_only)
        DO UPDATE SET {}
    """.format(", ".join(_UPSERT_COLS), set_clause)
    with conn.cursor() as cur:
        execute_values(cur, sql, values)
    conn.commit()
    return len(rows)


# ═══════════════════════════════════════════════════════
# 只读汇总（任意天数，可叠加量精确重算）
# ═══════════════════════════════════════════════════════

def rollup(conn, device_code: str, metric: str, start: date, end: date,
           stage: Optional[int] = None, running_only: bool = True) -> Dict[str, Any]:
    """读底表汇总 [start,end] 的统计。均值/方差/极值精确；median 为日中位近似。"""
    stage_key = -1 if stage is None else int(stage)
    sql = """
        SELECT SUM(cnt) AS cnt, SUM(sum_val) AS s, SUM(sum_sq) AS ssq,
               MIN(vmin) AS vmin, MAX(vmax) AS vmax,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY median) AS median_approx,
               COUNT(*) AS n_days,
               MIN(stat_date) AS first_day, MAX(stat_date) AS last_day
        FROM device_param_daily_stats
        WHERE device_code=%s AND metric=%s
          AND stat_date BETWEEN %s AND %s
          AND running_only=%s
          AND COALESCE(stage, -1) = %s
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (device_code, metric, start, end, running_only, stage_key))
        r = cur.fetchone()

    if not r or not r["cnt"]:
        return {"device_code": device_code, "metric": metric, "stage": stage,
                "n_days": 0, "cnt": 0, "msg": "无数据"}

    cnt = float(r["cnt"]); s = float(r["s"]); ssq = float(r["ssq"])
    mean = s / cnt
    var = max(ssq / cnt - mean * mean, 0.0)
    return {
        "device_code": device_code, "metric": metric, "stage": stage,
        "running_only": running_only,
        "start": str(r["first_day"]), "end": str(r["last_day"]),
        "n_days": int(r["n_days"]), "cnt": int(cnt),
        "mean": round(mean, 4),
        "variance": round(var, 4),            # 平方差（总体口径，精确）
        "std": round(math.sqrt(var), 4),
        "min": round(float(r["vmin"]), 4),
        "max": round(float(r["vmax"]), 4),
        "median_approx": round(float(r["median_approx"]), 4)
        if r["median_approx"] is not None else None,
        "median_is_approx": True,             # 跨天中位为日中位近似，非精确
    }


# ═══════════════════════════════════════════════════════
# 漂移预警配置（盯哪些 metric + 阈值）
# ═══════════════════════════════════════════════════════

def load_drift_config(conn, db, device_code: str) -> Tuple[List[Dict[str, Any]], str]:
    """返回 (watch_list, source)。watch_list=[{metric, stage, display_name, unit, cfg}]。

    优先读 device_param_drift_config；无则按数据派生默认：温度类参数(中文名含'温',
    整天) + 各阶段 stage_dur_min。source ∈ {'db','default'}。
    """
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT config FROM device_param_drift_config WHERE device_code=%s",
                        (device_code,))
            row = cur.fetchone()
        if row and row["config"]:
            name_map = db.get_point_names(device_code)
            unit_map = db.get_point_units(device_code)
            watch = []
            for item in row["config"]:
                if not item.get("enabled", True):
                    continue
                m = item["metric"]
                cfg = {k: item[k] for k in td.DEFAULT_THRESHOLDS if k in item}
                watch.append({
                    "metric": m,
                    "stage": item.get("stage"),
                    "display_name": (STAGE_DUR_METRIC if m == STAGE_DUR_METRIC
                                     else name_map.get(m, m)),
                    "unit": "min" if m == STAGE_DUR_METRIC else unit_map.get(m, ""),
                    "cfg": {**td.DEFAULT_THRESHOLDS, **cfg},
                })
            if watch:
                return watch, "db"
    except Exception as e:
        print(f"[stats_store] load_drift_config failed: {e}")

    return _default_watch_list(conn, db, device_code), "default"


def _default_watch_list(conn, db, device_code: str) -> List[Dict[str, Any]]:
    """默认盯参：优先已确认画像里 monitor=true 的参数；无画像时回退"中文名含'温'"。
    再加各阶段 stage_dur_min。从底表已有 metric 派生。"""
    name_map = db.get_point_names(device_code)
    unit_map = db.get_point_units(device_code)
    watch: List[Dict[str, Any]] = []

    # 已确认画像中要盯的参数（有则优先用，替代关键词硬编码）
    monitored = set()
    try:
        from . import param_profile
        monitored = {p for p, pr in param_profile.get_confirmed_map(conn, device_code).items()
                     if pr.get("monitor")}
    except Exception as e:
        print(f"[stats_store] 读画像盯参失败，回退关键词: {e}")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 值参数（整天）
        cur.execute("""
            SELECT DISTINCT metric FROM device_param_daily_stats
            WHERE device_code=%s AND stage IS NULL AND metric <> %s
        """, (device_code, STAGE_DUR_METRIC))
        for row in cur.fetchall():
            m = row["metric"]
            disp = name_map.get(m, m)
            use = (m in monitored) if monitored else ("温" in disp)
            if use:
                watch.append({"metric": m, "stage": None, "display_name": disp,
                              "unit": unit_map.get(m, ""),
                              "cfg": dict(td.DEFAULT_THRESHOLDS)})
        # 各阶段时长
        cur.execute("""
            SELECT DISTINCT stage FROM device_param_daily_stats
            WHERE device_code=%s AND metric=%s AND stage IS NOT NULL
            ORDER BY stage
        """, (device_code, STAGE_DUR_METRIC))
        for row in cur.fetchall():
            st = int(row["stage"])
            watch.append({"metric": STAGE_DUR_METRIC, "stage": st,
                          "display_name": f"阶段{st}时长", "unit": "min",
                          "cfg": dict(td.DEFAULT_THRESHOLDS)})
        # 分阶段·单参数值（compute_daily_stats 只为连续参数落这些行）→ 7 天滑动窗口
        cur.execute("""
            SELECT DISTINCT metric, stage FROM device_param_daily_stats
            WHERE device_code=%s AND stage IS NOT NULL AND metric <> %s
            ORDER BY metric, stage
        """, (device_code, STAGE_DUR_METRIC))
        for row in cur.fetchall():
            m, st = row["metric"], int(row["stage"])
            disp = name_map.get(m, m)
            watch.append({"metric": m, "stage": st,
                          "display_name": f"{disp}·阶段{st}",
                          "unit": unit_map.get(m, ""),
                          "cfg": dict(td.WINDOW_7D)})
    return watch


def save_drift_config(conn, device_code: str, config: List[dict],
                      user: Optional[str] = None) -> List[dict]:
    """保存界面编辑的盯参/阈值配置（按设备 JSONB）。沿用 stage 配置同款 upsert。"""
    ensure_tables(conn)
    cfg = []
    for item in config:
        if not item.get("metric"):
            continue
        clean = {"metric": item["metric"], "stage": item.get("stage"),
                 "enabled": item.get("enabled", True)}
        for k in td.DEFAULT_THRESHOLDS:
            if k in item and item[k] is not None:
                clean[k] = item[k]
        cfg.append(clean)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO device_param_drift_config (device_code, config, updated_at, updated_by)
            VALUES (%s, %s, now(), %s)
            ON CONFLICT (device_code)
            DO UPDATE SET config=EXCLUDED.config, updated_at=now(), updated_by=EXCLUDED.updated_by
        """, (device_code, json.dumps(cfg, ensure_ascii=False), user))
    conn.commit()
    return cfg


# ═══════════════════════════════════════════════════════
# 漂移预警计算（只读底表 → 写快照表）
# ═══════════════════════════════════════════════════════

def _fetch_daily_series(conn, device_code: str, metric: str, stage: Optional[int],
                        start: date, end: date, running_only: bool) -> pd.DataFrame:
    """取日级序列 [stat_date, median, mean, cnt]，按日升序。"""
    stage_key = -1 if stage is None else int(stage)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT stat_date, median, mean, cnt FROM device_param_daily_stats
            WHERE device_code=%s AND metric=%s
              AND COALESCE(stage,-1)=%s AND running_only=%s
              AND stat_date BETWEEN %s AND %s
            ORDER BY stat_date
        """, (device_code, metric, stage_key, running_only, start, end))
        rows = cur.fetchall()
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["stat_date", "median", "mean", "cnt"])


def daily_series(conn, device_code: str, metric: str, start: date, end: date,
                 stage: Optional[int] = None, running_only: bool = True
                 ) -> List[Dict[str, Any]]:
    """读日级序列(给前端画 sparkline / 带基线带趋势图)。按日升序 [{date,median,mean,cnt}]。"""
    df = _fetch_daily_series(conn, device_code, metric, stage, start, end, running_only)
    out: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        out.append({
            "date": str(r["stat_date"]),
            "median": float(r["median"]) if r["median"] is not None else None,
            "mean": float(r["mean"]) if r["mean"] is not None else None,
            "cnt": int(r["cnt"]) if r["cnt"] is not None else 0,
        })
    return out


def stats_overview(conn, db, device_code: str, start: date, end: date,
                   running_only: bool = True, recent_days: int = 3) -> List[Dict[str, Any]]:
    """窗口内**全部参数**的统计总览（即使无漂移也有内容）。

    一次查询取所有 metric(整天值参数 stage=NULL + 各阶段时长 stage_dur_min) 的日级行，
    Python 端：可叠加量精确算 均值/方差/标准差/极值；中位取日中位的中位(近似)；
    再内联算趋势(Mann-Kendall/Sen 斜率/基线vs近期/severity)。series 内嵌供前端画 sparkline
    （省去逐参数再请求）。按 严重度→|变化率| 排序，漂移的浮到最上面。
    """
    sql = """
        SELECT metric, stage, stat_date, cnt, sum_val, sum_sq, vmin, vmax, median
        FROM device_param_daily_stats
        WHERE device_code=%s AND stat_date BETWEEN %s AND %s AND running_only=%s
          AND (stage IS NULL OR metric=%s)
        ORDER BY metric, COALESCE(stage,-1), stat_date
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (device_code, start, end, running_only, STAGE_DUR_METRIC))
        rows = cur.fetchall()
    if not rows:
        return []

    name_map = db.get_point_names(device_code)
    unit_map = db.get_point_units(device_code)

    groups: Dict[Tuple[str, Any], List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["metric"], r["stage"]), []).append(r)

    out: List[Dict[str, Any]] = []
    for (metric, stage), recs in groups.items():
        cnt_tot = sum(int(x["cnt"]) for x in recs)
        if cnt_tot <= 0:
            continue
        s = sum(float(x["sum_val"]) for x in recs if x["sum_val"] is not None)
        ssq = sum(float(x["sum_sq"]) for x in recs if x["sum_sq"] is not None)
        mean = s / cnt_tot
        var = max(ssq / cnt_tot - mean * mean, 0.0)
        vmin = min(float(x["vmin"]) for x in recs if x["vmin"] is not None)
        vmax = max(float(x["vmax"]) for x in recs if x["vmax"] is not None)

        daily = [(x["stat_date"], float(x["median"])) for x in recs if x["median"] is not None]
        dates = [d for d, _ in daily]
        medians = [m for _, m in daily]
        n_days = len(medians)
        series = [{"date": str(d), "median": round(m, 4)} for d, m in daily]

        median_overall = float(np.median(medians)) if medians else None
        if medians:                       # 日间均差(各日中位偏离其均值的平均绝对差)
            dm = sum(medians) / len(medians)
            daily_mad = sum(abs(m - dm) for m in medians) / len(medians)
        else:
            daily_mad = None

        if n_days >= 2:
            days_axis = [(d - dates[0]).days for d in dates]
            mk = td.mann_kendall(medians)
            slope = td.sens_slope(days_axis, medians)
            if n_days > recent_days + 1:
                base_m, recent_m = medians[:-recent_days], medians[-recent_days:]
            else:
                base_m, recent_m = medians, medians[-1:]
            bstat = td.robust_stats(base_m)
            recent_med = float(np.median(recent_m))
            z = td.robust_z(recent_med, bstat["median"], bstat["scale"])
            cpct = td.change_pct(recent_med, bstat["median"])
            cls = td.classify_severity(cpct, z, mk["trend"])
            severity, direction = cls["severity"], cls["direction"]
            mk_trend, mk_p = mk["trend"], mk["p"]
        else:
            slope = z = cpct = mk_p = None
            severity, direction, mk_trend = "info", "flat", "none"

        is_dur = metric == STAGE_DUR_METRIC
        out.append({
            "metric": metric,
            "stage": int(stage) if stage is not None else None,
            "display_name": (f"阶段{int(stage)}时长" if is_dur else name_map.get(metric, metric)),
            "unit": "min" if is_dur else unit_map.get(metric, ""),
            "n_days": n_days, "cnt": cnt_tot,
            "mean": round(mean, 4),
            "median": round(median_overall, 4) if median_overall is not None else None,
            "min": round(vmin, 4), "max": round(vmax, 4),
            "variance": round(var, 4), "std": round(math.sqrt(var), 4),
            "daily_mad": round(daily_mad, 4) if daily_mad is not None else None,
            "change_pct": round(cpct, 3) if cpct is not None else None,
            "robust_z": round(z, 3) if z is not None else None,
            "sen_slope": round(slope, 5) if slope is not None else None,
            "mk_trend": mk_trend, "mk_p": round(mk_p, 5) if mk_p is not None else None,
            "direction": direction, "severity": severity,
            "series": series,
        })

    rank = {"critical": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (rank.get(r["severity"], 3),
                            -(abs(r["change_pct"]) if r["change_pct"] is not None else 0)))
    return out


def compute_trend_alerts(conn, db, device_code: str, eval_date: date,
                         running_only: bool = True) -> int:
    """对设备所有盯参算漂移并 upsert 快照表。返回写入条数。"""
    watch, _ = load_drift_config(conn, db, device_code)
    if not watch:
        return 0

    alert_rows: List[Dict[str, Any]] = []
    for w in watch:
        cfg = w["cfg"]
        baseline_days = int(cfg["baseline_days"])
        recent_days = int(cfg["recent_days"])
        min_base = int(cfg["min_base_days"])
        start = eval_date - timedelta(days=baseline_days)

        s = _fetch_daily_series(conn, device_code, w["metric"], w["stage"],
                                start, eval_date, running_only)
        s = s.dropna(subset=["median"])
        sample_days = len(s)

        base_row = {
            "device_code": device_code, "metric": w["metric"], "stage": w["stage"],
            "eval_date": eval_date, "baseline_days": baseline_days,
            "running_only": running_only,
            "display_name": w.get("display_name"), "unit": w.get("unit"),
            "sample_days": sample_days,
        }

        if sample_days < min_base:
            alert_rows.append({**base_row, "severity": "info", "note": "数据不足",
                               "baseline_median": None, "baseline_mad": None,
                               "recent_median": None, "recent_n": 0,
                               "change_pct": None, "robust_z": None,
                               "mk_trend": "none", "mk_p": None, "sen_slope": None,
                               "direction": "flat"})
            continue

        medians = s["median"].astype(float).tolist()
        # 时间轴用"距首日天数"，使 Sen 斜率单位=每天
        days_axis = [(d - s["stat_date"].iloc[0]).days for d in s["stat_date"]]

        # baseline vs recent 切分
        if sample_days > recent_days + 1:
            base_med = medians[:-recent_days]
            recent_med = medians[-recent_days:]
        else:
            base_med = medians
            recent_med = medians[-1:]
        bstat = td.robust_stats(base_med)
        recent_median = float(np.median(recent_med))

        z = td.robust_z(recent_median, bstat["median"], bstat["scale"])
        cpct = td.change_pct(recent_median, bstat["median"])
        mk = td.mann_kendall(medians)
        slope = td.sens_slope(days_axis, medians)
        cls = td.classify_severity(cpct, z, mk["trend"], cfg)

        note = None
        severity = cls["severity"]
        if td.detect_step_change(medians, bstat["scale"]):
            note = "疑似阶跃/配方切换"
            if severity == "critical":
                severity = "warning"

        alert_rows.append({**base_row,
                           "baseline_median": round(bstat["median"], 4),
                           "baseline_mad": round(bstat["mad"], 4),
                           "recent_median": round(recent_median, 4),
                           "recent_n": len(recent_med),
                           "change_pct": round(cpct, 3),
                           "robust_z": round(z, 3),
                           "mk_trend": mk["trend"], "mk_p": round(mk["p"], 5),
                           "sen_slope": round(slope, 5),
                           "direction": cls["direction"],
                           "severity": severity, "note": note})

    return _upsert_alerts(conn, alert_rows)


_ALERT_COLS = ["device_code", "metric", "stage", "eval_date", "baseline_days",
               "running_only", "display_name", "unit", "baseline_median",
               "baseline_mad", "recent_median", "recent_n", "change_pct",
               "robust_z", "mk_trend", "mk_p", "sen_slope", "direction",
               "severity", "sample_days", "note"]


def _upsert_alerts(conn, rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    values = [[r.get(c) for c in _ALERT_COLS] for r in rows]
    set_clause = ", ".join(
        "{}=EXCLUDED.{}".format(c, c) for c in _ALERT_COLS[6:]) + ", updated_at=now()"
    sql = """
        INSERT INTO device_param_trend_alert ({})
        VALUES %s
        ON CONFLICT (device_code, metric, (COALESCE(stage, -1)), eval_date,
                     baseline_days, running_only)
        DO UPDATE SET {}
    """.format(", ".join(_ALERT_COLS), set_clause)
    with conn.cursor() as cur:
        execute_values(cur, sql, values)
    conn.commit()
    return len(rows)


def read_trend_alerts(conn, device_code: str, eval_date: Optional[date] = None,
                      severity: Optional[str] = None,
                      baseline_days: Optional[int] = None) -> List[Dict[str, Any]]:
    """读快照表（页面/日报消费）。eval_date 缺省取该设备最新评估日。"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if eval_date is None:
            cur.execute("""SELECT MAX(eval_date) AS d FROM device_param_trend_alert
                           WHERE device_code=%s""", (device_code,))
            r = cur.fetchone()
            eval_date = r["d"] if r else None
        if eval_date is None:
            return []

        conds = ["device_code=%s", "eval_date=%s"]
        params: List[Any] = [device_code, eval_date]
        if severity:
            conds.append("severity=%s")
            params.append(severity)
        if baseline_days:
            conds.append("baseline_days=%s")
            params.append(baseline_days)
        cur.execute("""
            SELECT * FROM device_param_trend_alert
            WHERE {}
            ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1
                     ELSE 2 END, ABS(COALESCE(change_pct,0)) DESC
        """.format(" AND ".join(conds)), tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        if isinstance(r.get("eval_date"), (date, datetime)):
            r["eval_date"] = str(r["eval_date"])
        r.pop("updated_at", None)
    return rows
