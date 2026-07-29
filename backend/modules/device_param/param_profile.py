# cython: annotation_typing=False, infer_types=False, language_level=3
"""参数画像自适应层：为每个 device×参数 自动推断"画像"，让分析适配任意/未知参数。

三信号融合（纯数据为主、LLM 提语义、人确认）：
  1) signature_from_values —— 统计签名(基数/整数性/值域/单调性) → ptype，**参数无关，无名字也能判**
  2) read_db_meta          —— dev_device_param 的 name/description/unit/type（启用没人用的 type 列）
  3) learn_bands           —— 从 device_param_daily_stats 历史(精确 mean/std)学正常/警告/spec 建议
  4) llm_classify          —— 整批发 LLM 提语义(role/category/中文名)，失败则纯统计兜底
build_profile 融合→建议画像(confirmed=False)，工艺界面确认后高风险用途才生效。

profile 缺失/未确认时，调用方一律回退现有关键词/硬编码逻辑（不破坏现状）。
"""

import json
import math
import os
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import yaml
from psycopg2.extras import RealDictCursor, execute_values

from . import stats_store
from . import trend_drift as td

# ═══════════════════════════════════════════════════════
# CPK 重算(中位数过滤+CPK=1.33)默认参数：走配置文件，不硬编码
# ═══════════════════════════════════════════════════════

_CPK_RECALC_CONFIG_DEFAULTS = {
    "median_filter_low_pct": 0.15,
    "median_filter_high_pct": 0.15,
    "cpk_target": 1.33,
}
_CPK_RECALC_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "cpk_recalc_config.yaml")


