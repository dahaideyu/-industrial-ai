# cython: annotation_typing=False, infer_types=False, language_level=3
"""Pillar 3 高级分析：RUL/触限 ETA、跨设备对标、故障前兆自学习。

全部读已建好的 device_param_daily_stats（可叠加统计）+ 参数画像 spec + 告警事件，
**参数无关**：靠画像/统计而非按 device_code/关键词硬编码。数据不足时返回空结构不报错。
"""

import math
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
from psycopg2.extras import RealDictCursor

from . import stats_store
from . import trend_drift as td
from . import param_profile

# 真正"报警"状态码（dev_device_status_record.status）
ALARM_STATUS = 2


# ═══════════════════════════════════════════════════════
# RUL / 触限 ETA
# ═══════════════════════════════════════════════════════

def rul_eta(conn, db, device_code: str, days: int = 60,
            max_eta_days: float = 365.0, running_only: bool = True) -> List[Dict[str, Any]]:
    """按 Sen 斜率把每个连续参数外推到画像上限/下限，估"还有几天触限"。

    仅对有显著单调趋势(Mann-Kendall)且斜率朝向某条限的参数给 ETA。
    """
    end = date.today()
    start = end - timedelta(days=days)
    profiles = {p["p_name"]: p for p in param_profile.load_profiles(conn, device_code)}
    out: List[Dict[str, Any]] = []

    for pn, prof in profiles.items():
        if prof.get("ptype") not in ("continuous", "setpoint"):
            continue
        bands = prof.get("bands") or {}
        hi = bands.get("spec_high") if bands.get("spec_high") is not None else bands.get("warn_high")
        lo = bands.get("spec_low") if bands.get("spec_low") is not None else bands.get("warn_low")
        if hi is None and lo is None:
            continue

        series = stats_store.daily_series(conn, device_code, pn, start, end,
                                          stage=None, running_only=running_only)
        med = [s["median"] for s in series if s["median"] is not None]
        if len(med) < 5:
            continue
        dates = [datetime.strptime(s["date"], "%Y-%m-%d").date()
                 for s in series if s["median"] is not None]
        axis = [(d - dates[0]).days for d in dates]
        mk = td.mann_kendall(med)
        slope = td.sens_slope(axis, med)           # 每天变化量
        current = med[-1]

        target = direction = None
        eta = None
        if slope > 1e-9 and hi is not None and current < hi:
            target, direction = hi, "up"
            eta = (hi - current) / slope
        elif slope < -1e-9 and lo is not None and current > lo:
            target, direction = lo, "down"
            eta = (current - lo) / abs(slope)
        if eta is None or eta <= 0 or eta > max_eta_days or mk["trend"] == "none":
            continue

        out.append({
            "p_name": pn, "display_name": prof.get("display_name", pn),
            "unit": prof.get("unit", ""), "current": round(current, 4),
            "target_limit": round(target, 4), "direction": direction,
            "slope_per_day": round(slope, 5), "mk_trend": mk["trend"],
            "eta_days": round(eta, 1),
            "eta_date": (end + timedelta(days=eta)).strftime("%Y-%m-%d"),
            "spec_source": bands.get("spec_source"),
        })
    out.sort(key=lambda x: x["eta_days"])
    return out


# ═══════════════════════════════════════════════════════
# 跨设备 / 同型号对标
# ═══════════════════════════════════════════════════════

def benchmark(conn, db, device_code: str, days: int = 30, min_fleet: int = 3,
              running_only: bool = True) -> List[Dict[str, Any]]:
    """同名参数跨设备互比：本机近窗均值 vs 同群(共享同 p_name)分布 → z 分，找离群。

    同一 p_name 跨设备 ≈ 同型号同传感器；fleet<min_fleet 只给信息不判离群。
    """
    end = date.today()
    start = end - timedelta(days=days)
    name_map = db.get_point_names(device_code)
    out: List[Dict[str, Any]] = []

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 本机有哪些整天值参数
        cur.execute("""
            SELECT DISTINCT metric FROM device_param_daily_stats
            WHERE device_code=%s AND stage IS NULL AND metric <> %s AND running_only=%s
              AND stat_date BETWEEN %s AND %s
        """, (device_code, stats_store.STAGE_DUR_METRIC, running_only, start, end))
        my_metrics = [r["metric"] for r in cur.fetchall()]

        for m in my_metrics:
            cur.execute("""
                SELECT device_code, SUM(sum_val) AS s, SUM(cnt) AS c
                FROM device_param_daily_stats
                WHERE metric=%s AND stage IS NULL AND running_only=%s
                  AND stat_date BETWEEN %s AND %s
                GROUP BY device_code
                HAVING SUM(cnt) > 0
            """, (m, running_only, start, end))
            rows = cur.fetchall()
            means = {r["device_code"]: float(r["s"]) / float(r["c"]) for r in rows}
            if device_code not in means:
                continue
            mine = means[device_code]
            peers = [v for d, v in means.items() if d != device_code]
            rec = {"p_name": m, "display_name": name_map.get(m, m),
                   "this_mean": round(mine, 4), "fleet_n": len(means),
                   "fleet_mean": None, "z": None, "outlier": False}
            if len(means) >= min_fleet and peers:
                arr = np.array(list(means.values()), dtype=float)
                fmean, fstd = float(arr.mean()), float(arr.std())
                rec["fleet_mean"] = round(fmean, 4)
                if fstd > 1e-9:
                    z = (mine - fmean) / fstd
                    rec["z"] = round(z, 2)
                    rec["outlier"] = abs(z) >= 2.0
            out.append(rec)
    out.sort(key=lambda x: (x["z"] is None, -abs(x["z"]) if x["z"] is not None else 0))
    return out


