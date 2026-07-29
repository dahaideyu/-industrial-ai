# cython: annotation_typing=False, infer_types=False, language_level=3
"""Step⑤KPI / Step⑥阶段CPK：在 stage_analysis.py 的批次/阶段切分基础上，
计算产量(剔除空跑)/合格率/节拍/OEE/单件能耗，以及阶段级时长CPK/参数CPK/能耗。

复用：
- stage_analysis.py 的 _fetch_long/_build_segments/_attach（批次+阶段切分）
- param_profile.py 的 compute_cpk/get_confirmed_map（CPK、已确认规格限）
- analysis_service.py 的 get_llm/_query_knowledge_base_sync（AI 语义对齐，同款调用模式）

设计口径（已与用户确认，见 plan）：
- 产品型号本轮不拆分，按设备整体聚合
- 空跑判定：category=="weight" 的物料重量参数，批次内峰值 < 该参数历史中位值 * 阈值比例 视为空跑
- 合格判定：只用 param_profile 已确认的 spec_low/spec_high，没有已确认规格限时相关字段返回 None
"""
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from psycopg2.extras import RealDictCursor

from core.config import CONFIG
from . import param_profile
from .stage_analysis import _fetch_long, _build_segments, _attach, db_device_name
from .analysis_service import get_llm, _query_knowledge_base_sync, analyze_state_from_pulse


# ══════════════════════════════════════════════════════════
# 空跑判定阈值配置（人工可调，懒创建表，模式同 stage_analysis._ensure_config_table）
# ══════════════════════════════════════════════════════════

def _ensure_kpi_config_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_kpi_config (
                device_code     VARCHAR(64) PRIMARY KEY,
                empty_run_ratio NUMERIC(4,2) NOT NULL DEFAULT 0.30,
                updated_at      TIMESTAMPTZ DEFAULT now(),
                updated_by      VARCHAR(128)
            )
        """)
    conn.commit()


def load_kpi_config(conn, device_code: str) -> Dict[str, Any]:
    _ensure_kpi_config_table(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT empty_run_ratio FROM device_kpi_config WHERE device_code=%s", (device_code,))
        row = cur.fetchone()
    return {"empty_run_ratio": float(row["empty_run_ratio"]) if row else 0.30}


def save_kpi_config(conn, device_code: str, empty_run_ratio: float, user: Optional[str] = None) -> None:
    _ensure_kpi_config_table(conn)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO device_kpi_config (device_code, empty_run_ratio, updated_at, updated_by)
            VALUES (%s, %s, now(), %s)
            ON CONFLICT (device_code) DO UPDATE SET
                empty_run_ratio = EXCLUDED.empty_run_ratio, updated_at = now(), updated_by = EXCLUDED.updated_by
        """, (device_code, empty_run_ratio, user))
    conn.commit()


# ══════════════════════════════════════════════════════════
# 批次/阶段原始数据（复用 stage_analysis 的私有分段函数，不重新发明）
# ══════════════════════════════════════════════════════════

def _fetch_batches_and_data(db, device_code: str, start: datetime, end: datetime, pulse_param: str):
    """拉数据 + 切段（stage/seg_id/batch）。返回 (seg, merged, name_map, unit_map)，无数据时 None。"""
    conn = db.conn
    name_map = db.get_point_names(device_code)
    unit_map = db.get_point_units(device_code)
    meter_ids = db.get_energy_device_ids(device_code)
    raw = _fetch_long(conn, device_code, start, end, meter_ids=meter_ids)
    if raw.empty:
        return None
    stage_long = raw[raw["p_name"] == pulse_param]
    if stage_long.empty:
        return None
    seg = _build_segments(stage_long)
    if seg.empty:
        return None
    target_long = raw[raw["p_name"] != pulse_param]
    merged = _attach(target_long, seg)
    return seg, merged, name_map, unit_map


def _batch_windows(seg: pd.DataFrame) -> pd.DataFrame:
    """每批次("房子")的起止时间 + 总时长(批次内所有段时长之和)。"""
    return (seg.groupby("batch")
              .agg(t_start=("t_start", "min"), t_end=("t_end", "max"), dur_min=("dur_min", "sum"))
              .reset_index())