def get_cpk_recalc_config() -> Dict[str, float]:
    """读 config/cpk_recalc_config.yaml 里的中位数过滤上下限比例 + CPK目标值。

    文件不存在或缺字段时，用默认值(15%/15%/1.33)补全并写回文件，保证配置文件
    始终是"当前生效值"的唯一真实来源，不是散落在各处函数签名里的字面量。
    """
    config = dict(_CPK_RECALC_CONFIG_DEFAULTS)
    existing = None
    if os.path.exists(_CPK_RECALC_CONFIG_PATH):
        try:
            with open(_CPK_RECALC_CONFIG_PATH, "r", encoding="utf-8") as f:
                existing = yaml.safe_load(f)
        except Exception as e:
            print(f"[param_profile] 读取 cpk_recalc_config.yaml 失败，用默认值: {e}")

    if isinstance(existing, dict):
        config.update({k: existing[k] for k in _CPK_RECALC_CONFIG_DEFAULTS if k in existing})

    if existing != config:
        try:
            os.makedirs(os.path.dirname(_CPK_RECALC_CONFIG_PATH), exist_ok=True)
            with open(_CPK_RECALC_CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            print(f"[param_profile] 初始化 cpk_recalc_config.yaml 失败(不影响本次使用默认值): {e}")

    return config

# 语义类别的中文名关键词（便宜的默认，LLM/人会细化）
_CATEGORY_KEYWORDS = [
    ("temperature", ("温",)),
    ("vacuum", ("真空",)),
    ("pressure", ("压", "风压")),
    ("weight", ("重", "重量", "称")),
    ("power", ("功率", "电流", "电压", "功")),
    ("speed", ("速", "转速", "频率")),
    ("stage", ("阶段", "工序", "状态")),
    ("flow", ("流量",)),
    ("level", ("液位", "料位")),
]


# ═══════════════════════════════════════════════════════
# 建表
# ═══════════════════════════════════════════════════════

def ensure_table(conn) -> None:
    """device_param_profile：每 (设备,参数) 一行画像 JSONB + 确认态。"""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_param_profile (
                device_code VARCHAR(64)  NOT NULL,
                p_name      VARCHAR(128) NOT NULL,
                profile     JSONB        NOT NULL,
                confirmed   BOOLEAN      NOT NULL DEFAULT FALSE,
                updated_by  VARCHAR(128),
                updated_at  TIMESTAMPTZ  DEFAULT now(),
                PRIMARY KEY (device_code, p_name)
            )
        """)
    conn.commit()


# ═══════════════════════════════════════════════════════
# 信号 1：统计签名 → ptype（参数无关）
# ═══════════════════════════════════════════════════════

def signature_from_values(values: List[float]) -> Dict[str, Any]:
    """从一串数值算统计签名。无名字也能判类型。"""
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    arr = arr[np.isfinite(arr)]
    n = int(arr.size)
    if n == 0:
        return {"n": 0}
    uniq = np.unique(arr)
    diffs = np.diff(arr)
    sig = {
        "n": n,
        "cardinality": int(uniq.size),
        "vmin": float(arr.min()),
        "vmax": float(arr.max()),
        "mean": float(arr.mean()),
        "std": float(arr.std()),
        "integer_only": bool(np.all(np.equal(np.mod(arr, 1), 0))),
        "monotonic_frac": float(np.mean(diffs >= 0)) if diffs.size else 1.0,
        "distinct_sample": [float(x) for x in uniq[:12]],
    }
    return sig


def classify_ptype(sig: Dict[str, Any]) -> Dict[str, Any]:
    """由签名落 ptype + 置信度。switch/state/counter/setpoint/continuous/unknown。"""
    n = sig.get("n", 0)
    if n < 20:
        return {"ptype": "unknown", "confidence": 0.3}
    card = sig["cardinality"]
    rng = sig["vmax"] - sig["vmin"]
    intonly = sig["integer_only"]
    mono = sig["monotonic_frac"]
    if card <= 2:
        return {"ptype": "switch", "confidence": 0.9}
    if intonly and card <= 20 and rng <= 50:
        return {"ptype": "state", "confidence": 0.75, "is_stage_param": True}
    if mono >= 0.97 and rng > 0:
        return {"ptype": "counter", "confidence": 0.7, "is_cumulative": True}
    if (not intonly) and card <= 10:
        return {"ptype": "setpoint", "confidence": 0.5}
    return {"ptype": "continuous", "confidence": 0.8}


def _category_from_name(desc: str) -> Optional[str]:
    if not desc:
        return None
    for cat, kws in _CATEGORY_KEYWORDS:
        if any(k in desc for k in kws):
            return cat
    return None


def _role_from_ptype(ptype: str) -> str:
    return {
        "state": "state_machine", "switch": "diagnostic", "counter": "counter",
        "setpoint": "control_setpoint", "continuous": "process_indicator",
    }.get(ptype, "process_indicator")


# ═══════════════════════════════════════════════════════
# 信号 2：DB 元数据（启用 dev_device_param.type）
# ═══════════════════════════════════════════════════════

def read_db_meta(db, device_code: str) -> Dict[str, Dict[str, Any]]:
    """{p_name: {description, unit, db_type}}。type 列缺失时优雅降级。

    含关联电表(device_energy_meter)的能耗点位元数据——跟 services.get_points 保持
    一致，否则能耗点位在这里查不到 description/unit，画像会退化成"无名参数"。
    """
    out: Dict[str, Dict[str, Any]] = {}
    device_ids = [device_code] + db.get_energy_device_ids(device_code)
    try:
        with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT name AS p_name, description, unit, type
                FROM dev_device_param WHERE device_no = ANY(%s)
            """, (device_ids,))
            for r in cur.fetchall():
                out[r["p_name"]] = {"description": r.get("description") or "",
                                    "unit": r.get("unit") or "",
                                    "db_type": r.get("type") or ""}
    except Exception as e:
        print(f"[param_profile] read_db_meta type 列读取失败，降级: {e}")
        names = db.get_point_names(device_code)
        units = db.get_point_units(device_code)
        for p, d in names.items():
            out[p] = {"description": d or "", "unit": units.get(p, ""), "db_type": ""}
    return out


# ═══════════════════════════════════════════════════════
# 信号 3：从历史学正常/警告/spec 区间（读 daily_stats，精确可叠加）
# ═══════════════════════════════════════════════════════

