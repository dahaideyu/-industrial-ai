# cython: annotation_typing=False, infer_types=False, language_level=3
"""诊断工具集：薄封装现有参数分析，供 agent function-calling 调用。

每个工具锁定到本次诊断的 device_code（loop 注入，LLM 不需传），自开短连接，返回精简 JSON。
"""

from datetime import datetime, date, timedelta
from collections import Counter
from typing import Any, Dict

from ..services import TimescaleDB
from .. import stats_store, param_profile, advanced_analysis


def _db() -> TimescaleDB:
    db = TimescaleDB()
    if not db.connect():
        raise RuntimeError("TimescaleDB 连接失败")
    return db


def get_param_profile(device_code: str, **_) -> Dict[str, Any]:
    db = _db()
    try:
        profs = param_profile.load_profiles(db.conn, device_code)
        slim = [{"p_name": p["p_name"], "display_name": p.get("display_name"),
                 "ptype": p.get("ptype"), "role": p.get("role"),
                 "category": p.get("category"), "monitor": p.get("monitor"),
                 "confirmed": p.get("confirmed"),
                 "bands": p.get("bands")} for p in profs]
        return {"count": len(slim), "profiles": slim}
    finally:
        db.close()


def get_stats_overview(device_code: str, days: int = 30, **_) -> Dict[str, Any]:
    db = _db()
    try:
        stats_store.ensure_tables(db.conn)
        end = date.today()
        rows = stats_store.stats_overview(db.conn, db, device_code,
                                          end - timedelta(days=days), end)
        # 去掉 series 大字段，保留诊断需要的数字
        slim = [{k: r[k] for k in ("metric", "display_name", "unit", "stage", "n_days",
                                   "mean", "median", "min", "max", "variance", "std",
                                   "change_pct", "sen_slope", "mk_trend", "direction",
                                   "severity") if k in r} for r in rows]
        return {"days": days, "count": len(slim), "metrics": slim}
    finally:
        db.close()


def get_cpk(device_code: str, days: int = 30, **_) -> Dict[str, Any]:
    db = _db()
    try:
        stats_store.ensure_tables(db.conn)
        profiles = {p["p_name"]: p for p in param_profile.load_profiles(db.conn, device_code)}
        end = date.today()
        start = end - timedelta(days=days)
        out = []
        for pn, prof in profiles.items():
            if prof.get("ptype") not in ("continuous", "setpoint"):
                continue
            r = stats_store.rollup(db.conn, device_code, pn, start, end)
            if not r or not r.get("cnt"):
                continue
            bands = prof.get("bands") or {}
            c = param_profile.compute_cpk(r["mean"], r["std"], bands.get("spec_low"),
                                          bands.get("spec_high"))
            out.append({"p_name": pn, "display_name": prof.get("display_name"),
                        "mean": r["mean"], "std": r["std"], **c})
        out.sort(key=lambda x: (x["cpk"] is None, x["cpk"] if x["cpk"] is not None else 1e9))
        return {"days": days, "count": len(out), "cpk": out}
    finally:
        db.close()


def get_rul(device_code: str, days: int = 60, **_) -> Dict[str, Any]:
    db = _db()
    try:
        stats_store.ensure_tables(db.conn)
        items = advanced_analysis.rul_eta(db.conn, db, device_code, days=days)
        return {"count": len(items), "items": items}
    finally:
        db.close()


def get_benchmark(device_code: str, days: int = 30, **_) -> Dict[str, Any]:
    db = _db()
    try:
        stats_store.ensure_tables(db.conn)
        items = advanced_analysis.benchmark(db.conn, db, device_code, days=days)
        return {"count": len(items), "items": items}
    finally:
        db.close()


def get_precursors(device_code: str, days: int = 30, pre_min: int = 30, **_) -> Dict[str, Any]:
    db = _db()
    try:
        stats_store.ensure_tables(db.conn)
        return advanced_analysis.learn_precursors(db.conn, db, device_code,
                                                  days=days, pre_min=pre_min)
    finally:
        db.close()


def get_alarm_history(device_code: str, days: int = 14, **_) -> Dict[str, Any]:
    db = _db()
    try:
        device_id = db.get_device_id_by_code(device_code)
        if device_id is None:
            return {"n_events": 0, "by_status": {}, "note": "未找到设备"}
        end = datetime.now()
        events = db.get_alarm_events(device_id, end - timedelta(days=days), end)
        cnt = Counter(e.get("status_name") or str(e.get("status")) for e in events)
        return {"days": days, "n_events": len(events),
                "by_status": dict(cnt.most_common())}
    finally:
        db.close()


# ── 注册表 + OpenAI function-calling schema ──

TOOLS = {
    "get_param_profile": get_param_profile,
    "get_stats_overview": get_stats_overview,
    "get_cpk": get_cpk,
    "get_rul": get_rul,
    "get_benchmark": get_benchmark,
    "get_precursors": get_precursors,
    "get_alarm_history": get_alarm_history,
}


def _fn(name: str, desc: str, props: Dict[str, Any] | None = None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props or {}, "required": []}}}

_DAYS = {"days": {"type": "integer", "description": "回溯天数"}}

TOOLS_SCHEMA = [
    _fn("get_param_profile", "获取该设备每个参数的画像：类型/角色/类别/正常区间/spec/是否已确认。"),
    _fn("get_stats_overview", "获取全部参数的统计趋势总览：均值/方差/标准差/中位/极值 + 趋势/severity。", _DAYS),
    _fn("get_cpk", "获取连续参数的过程能力 Cpk/Cp/Ca（需画像里有 spec）。", _DAYS),
    _fn("get_rul", "剩余寿命/触限 ETA：按趋势斜率外推到上下限，估还有几天触限。", _DAYS),
    _fn("get_benchmark", "跨设备对标：同名参数 z 分，找与同伴不一样的离群参数。", _DAYS),
    _fn("get_precursors", "故障前兆自学习：历史告警前偏移最大的参数。",
        {**_DAYS, "pre_min": {"type": "integer", "description": "告警前回看分钟数"}}),
    _fn("get_alarm_history", "近期告警/状态事件按类型的汇总计数。", _DAYS),
]