# ══════════════════════════════════════════════════════════
# Step⑤ KPI：空跑判定 / 合格判定 / 能耗delta
# ══════════════════════════════════════════════════════════

def _detect_empty_batches(conn, device_code: str, merged: pd.DataFrame,
                          threshold_ratio: float) -> (Dict[int, bool], str):
    """按 category=="weight" 参数的批次内峰值 vs 历史中位值判定空跑。

    多个重量参数时，只要有一个显示"批次内出现过接近正常水平的重量"，就不算空跑
    （不同批次可能只用到部分物料通道）。返回 {batch: is_empty}，没有可用重量参数时 ({}, "no_weight_param")。
    """
    profiles = param_profile.load_profiles(conn, device_code)
    weight_params = [p["p_name"] for p in profiles if p.get("category") == "weight" and p.get("p_name")]
    if not weight_params:
        return {}, "no_weight_param"

    result: Dict[int, bool] = {}
    used_any = False
    for p_name in weight_params:
        sub = merged[merged["p_name"] == p_name]
        if sub.empty:
            continue
        median_val = sub["v"].median()
        if median_val is None or median_val <= 0:
            continue
        used_any = True
        peak_by_batch = sub.groupby("batch")["v"].max()
        for b, peak in peak_by_batch.items():
            is_empty_this_param = (peak / median_val) < threshold_ratio
            result[b] = result.get(b, True) and is_empty_this_param
    return (result, "ok") if used_any else ({}, "no_weight_param")


def _judge_batch_quality(conn, device_code: str, merged: pd.DataFrame):
    """只用已确认规格限判定：批次内任一已确认参数超规格 → 该批次不合格。
    没有任何已确认规格限的参数时返回 (None, "no_confirmed_spec")，不编造合格率。
    """
    confirmed = param_profile.get_confirmed_map(conn, device_code)
    spec_params = {p: prof.get("bands", {}) for p, prof in confirmed.items()
                   if (prof.get("bands") or {}).get("spec_low") is not None
                   or (prof.get("bands") or {}).get("spec_high") is not None}
    if not spec_params:
        return None, "no_confirmed_spec"

    result: Dict[int, bool] = {}
    for p_name, bands in spec_params.items():
        sub = merged[merged["p_name"] == p_name]
        if sub.empty:
            continue
        lo, hi = bands.get("spec_low"), bands.get("spec_high")
        by_batch = sub.groupby("batch")["v"].agg(["min", "max"])
        for b, row in by_batch.iterrows():
            out_of_spec = (lo is not None and row["min"] < lo) or (hi is not None and row["max"] > hi)
            result[b] = result.get(b, True) and (not out_of_spec)
    return result, "ok"


def _batch_energy_delta(merged: pd.DataFrame, energy_points=("ene_eptotal", "ene_imp")) -> Dict[int, float]:
    """每批次能耗消耗 = 累计电表读数末-首。优先 ene_eptotal，全窗口无数据才退 ene_imp。"""
    for p_name in energy_points:
        sub = merged[merged["p_name"] == p_name].sort_values("gather_time")
        if sub.empty:
            continue
        by_batch = sub.groupby("batch")["v"].agg(first="first", last="last")
        result = {}
        for b, row in by_batch.iterrows():
            delta = row["last"] - row["first"]
            if delta >= 0:  # 电表偶发回绕/重置时为负，跳过不计入
                result[b] = float(delta)
        return result
    return {}