def learn_bands(conn, device_code: str, p_name: str, days: int = 60) -> Dict[str, Any]:
    """用 device_param_daily_stats 的精确 mean/std/极值，给正常/警告/spec(learned) 建议。

    normal = mean ± 2σ（夹在 [min,max]）；warn = mean ± 3σ；spec(learned) 同 warn 起步。
    人可在界面把 spec 改成工程规格（source=engineering）。
    """
    end = date.today()
    start = end - timedelta(days=days)
    r = stats_store.rollup(conn, device_code, p_name, start, end,
                           stage=None, running_only=True)
    if not r or not r.get("cnt"):
        return {}
    mean, std = r["mean"], r["std"]
    vmin, vmax = r["min"], r["max"]

    def _clip(x):
        return float(min(max(x, vmin), vmax))
    return {
        "mean": round(mean, 4), "std": round(std, 4),
        "median": r.get("median_approx"),
        "vmin": vmin, "vmax": vmax,
        "normal_low": round(_clip(mean - 2 * std), 4),
        "normal_high": round(_clip(mean + 2 * std), 4),
        "warn_low": round(_clip(mean - 3 * std), 4),
        "warn_high": round(_clip(mean + 3 * std), 4),
        "spec_low": round(_clip(mean - 3 * std), 4),
        "spec_high": round(_clip(mean + 3 * std), 4),
        "spec_source": "learned",
        "sample_days": r.get("n_days", 0),
    }


# ═══════════════════════════════════════════════════════
# 信号 4：LLM 整批语义分类（失败则统计兜底）
# ═══════════════════════════════════════════════════════