# ═══════════════════════════════════════════════════════
# 故障前兆自学习
# ═══════════════════════════════════════════════════════

def learn_precursors(conn, db, device_code: str, days: int = 30, pre_min: int = 30,
                     max_events: int = 40, running_only: bool = True) -> Dict[str, Any]:
    """对齐历史告警事件前 pre_min 分钟的参数行为，聚合"出事前偏移最大的参数"。

    每个参数：跨事件的平均 |稳健z|(窗口均值 vs 该参数全期基线) + 命中率(|z|>2 占比)。
    替代 point_config 里硬编码的故障模式——从数据自学前兆签名。
    """
    device_id = db.get_device_id_by_code(device_code)
    if device_id is None:
        return {"n_events": 0, "precursors": [], "note": "未找到设备"}

    end = datetime.now()
    start = end - timedelta(days=days)
    events = db.get_alarm_events(device_id, start, end)
    alarms = [e for e in events if e.get("status") == ALARM_STATUS]
    if not alarms:
        return {"n_events": 0, "precursors": [], "note": "窗口内无报警事件"}
    alarms = alarms[-max_events:]

    # 各参数全期基线(均值/标准差)，可叠加精确
    base = {}
    for p in param_profile.load_profiles(conn, device_code):
        if p.get("ptype") not in ("continuous", "setpoint"):
            continue
        r = stats_store.rollup(conn, device_code, p["p_name"],
                               start.date(), end.date(), stage=None,
                               running_only=running_only)
        if r and r.get("cnt") and r["std"] > 1e-9:
            base[p["p_name"]] = (r["mean"], r["std"], p.get("display_name", p["p_name"]),
                                 p.get("unit", ""))
    if not base:
        return {"n_events": len(alarms), "precursors": [],
                "note": "无连续参数基线(先建画像/回填统计)"}

    agg: Dict[str, Dict[str, float]] = {p: {"sum_abs_z": 0.0, "hits": 0, "n": 0} for p in base}
    for ev in alarms:
        s = ev.get("start_time")
        if isinstance(s, str):
            s = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        if not isinstance(s, datetime):
            continue
        w0 = s - timedelta(minutes=pre_min)
        rows = db.get_param_data(device_code, start_time=w0, end_time=s)
        vals: Dict[str, List[float]] = {}
        for r in rows:
            v = r.get("p_value_num")
            if v is not None and r["p_name"] in base:
                vals.setdefault(r["p_name"], []).append(v)
        for p, vs in vals.items():
            mean, std, _, _ = base[p]
            z = (float(np.mean(vs)) - mean) / std
            a = agg[p]
            a["sum_abs_z"] += abs(z)
            a["hits"] += 1 if abs(z) >= 2.0 else 0
            a["n"] += 1

    precursors = []
    for p, a in agg.items():
        if a["n"] == 0:
            continue
        _, _, disp, unit = base[p]
        precursors.append({
            "p_name": p, "display_name": disp, "unit": unit,
            "avg_abs_z": round(a["sum_abs_z"] / a["n"], 2),
            "hit_rate": round(a["hits"] / a["n"], 2),
            "events_seen": a["n"],
        })
    precursors.sort(key=lambda x: -x["avg_abs_z"])
    return {"n_events": len(alarms), "pre_min": pre_min,
            "precursors": precursors[:10],
            "note": "avg_abs_z 越大=出事前偏移越明显；hit_rate=该参数在多少比例事件前已显著偏移"}