def _kpi_ai_insight(device_name: str, kpi: Dict[str, Any]) -> Optional[str]:
    """把 KPI 数字组织成 prompt，调 LLM(+知识库) 生成语义解读。数据不足的项如实说明，不编造。"""
    def _fmt(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "数据不足"

    facts = (
        f"设备：{device_name}\n"
        f"总循环数：{kpi['total_cycles']}，剔除空跑后产量：{_fmt(kpi['output_count'], '件')}\n"
        f"合格率：{_fmt(kpi['pass_rate'], '%')}（{kpi['quality_status']}）\n"
        f"节拍：均值{_fmt(kpi['cycle_time']['mean_min'], '分钟')}，"
        f"P10近似标准节拍{_fmt(kpi['cycle_time']['p10_min'], '分钟')}\n"
        f"可用率：{_fmt(kpi['availability'], '%')}，性能效率：{_fmt(kpi['performance'])}\n"
        f"OEE：{_fmt(kpi['oee'], '%')}\n"
        f"能耗：有效{kpi['energy']['valid_kwh']}，空跑{kpi['energy']['empty_run_kwh']}，"
        f"单件{_fmt(kpi['energy']['per_unit_kwh'])}"
    )
    try:
        kb = _query_knowledge_base_sync(device_name, f"该设备的产量/OEE/节拍/能耗正常范围是多少？")
    except Exception:
        kb = None
    try:
        async def _call():
            llm = get_llm()
            prompt = (
                f"以下是设备{device_name}的KPI数据：\n{facts}\n\n"
                + (f"知识库参考：{kb[:400]}\n\n" if kb else "")
                + "请用3-5句话，结合宏观运营视角，指出这组数据反映的问题和1-2条改进建议"
                  "（150字以内，数据不足的指标直接说明不可评估，不要编造具体数值）。"
            )
            resp = await llm.chat.completions.create(
                model=CONFIG["model"], messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=300,
            )
            return resp.choices[0].message.content.strip()
        return asyncio.run(_call())
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
# 产品型号识别："房子形状"(阶段时长占比)持续性变化检测
# ══════════════════════════════════════════════════════════
#
# 用户口径：每个型号生产出来的"房子"形状(阶段时长占比轮廓)大部分固定；一旦长时间
# 出现另一种形状、且这种新形状连续/频繁重复出现，才判定为换了型号——单次冒出来的
# 不同形状是异常波动，不算换型号。判定之后再看其他参数+知识库辅助判断是否合理。

def _batch_shape_vectors(seg: pd.DataFrame) -> Dict[int, Dict[int, float]]:
    """每批次的阶段时长占比向量 {batch: {stage: ratio}}，作为"房子形状"指纹。"""
    per_batch_stage = seg.groupby(["batch", "stage"])["dur_min"].sum().reset_index()
    batch_totals = seg.groupby("batch")["dur_min"].sum()
    vectors: Dict[int, Dict[int, float]] = {}
    for _, row in per_batch_stage.iterrows():
        b, st, d = int(row["batch"]), int(row["stage"]), float(row["dur_min"])
        total = batch_totals.get(b, 0)
        if total > 0:
            vectors.setdefault(b, {})[st] = d / total
    return vectors


def _shape_similarity(a: Dict[int, float], b: Dict[int, float]) -> float:
    """两个形状向量的余弦相似度（维度=阶段码，缺失维度按0处理）。"""
    stages = set(a) | set(b)
    if not stages:
        return 0.0
    va = np.array([a.get(s, 0.0) for s in stages])
    vb = np.array([b.get(s, 0.0) for s in stages])
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


_TYPE_LABELS = [f"产品{c}" for c in "ABCDEFGHIJ"]  # 兜底封顶10种，避免噪声导致无限细分


def _detect_product_types(seg: pd.DataFrame, batches: pd.DataFrame,
                          similarity_threshold: float = 0.85,
                          persistence: int = 3) -> Dict[int, str]:
    """按时间顺序扫描批次形状向量，检测"持续性"的形状变化，划出产品A/B/C…

    只有连续 persistence 个批次都和新形状一致时才确认换型号；否则视为单次异常波动，
    沿用当前型号、不更新质心（避免异常值污染判断基准）。
    """
    ordered = batches.sort_values("t_start")["batch"].tolist()
    if not ordered:
        return {}
    vectors = _batch_shape_vectors(seg)

    type_of: Dict[int, str] = {}
    type_idx = 0
    centroid = vectors.get(ordered[0], {})
    type_of[ordered[0]] = _TYPE_LABELS[type_idx]

    i = 1
    n = len(ordered)
    while i < n:
        b = ordered[i]
        vec = vectors.get(b, {})
        if not vec or _shape_similarity(vec, centroid) >= similarity_threshold:
            type_of[b] = _TYPE_LABELS[type_idx]
            if vec:
                centroid = {s: (centroid.get(s, 0.0) + vec.get(s, 0.0)) / 2 for s in set(centroid) | set(vec)}
            i += 1
            continue

        lookahead = [vectors.get(x, {}) for x in ordered[i:i + persistence]]
        consistent = sum(1 for v in lookahead if v and _shape_similarity(v, vec) >= similarity_threshold)
        if len(lookahead) >= persistence and consistent >= persistence - 1:
            type_idx = min(type_idx + 1, len(_TYPE_LABELS) - 1)
            centroid = vec
        # 无论是否确认换型号，当前这个批次先归到(可能刚更新的)当前型号名下
        type_of[b] = _TYPE_LABELS[type_idx]
        i += 1

    return type_of


def _type_signature_summary(merged: pd.DataFrame, batch_ids: List[int],
                            name_map: Dict[str, str], unit_map: Dict[str, str], top_n: int = 5) -> str:
    """给一组批次算几个代表性参数的均值，供AI+知识库判断型号划分是否合理（不参与硬分组）。"""
    sub = merged[merged["batch"].isin(batch_ids)]
    if sub.empty:
        return "(无参数数据)"
    means = sub.groupby("p_name")["v"].mean().sort_values(ascending=False)
    return "，".join(f"{name_map.get(p, p)}≈{round(v, 2)}{unit_map.get(p, '')}"
                    for p, v in means.head(top_n).items())


def _product_type_insight(device_name: str, type_summaries: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """把各型号的批次数+特征摘要交给LLM+知识库，判断这个形状聚类像不像真实的型号差异。"""
    if len(type_summaries) < 2:
        return None
    facts = "\n".join(f"{label}：{info['batch_count']}个循环，特征：{info['signature']}"
                      for label, info in type_summaries.items())
    try:
        kb = _query_knowledge_base_sync(device_name, "该设备生产的产品有哪些型号/规格，工艺参数差异是什么？")
    except Exception:
        kb = None
    try:
        async def _call():
            llm = get_llm()
            prompt = (
                f"设备{device_name}按生产循环的阶段时长形状聚出以下分组：\n{facts}\n\n"
                + (f"知识库参考：{kb[:400]}\n\n" if kb else "")
                + "请用2-3句话判断这个分组像不像真实存在的不同产品型号/规格，指出可能的区分依据；"
                  "如果看起来只是同一型号的正常波动也请直说（不要编造具体型号名称，没有知识库信息就说不确定）。"
            )
            resp = await llm.chat.completions.create(
                model=CONFIG["model"], messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=200,
            )
            return resp.choices[0].message.content.strip()
        return asyncio.run(_call())
    except Exception:
        return None


def _kpi_for_batches(batch_ids: List[int], batches: pd.DataFrame,
                     empty_map: Dict[int, bool], quality_map: Optional[Dict[int, bool]],
                     energy_map: Dict[int, float]) -> Dict[str, Any]:
    """给一组批次(全部或按型号切出的子集)算产量/合格率/节拍/能耗——纯数值，不含可用率(设备级共享)和AI解读。"""
    total_batches = len(batch_ids)
    valid_batches = [b for b in batch_ids if not empty_map.get(b, False)]
    output_count = len(valid_batches)

    if quality_map is not None:
        good_batches = [b for b in valid_batches if quality_map.get(b, True)]
        good_count = len(good_batches)
        pass_rate = round(good_count / output_count * 100, 1) if output_count else None
    else:
        good_count = None
        pass_rate = None

    valid_dur = batches[batches["batch"].isin(valid_batches)]["dur_min"]
    cycle_mean = round(float(valid_dur.mean()), 2) if len(valid_dur) else None
    cycle_median = round(float(valid_dur.median()), 2) if len(valid_dur) else None
    cycle_p10 = round(float(valid_dur.quantile(0.1)), 2) if len(valid_dur) >= 3 else None
    performance = round(cycle_p10 / cycle_mean, 3) if cycle_p10 and cycle_mean else None

    valid_energy = sum(energy_map.get(b, 0.0) for b in valid_batches)
    empty_batches = [b for b in batch_ids if empty_map.get(b, False)]
    empty_energy = sum(energy_map.get(b, 0.0) for b in empty_batches)
    per_unit_energy = None
    if good_count:
        per_unit_energy = round(valid_energy / good_count, 3)
    elif output_count:
        per_unit_energy = round(valid_energy / output_count, 3)

    return {
        "total_cycles": total_batches, "output_count": output_count,
        "empty_run_count": total_batches - output_count,
        "good_count": good_count, "pass_rate": pass_rate,
        "cycle_time": {"mean_min": cycle_mean, "median_min": cycle_median, "p10_min": cycle_p10},
        "performance": performance,
        "energy": {"valid_kwh": round(valid_energy, 2), "empty_run_kwh": round(empty_energy, 2),
                   "per_unit_kwh": per_unit_energy},
    }


def compute_kpi_summary(db, device_code: str, pulse_param: str, days: int = 1) -> Dict[str, Any]:
    """Step⑤ 主入口：识别产品型号(房子形状聚类) → 按型号分别算产量(剔除空跑)/合格率/
    节拍/OEE/单件能耗 + AI语义对齐；运转率/可用率是设备级共享指标，不拆型号。"""
    end = datetime.now()
    start = end - timedelta(days=days)

    fetched = _fetch_batches_and_data(db, device_code, start, end, pulse_param)
    if fetched is None:
        return {"error": "no_data", "step": 5, "msg": "该窗口内无脉搏参数数据，无法计算KPI。"}
    seg, merged, name_map, unit_map = fetched

    batches = _batch_windows(seg)
    if batches.empty:
        return {"error": "no_batches", "step": 5, "msg": "未能从脉搏参数切出完整批次。"}

    conn = db.conn
    device_name = db_device_name(db, device_code)
    kpi_cfg = load_kpi_config(conn, device_code)
    empty_map, empty_status = _detect_empty_batches(conn, device_code, merged, kpi_cfg["empty_run_ratio"])
    quality_map, quality_status = _judge_batch_quality(conn, device_code, merged)
    energy_map = _batch_energy_delta(merged)
    all_batches = batches["batch"].tolist()

    # 运转率/可用率：设备运行状态本身跟产品型号无关，直接复用 Step③ 的判断，不拆型号
    state = analyze_state_from_pulse(conn, device_code, device_name, pulse_param, days=days)
    availability = state.get("utilization") if isinstance(state, dict) else None

    # 产品型号识别：房子形状持续性变化检测
    type_map = _detect_product_types(seg, batches)
    types_present: List[str] = []
    for b in all_batches:
        label = type_map.get(b)
        if label and label not in types_present:
            types_present.append(label)

    def _finalize(batch_ids: List[int], label: str) -> Dict[str, Any]:
        kpi = _kpi_for_batches(batch_ids, batches, empty_map, quality_map, energy_map)
        kpi["type_label"] = label
        kpi["availability"] = availability
        quality_factor = kpi["pass_rate"] / 100 if kpi["pass_rate"] is not None else None
        if availability is not None and kpi["performance"] is not None and quality_factor is not None:
            kpi["oee"] = round(availability / 100 * kpi["performance"] * quality_factor * 100, 1)
            kpi["oee_note"] = None
        else:
            missing = [name for cond, name in (
                (availability is None, "可用率"),
                (kpi["performance"] is None, "性能效率(节拍样本不足)"),
                (quality_factor is None, "合格率(无已确认规格限)"),
            ) if cond]
            kpi["oee"] = None
            kpi["oee_note"] = "缺少" + "、".join(missing) + "，OEE 暂不可计算"
        kpi["empty_run_status"] = empty_status
        kpi["quality_status"] = quality_status
        return kpi

    product_types: List[Dict[str, Any]] = []
    type_insight = None
    if len(types_present) >= 2:
        type_signature_summaries: Dict[str, Dict[str, Any]] = {}
        for label in types_present:
            batch_ids = [b for b in all_batches if type_map.get(b) == label]
            kpi = _finalize(batch_ids, label)
            kpi["batch_count"] = len(batch_ids)
            kpi["signature"] = _type_signature_summary(merged, batch_ids, name_map, unit_map)
            type_signature_summaries[label] = {"batch_count": len(batch_ids), "signature": kpi["signature"]}
            product_types.append(kpi)
        for kpi in product_types:
            kpi["ai_insight"] = _kpi_ai_insight(device_name, kpi)
        type_insight = _product_type_insight(device_name, type_signature_summaries)

    overall = _finalize(all_batches, "整体")
    overall["ai_insight"] = _kpi_ai_insight(device_name, overall)

    return {
        "step": 5,
        "device_code": device_code,
        "device_name": device_name,
        "window": {"start": start.strftime("%Y-%m-%d %H:%M:%S"), "end": end.strftime("%Y-%m-%d %H:%M:%S")},
        "empty_run_ratio_used": kpi_cfg["empty_run_ratio"],
        "product_types": product_types,
        "type_insight": type_insight,
        "overall": overall,
    }


# ══════════════════════════════════════════════════════════
# Step⑥ 阶段 CPK：阶段时长CPK / 参数CPK(已确认规格限) / 阶段能耗
# ══════════════════════════════════════════════════════════

def _stage_duration_cpk(seg: pd.DataFrame, cpk_target: float = 1.33,
                        filter_pct: float = 0.30) -> Dict[int, Dict[str, Any]]:
    """按阶段，对跨批次 dur_min 序列做中位数过滤 + CPK=1.33 反算规格限。

    算法同 param_profile.recalc_spec_limits()，数据源从参数原始值换成阶段时长序列，
    不需要人工预先配置阶段时长规格限就能出结果。
    """
    result: Dict[int, Dict[str, Any]] = {}
    for stage, grp in seg.groupby("stage"):
        stage = int(stage)
        vals = grp["dur_min"].dropna().tolist()
        n = len(vals)
        if n < 5:
            result[stage] = {"n": n, "note": "批次样本不足(<5)，不计算CPK"}
            continue
        median = float(np.median(vals))
        lo, hi = median * (1 - filter_pct), median * (1 + filter_pct)
        filtered = [v for v in vals if lo <= v <= hi]
        if len(filtered) < 3:
            result[stage] = {"n": n, "note": "中位数过滤后样本不足，不计算CPK"}
            continue
        mu = float(np.mean(filtered))
        sigma = float(np.std(filtered, ddof=1)) if len(filtered) >= 2 else 0.0
        k = cpk_target * 3
        spec_low, spec_high = round(mu - k * sigma, 2), round(mu + k * sigma, 2)
        cpk_info = param_profile.compute_cpk(mu, sigma, spec_low, spec_high)
        out_of_spec = sum(1 for v in vals if v < spec_low or v > spec_high)
        result[stage] = {
            "n": n, "mean_min": round(mu, 2), "std_min": round(sigma, 2),
            "spec_low_min": spec_low, "spec_high_min": spec_high,
            "out_of_spec_count": out_of_spec,
            "out_of_spec_ratio": round(out_of_spec / n * 100, 1),
            **cpk_info,
        }
    return result


def _stage_param_stats(merged: pd.DataFrame, confirmed: Dict[str, Dict[str, Any]],
                       name_map: Dict[str, str], unit_map: Dict[str, str],
                       exclude_params=()) -> Dict[int, Dict[str, Any]]:
    """每阶段、每参数的跨批次 mean/std；已确认规格限的参数额外算 CPK，未确认的只出 mean/std。"""
    sub = merged[~merged["p_name"].isin(set(exclude_params))]
    if sub.empty:
        return {}
    per_batch_mean = sub.groupby(["stage", "p_name", "batch"])["v"].mean().reset_index()
    result: Dict[int, Dict[str, Any]] = {}
    for (stage, p_name), grp in per_batch_mean.groupby(["stage", "p_name"]):
        vals = grp["v"].tolist()
        if len(vals) < 2:
            continue
        mu, sigma = float(np.mean(vals)), float(np.std(vals, ddof=1))
        entry = {
            "display_name": name_map.get(p_name, p_name), "unit": unit_map.get(p_name, ""),
            "n": len(vals), "mean": round(mu, 3), "std": round(sigma, 3),
        }
        bands = (confirmed.get(p_name) or {}).get("bands") or {}
        spec_low, spec_high = bands.get("spec_low"), bands.get("spec_high")
        if spec_low is not None or spec_high is not None:
            entry.update({"spec_low": spec_low, "spec_high": spec_high,
                          **param_profile.compute_cpk(mu, sigma, spec_low, spec_high)})
        result.setdefault(int(stage), {})[p_name] = entry
    return result


def _stage_ai_insight(device_name: str, stage: int, entry: Dict[str, Any]) -> Optional[str]:
    dur = entry.get("duration_cpk") or {}
    lines = [f"阶段{stage}："]
    if dur.get("cpk") is not None:
        lines.append(f"时长均值{dur.get('mean_min')}分钟(±{dur.get('std_min')})，"
                     f"CPK={dur.get('cpk')}，超差{dur.get('out_of_spec_ratio')}%")
    else:
        lines.append(f"时长CPK：{dur.get('note', '数据不足')}")
    for stat in (entry.get("param_stats") or {}).values():
        if stat.get("cpk") is not None:
            lines.append(f"{stat['display_name']}：均值{stat['mean']}{stat['unit']}，CPK={stat['cpk']}")
    if entry.get("energy_avg") is not None:
        lines.append(f"阶段平均能耗：{entry['energy_avg']}")
    facts = "\n".join(lines)

    try:
        kb = _query_knowledge_base_sync(device_name, f"该设备第{stage}阶段的工艺标准和常见异常是什么？")
    except Exception:
        kb = None
    try:
        async def _call():
            llm = get_llm()
            prompt = (
                f"{facts}\n\n" + (f"知识库参考：{kb[:400]}\n\n" if kb else "")
                + "请用2-3句话指出该阶段是否存在需要关注的异常，以及可能的根因/保养建议"
                  "（60字以内，没有异常就说正常，不要编造数据）。"
            )
            resp = await llm.chat.completions.create(
                model=CONFIG["model"], messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=150,
            )
            return resp.choices[0].message.content.strip()
        return asyncio.run(_call())
    except Exception:
        return None


def compute_stage_cpk(db, device_code: str, pulse_param: str, days: int = 7) -> Dict[str, Any]:
    """Step⑥ 主入口：阶段时长CPK + 参数CPK(已确认规格限) + 阶段能耗 + 分阶段AI语义对齐。"""
    end = datetime.now()
    start = end - timedelta(days=days)

    fetched = _fetch_batches_and_data(db, device_code, start, end, pulse_param)
    if fetched is None:
        return {"error": "no_data", "step": 6, "msg": "该窗口内无脉搏参数数据，无法按阶段分析。"}
    seg, merged, name_map, unit_map = fetched

    conn = db.conn
    device_name = db_device_name(db, device_code)
    duration_cpk = _stage_duration_cpk(seg)
    confirmed = param_profile.get_confirmed_map(conn, device_code)

    energy_points = [p for p in ("ene_eptotal", "ene_imp") if (merged["p_name"] == p).any()]
    stage_energy: Dict[int, float] = {}
    if energy_points:
        p_name = energy_points[0]  # 优先 ene_eptotal，同一批次不重复叠加两个点位
        sub = merged[merged["p_name"] == p_name].sort_values("gather_time")
        per_seg_delta = sub.groupby(["stage", "seg_id"])["v"].agg(first="first", last="last")
        per_seg_delta["delta"] = per_seg_delta["last"] - per_seg_delta["first"]
        per_seg_delta = per_seg_delta[per_seg_delta["delta"] >= 0]  # 剔除电表回绕/重置
        by_stage = per_seg_delta.groupby("stage")["delta"].mean()
        stage_energy = {int(st): round(float(v), 3) for st, v in by_stage.items()}

    param_stats = _stage_param_stats(merged, confirmed, name_map, unit_map,
                                     exclude_params=set(energy_points))

    stages_out = []
    for stage in sorted(seg["stage"].unique().tolist()):
        stage = int(stage)
        entry = {
            "stage": stage,
            "duration_cpk": duration_cpk.get(stage),
            "param_stats": param_stats.get(stage, {}),
            "energy_avg": stage_energy.get(stage),
        }
        entry["ai_insight"] = _stage_ai_insight(device_name, stage, entry)
        stages_out.append(entry)

    return {
        "step": 6,
        "device_code": device_code,
        "device_name": device_name,
        "stage_param": {"p_name": pulse_param, "display_name": name_map.get(pulse_param, pulse_param)},
        "stages": stages_out,
    }