async def llm_classify(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """整批把(英文名/中文名/单位/签名)发 LLM，返回 {p_name: {role, category, friendly}}。

    只提"建议"——失败/超时返回 {}，由统计签名兜底。复用 analysis_service 的 LLM 客户端。
    """
    if not items:
        return {}
    try:
        from .analysis_service import get_llm
        from core.config import CONFIG
    except Exception:
        return {}

    lines = []
    for it in items:
        lines.append(
            f"- p_name={it['p_name']} | 中文名={it.get('description', '')} | "
            f"单位={it.get('unit', '')} | db_type={it.get('db_type', '')} | "
            f"统计={it.get('ptype', '')},基数={it.get('cardinality', '')},"
            f"范围=[{it.get('vmin', '')},{it.get('vmax', '')}],样例={it.get('distinct_sample', '')}")
    user = (
        "你是工业设备工艺专家。下面是某设备的参数清单(含英文点位名/中文名/单位/统计特征)。"
        "请为每个参数判断：ptype(continuous连续量/state状态量/counter计数累积/switch开关量/"
        "setpoint设定值/enum枚举)、role(process_indicator工艺指标/control_setpoint控制设定/"
        "state_machine状态机/diagnostic诊断/quality质量/energy能耗/counter计数)、"
        "category(temperature/pressure/vacuum/weight/power/speed/stage/flow/level/other)、"
        "friendly(简短中文释义)。\n"
        "只输出 JSON 数组，每项 {p_name, ptype, role, category, friendly}，不要多余文字。\n\n"
        + "\n".join(lines)
    )
    try:
        llm = get_llm()
        resp = await llm.chat.completions.create(
            model=CONFIG["model"],
            messages=[{"role": "user", "content": user}],
            temperature=0.1,
        )
        text = resp.choices[0].message.content or ""
        s, e = text.find("["), text.rfind("]")
        if s < 0 or e < 0:
            return {}
        arr = json.loads(text[s:e + 1])
        return {o["p_name"]: o for o in arr if isinstance(o, dict) and o.get("p_name")}
    except Exception as ex:
        print(f"[param_profile] llm_classify 失败，统计兜底: {ex}")
        return {}


# ═══════════════════════════════════════════════════════
# 融合 → 画像
# ═══════════════════════════════════════════════════════

async def build_profiles(db, device_code: str, sample_days: int = 1,
                         use_llm: bool = True) -> List[Dict[str, Any]]:
    """对设备全部参数产出建议画像(confirmed=False)。融合统计签名/DB元数据/学习区间/LLM 语义。"""
    conn = db.conn
    ensure_table(conn)
    stats_store.ensure_tables(conn)

    # 取近 sample_days 原始采样算统计签名（一次拉取，全参数）
    latest = db.get_latest_param_time(device_code) or datetime.now()
    s0 = latest - timedelta(days=sample_days)
    rows = db.get_param_data(device_code, start_time=s0, end_time=latest)
    values_by: Dict[str, List[float]] = {}
    for r in rows:
        v = r.get("p_value_num")
        if v is not None:
            values_by.setdefault(r["p_name"], []).append(v)

    meta = read_db_meta(db, device_code)
    # 参数全集：DB 元数据 ∪ 实际有数据的
    all_params = sorted(set(meta.keys()) | set(values_by.keys()))

    # 组装 LLM 输入（带签名），整批一次
    items, sigs = [], {}
    for p in all_params:
        sig = signature_from_values(values_by.get(p, []))
        sigs[p] = sig
        cls = classify_ptype(sig)
        items.append({
            "p_name": p, "ptype": cls["ptype"],
            "description": meta.get(p, {}).get("description", ""),
            "unit": meta.get(p, {}).get("unit", ""),
            "db_type": meta.get(p, {}).get("db_type", ""),
            "cardinality": sig.get("cardinality"), "vmin": sig.get("vmin"),
            "vmax": sig.get("vmax"), "distinct_sample": sig.get("distinct_sample"),
        })
    llm_out = await llm_classify(items) if use_llm else {}

    profiles = []
    for p in all_params:
        sig = sigs[p]
        cls = classify_ptype(sig)
        m = meta.get(p, {})
        lo = llm_out.get(p, {})
        ptype = lo.get("ptype") or cls["ptype"]
        category = lo.get("category") or _category_from_name(m.get("description", "")) or "other"
        role = lo.get("role") or _role_from_ptype(ptype)
        bands = learn_bands(conn, device_code, p) if ptype in ("continuous", "setpoint") else {}

        prof = {
            "p_name": p,
            "display_name": m.get("description") or lo.get("friendly") or p,
            "unit": m.get("unit", ""),
            "ptype": ptype,
            "role": role,
            "category": category,
            "is_stage_param": bool(cls.get("is_stage_param", False)),
            "is_cumulative": bool(cls.get("is_cumulative", False)),
            "cardinality": sig.get("cardinality", 0),
            "monitor": ptype in ("continuous", "setpoint"),   # 默认盯连续/设定量
            "bands": bands,
            "friendly": lo.get("friendly", ""),
            "source": {
                "ptype": "llm" if lo.get("ptype") else ("stats" if sig.get("n") else "db_type"),
                "role": "llm" if lo.get("role") else "stats",
                "category": "llm" if lo.get("category") else ("db_type" if category != "other" else "stats"),
                "bands": "stats" if bands else "none",
            },
            "confidence": round(float(cls.get("confidence", 0.5)), 2),
        }
        profiles.append(prof)
    return profiles


# ═══════════════════════════════════════════════════════
# 存/读
# ═══════════════════════════════════════════════════════

def save_suggestions(conn, device_code: str, profiles: List[Dict[str, Any]]) -> int:
    """写"建议"画像。**不覆盖已确认行**（ON CONFLICT 仅更新 confirmed=false 的）。"""
    if not profiles:
        return 0
    values = [[device_code, p["p_name"], json.dumps(p, ensure_ascii=False)] for p in profiles]
    sql = """
        INSERT INTO device_param_profile (device_code, p_name, profile, confirmed, updated_at)
        VALUES %s
        ON CONFLICT (device_code, p_name) DO UPDATE
          SET profile = EXCLUDED.profile, updated_at = now()
          WHERE device_param_profile.confirmed = FALSE
    """
    tmpl = "(%s, %s, %s::jsonb, FALSE, now())"
    with conn.cursor() as cur:
        execute_values(cur, sql, values, template=tmpl)
    conn.commit()
    return len(profiles)


def save_confirmed(conn, device_code: str, p_name: str, profile: Dict[str, Any],
                   user: Optional[str] = None) -> None:
    """工艺编辑/确认单个参数画像（confirmed=true）。"""
    ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO device_param_profile (device_code, p_name, profile, confirmed, updated_by, updated_at)
            VALUES (%s, %s, %s::jsonb, TRUE, %s, now())
            ON CONFLICT (device_code, p_name) DO UPDATE
              SET profile=EXCLUDED.profile, confirmed=TRUE,
                  updated_by=EXCLUDED.updated_by, updated_at=now()
        """, (device_code, p_name, json.dumps(profile, ensure_ascii=False), user))
    conn.commit()


def load_profiles(conn, device_code: str) -> List[Dict[str, Any]]:
    """读设备全部参数画像（含 confirmed 状态）。"""
    ensure_table(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""SELECT p_name, profile, confirmed, updated_by, updated_at
                       FROM device_param_profile WHERE device_code=%s ORDER BY p_name""",
                    (device_code,))
        out = []
        for r in cur.fetchall():
            prof = dict(r["profile"])
            prof["confirmed"] = r["confirmed"]
            prof["updated_by"] = r["updated_by"]
            out.append(prof)
        return out


def get_confirmed_map(conn, device_code: str) -> Dict[str, Dict[str, Any]]:
    """{p_name: profile} 仅已确认行。供硬编码点改读 profile 时用（未确认/缺失则回退）。"""
    try:
        ensure_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""SELECT p_name, profile FROM device_param_profile
                           WHERE device_code=%s AND confirmed=TRUE""", (device_code,))
            return {r["p_name"]: dict(r["profile"]) for r in cur.fetchall()}
    except Exception as e:
        print(f"[param_profile] get_confirmed_map 失败: {e}")
        return {}


# ═══════════════════════════════════════════════════════
# Cpk 过程能力（读 daily_stats 精确 mean/std + profile.spec）
# ═══════════════════════════════════════════════════════

def get_threshold_config(conn, device_code: str) -> Dict[str, tuple]:
    """从**已确认**画像产出阈值配置，供 device_warning AnomalyDetector 的
    config['parameter_thresholds'] 用，替代 point_config 硬编码。

    格式与该检测器一致：{中文名: (正常下限, 正常上限, 报警下限, 报警上限)}。
    只用已确认行(喂告警=高风险)；缺失/未确认则空，调用方回退 point_config。
    """
    out: Dict[str, tuple] = {}
    for pn, prof in get_confirmed_map(conn, device_code).items():
        b = prof.get("bands") or {}
        nl, nh = b.get("normal_low"), b.get("normal_high")
        wl, wh = b.get("warn_low"), b.get("warn_high")
        if None in (nl, nh, wl, wh):
            continue
        key = prof.get("display_name") or pn
        out[key] = (nl, nh, wl, wh)   # (正常下,正常上,报警下,报警上)
    return out


def compute_cpk(mean: float, std: float, spec_low: Optional[float],
                spec_high: Optional[float]) -> Dict[str, Any]:
    """Cp/Cpk/Ca。单/双边规格都支持；std≤0 返回空。"""
    if std is None or std <= 0:
        return {"cpk": None, "cp": None, "ca": None, "note": "标准差为0或缺失"}
    cpu = (spec_high - mean) / (3 * std) if spec_high is not None else None
    cpl = (mean - spec_low) / (3 * std) if spec_low is not None else None
    cands = [c for c in (cpu, cpl) if c is not None]
    cpk = min(cands) if cands else None
    cp = ca = None
    if spec_low is not None and spec_high is not None:
        cp = (spec_high - spec_low) / (6 * std)
        center = (spec_high + spec_low) / 2
        half = (spec_high - spec_low) / 2
        ca = abs(mean - center) / half if half > 0 else None
    return {
        "cpk": round(cpk, 3) if cpk is not None else None,
        "cp": round(cp, 3) if cp is not None else None,
        "ca": round(ca, 3) if ca is not None else None,
        "cpu": round(cpu, 3) if cpu is not None else None,
        "cpl": round(cpl, 3) if cpl is not None else None,
    }


def recalc_spec_limits(conn, device_code: str, p_name: str,
                       cpk_target: Optional[float] = None,
                       median_filter_low_pct: Optional[float] = None,
                       median_filter_high_pct: Optional[float] = None) -> Dict[str, Any]:
    """基于原始数据重算规格上下限（CPK=1.33 算法）。

    1. 拉取该参数最近 14 天原始数据（上限 10 万条）
    2. 取中位数 M
    3. 保留 [M*(1-low_pct), M*(1+high_pct)] 内的值（过滤离群，下限和上限可独立调节）
    4. 在过滤后的集合上计算 μ 和 σ
    5. USL = μ + cpk_target * 3σ, LSL = μ - cpk_target * 3σ

    三个参数不传时，从 config/cpk_recalc_config.yaml 读默认值（不再是函数签名里的字面量）；
    调用方（如前端"重算"弹窗手动调整过）显式传值时，仍然可以单次覆盖，不影响配置文件。
    """
    from psycopg2.extras import RealDictCursor
    import statistics

    cfg = get_cpk_recalc_config()
    if cpk_target is None:
        cpk_target = cfg["cpk_target"]
    if median_filter_low_pct is None:
        median_filter_low_pct = cfg["median_filter_low_pct"]
    if median_filter_high_pct is None:
        median_filter_high_pct = cfg["median_filter_high_pct"]

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '30s'")
            cur.execute("""
                SELECT a.point_value::double precision AS v
                FROM device_alarm_info a
                WHERE a.device_id = %s
                  AND a.point_id = %s
                  AND a.point_time >= NOW() - INTERVAL '14 days'
                ORDER BY a.point_time
                LIMIT 100000
            """, (device_code, p_name))
            rows = cur.fetchall()
    except Exception as e:
        return {"error": f"查询原始数据失败: {e}"}

    values = [r["v"] for r in rows if r["v"] is not None]
    if len(values) < 10:
        return {"error": f"原始数据不足（仅 {len(values)} 条），需要 ≥10 条"}

    total_count = len(values)

    # 中位数过滤（下限和上限独立调节）
    median = statistics.median(values)
    lo = median * (1 - median_filter_low_pct)
    hi = median * (1 + median_filter_high_pct)
    filtered = [v for v in values if lo <= v <= hi]
    filtered_count = len(filtered)

    if filtered_count < 5:
        return {"error": f"中位数下限-{median_filter_low_pct*100:.0f}% 上限+{median_filter_high_pct*100:.0f}% 过滤后数据不足（仅 {filtered_count} 条）"}

    mu = statistics.mean(filtered)
    sigma = statistics.stdev(filtered) if len(filtered) >= 2 else 0.0

    if sigma <= 0:
        return {"error": "过滤后数据标准差为 0，无法计算规格限"}

    k = cpk_target * 3  # CPK=1.33 → k≈3.99
    spec_low = round(mu - k * sigma, 4)
    spec_high = round(mu + k * sigma, 4)

    return {
        "total_count": total_count,
        "filtered_count": filtered_count,
        "median": round(median, 4),
        "filter_range": [round(lo, 4), round(hi, 4)],
        "mean": round(mu, 4),
        "std": round(sigma, 4),
        "cpk_target": cpk_target,
        "spec_low": spec_low,
        "spec_high": spec_high,
    }


def calc_cpk_from_raw(conn, device_code: str, p_name: str,
                      spec_low: float, spec_high: float) -> Dict[str, Any]:
    """用 device_param_daily_stats（与 /cpk 同源）+ 给定规格限计算 CPK。"""
    from datetime import date, timedelta
    from . import stats_store

    end_d = date.today()
    start_d = end_d - timedelta(days=30)

    r = stats_store.rollup(conn, device_code, p_name, start_d, end_d,
                           stage=None, running_only=True)
    if not r or not r.get("cnt"):
        return {"error": "daily_stats 中无该参数数据，请先执行统计回填"}

    mu = r["mean"]
    sigma = r["std"]
    if sigma is None or sigma <= 0:
        return {"error": "数据标准差为 0，无法计算 CPK"}

    cpu = (spec_high - mu) / (3 * sigma)
    cpl = (mu - spec_low) / (3 * sigma)
    cpk = min(cpu, cpl)

    return {
        "data_source": "device_param_daily_stats",
        "total_count": int(r["cnt"]),
        "n_days": int(r.get("n_days", 0)),
        "mean": round(mu, 4),
        "std": round(sigma, 4),
        "spec_low": spec_low,
        "spec_high": spec_high,
        "cpu": round(cpu, 4),
        "cpl": round(cpl, 4),
        "cpk": round(cpk, 4),
    }
