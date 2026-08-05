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
import math
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from psycopg2.extras import RealDictCursor

from core.config import CONFIG
from . import param_profile
from . import tuning
from .stage_analysis import _fetch_long, _build_segments, _attach, db_device_name, load_state_groups
from .analysis_service import get_llm, query_knowledge_base, analyze_state_from_pulse


# ══════════════════════════════════════════════════════════
# NaN/Infinity 清洗：Starlette JSONResponse 使用 allow_nan=False，
# 响应中含 NaN/Infinity 会触发 ValueError → FastAPI 返回 500
# ══════════════════════════════════════════════════════════

def _sanitize_nan(obj: Any) -> Any:
    """递归将 NaN/Infinity 替换为 None，防止 JSON 序列化失败。"""
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


# ══════════════════════════════════════════════════════════
# 空跑判定阈值配置（人工可调，懒创建表，模式同 stage_analysis._ensure_config_table）
# ══════════════════════════════════════════════════════════

DEFAULT_EMPTY_RUN_RATIO = 0.30


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
        # 标准节拍（standard cycle time）——性能效率的固定基准。增量加列，兼容老库。
        cur.execute("ALTER TABLE device_kpi_config ADD COLUMN IF NOT EXISTS std_cycle_min NUMERIC(10,2)")
        cur.execute("ALTER TABLE device_kpi_config ADD COLUMN IF NOT EXISTS std_cycle_source VARCHAR(16)")
        cur.execute("ALTER TABLE device_kpi_config ADD COLUMN IF NOT EXISTS std_cycle_at TIMESTAMPTZ")
    conn.commit()


def load_kpi_config(conn, device_code: str) -> Dict[str, Any]:
    _ensure_kpi_config_table(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT empty_run_ratio, std_cycle_min, std_cycle_source, std_cycle_at
            FROM device_kpi_config WHERE device_code=%s
        """, (device_code,))
        row = cur.fetchone()
    if not row:
        return {"empty_run_ratio": DEFAULT_EMPTY_RUN_RATIO, "std_cycle_min": None,
                "std_cycle_source": None, "std_cycle_at": None}
    return {
        "empty_run_ratio": float(row["empty_run_ratio"]) if row["empty_run_ratio"] is not None else DEFAULT_EMPTY_RUN_RATIO,
        "std_cycle_min": float(row["std_cycle_min"]) if row["std_cycle_min"] is not None else None,
        "std_cycle_source": row["std_cycle_source"],
        "std_cycle_at": row["std_cycle_at"].strftime("%Y-%m-%d %H:%M:%S") if row["std_cycle_at"] else None,
    }


def save_kpi_config(conn, device_code: str,
                    empty_run_ratio: Optional[float] = None,
                    std_cycle_min: Optional[float] = None,
                    std_cycle_source: Optional[str] = None,
                    user: Optional[str] = None) -> None:
    """部分更新：只写传进来的字段，None 表示不改（用 COALESCE 保留原值）。"""
    _ensure_kpi_config_table(conn)
    set_std_at = std_cycle_min is not None or std_cycle_source is not None
    with conn.cursor() as cur:
        # 注意：UPDATE 分支不能用 EXCLUDED.empty_run_ratio —— 它在 INSERT 里已被
        # COALESCE 成默认值 0.30，永远非 NULL，会把"只改标准节拍"变成把空跑阈值
        # 重置回默认。所以 UPDATE 分支单独再传一次原始参数判空。
        cur.execute("""
            INSERT INTO device_kpi_config
                (device_code, empty_run_ratio, std_cycle_min, std_cycle_source, std_cycle_at, updated_at, updated_by)
            VALUES (%s, COALESCE(%s, 0.30), %s, %s, CASE WHEN %s THEN now() ELSE NULL END, now(), %s)
            ON CONFLICT (device_code) DO UPDATE SET
                empty_run_ratio  = COALESCE(%s, device_kpi_config.empty_run_ratio),
                std_cycle_min    = COALESCE(EXCLUDED.std_cycle_min, device_kpi_config.std_cycle_min),
                std_cycle_source = COALESCE(EXCLUDED.std_cycle_source, device_kpi_config.std_cycle_source),
                std_cycle_at     = COALESCE(EXCLUDED.std_cycle_at, device_kpi_config.std_cycle_at),
                updated_at = now(), updated_by = EXCLUDED.updated_by
        """, (device_code, empty_run_ratio, std_cycle_min, std_cycle_source, set_std_at, user,
              empty_run_ratio))
    conn.commit()


# ══════════════════════════════════════════════════════════
# 批次/阶段原始数据（复用 stage_analysis 的私有分段函数，不重新发明）
# ══════════════════════════════════════════════════════════

def _fetch_batches_and_data(db, device_code: str, start: datetime, end: datetime, pulse_param: str,
                            meter_ids: Optional[List[str]] = None):
    """拉数据 + 切段（stage/seg_id/batch）。返回 (seg, merged, name_map, unit_map, meter_ids)，无数据时 None。

    meter_ids 一并返回，调用方不必再查一遍 device_energy_meter；调用方若已经查过
    （如能耗入口需要先判断有无电表以便快速失败）可直接传进来，避免重复查询。
    """
    conn = db.conn
    name_map = db.get_point_names(device_code)
    unit_map = db.get_point_units(device_code)
    if meter_ids is None:
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
    return seg, merged, name_map, unit_map, meter_ids


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


def _run_concurrently(coro_factory, count: int) -> List[Any]:
    """在独立线程里并发跑一批协程，返回结果列表（异常位置返回 None）。

    为什么起独立线程而不是直接 asyncio.run：调用方是 FastAPI 的同步 def 端点，
    当前没有运行中的事件循环，asyncio.run 可用；但一旦哪天端点改成 async def，
    asyncio.run 会直接抛 "cannot be called from a running event loop"。
    放到独立线程里跑，两种情况都安全。

    coro_factory(i) 必须在**线程内**才被调用来创建协程 —— 协程对象绑定创建它的
    事件循环，提前创建会绑错循环。
    """
    if count <= 0:
        return []
    box: List[Any] = []

    def _worker():
        async def _all():
            return await asyncio.gather(*(coro_factory(i) for i in range(count)),
                                        return_exceptions=True)
        try:
            box.extend(asyncio.run(_all()))
        except Exception as e:
            print(f"[AI并发] 批量调用失败: {e}")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if len(box) != count:
        return [None] * count
    out = []
    for r in box:
        if isinstance(r, BaseException):
            print(f"[AI并发] 单项失败: {r}")
            out.append(None)
        else:
            out.append(r)
    return out


async def _llm_text(prompt: str, max_tokens: int = 300) -> Optional[str]:
    """一次性文本补全，失败返回 None（AI 解读是锦上添花，不能拖垮主流程）。"""
    try:
        llm = get_llm()
        resp = await llm.chat.completions.create(
            model=CONFIG["model"], messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip() or None
    except Exception as e:
        print(f"[AI解读] LLM 调用失败: {e}")
        return None


async def _kb_async(device_name: str, question: str) -> Optional[str]:
    """知识库检索（同步阻塞的 RAGFlow 调用）挪到线程里，不占住事件循环。"""
    try:
        return await asyncio.to_thread(query_knowledge_base, device_name, question)
    except Exception as e:
        print(f"[AI解读] 知识库检索失败: {e}")
        return None


async def _kpi_ai_insight(device_name: str, kpi: Dict[str, Any]) -> Optional[str]:
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
    # 这个问题是常量：同一设备问多少次结果都一样，靠 query_knowledge_base 的缓存去重
    kb = await _kb_async(device_name, "该设备的产量/OEE/节拍/能耗正常范围是多少？")
    prompt = (
        f"以下是设备{device_name}的KPI数据：\n{facts}\n\n"
        + (f"知识库参考：{kb[:400]}\n\n" if kb else "")
        + "请用3-5句话，结合宏观运营视角，指出这组数据反映的问题和1-2条改进建议"
          "（150字以内，数据不足的指标直接说明不可评估，不要编造具体数值）。"
    )
    return await _llm_text(prompt, max_tokens=300)


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


async def _product_type_insight(device_name: str, type_summaries: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """把各型号的批次数+特征摘要交给LLM+知识库，判断这个形状聚类像不像真实的型号差异。"""
    if len(type_summaries) < 2:
        return None
    facts = "\n".join(f"{label}：{info['batch_count']}个循环，特征：{info['signature']}"
                      for label, info in type_summaries.items())
    kb = await _kb_async(device_name, "该设备生产的产品有哪些型号/规格，工艺参数差异是什么？")
    prompt = (
        f"设备{device_name}按生产循环的阶段时长形状聚出以下分组：\n{facts}\n\n"
        + (f"知识库参考：{kb[:400]}\n\n" if kb else "")
        + "请用2-3句话判断这个分组像不像真实存在的不同产品型号/规格，指出可能的区分依据；"
          "如果看起来只是同一型号的正常波动也请直说（不要编造具体型号名称，没有知识库信息就说不确定）。"
    )
    return await _llm_text(prompt, max_tokens=200)


def _kpi_for_batches(batch_ids: List[int], batches: pd.DataFrame,
                     empty_map: Dict[int, bool], quality_map: Optional[Dict[int, bool]],
                     energy_map: Dict[int, float],
                     std_cycle_min: Optional[float] = None) -> Dict[str, Any]:
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

    # 性能效率 = 标准节拍 ÷ 实际平均节拍。
    # 标准节拍是配置里冻结的固定基准（首次用 P10 自动标定后不再变），不是当前窗口的 P10 ——
    # 用当前窗口 P10 是自参照：设备整体变慢时 P10 跟着一起变慢，performance 数值不动，
    # 劣化和改善都看不出来，而持续改善恰恰需要一个不动的基准（标准作业）。
    if std_cycle_min and cycle_mean:
        performance = round(std_cycle_min / cycle_mean, 3)
        # >1 说明实际比标准还快 —— 不截断，它是"标准该重新标定了"的信号
        perf_basis = f"标准节拍 {std_cycle_min} 分钟"
    else:
        performance = None
        perf_basis = "未标定标准节拍"

    valid_energy = sum(energy_map.get(b, 0.0) for b in valid_batches)
    empty_batches = [b for b in batch_ids if empty_map.get(b, False)]
    empty_energy = sum(energy_map.get(b, 0.0) for b in empty_batches)
    per_unit_energy = None
    if good_count:
        per_unit_energy = round(valid_energy / good_count, 3)
    elif output_count:
        per_unit_energy = round(valid_energy / output_count, 3)

    # 有效/无效(空跑)能耗占比：分母是两者之和，不是全窗口耗电——窗口里
    # 待机、离线不耗电（或耗电不计在这两类批次里），混进分母会稀释占比，
    # 看不出"空跑到底占生产用电的多大头"。
    total_energy = valid_energy + empty_energy
    valid_energy_ratio = round(valid_energy / total_energy * 100, 1) if total_energy > 0 else None
    empty_run_ratio = round(empty_energy / total_energy * 100, 1) if total_energy > 0 else None

    return {
        "total_cycles": total_batches, "output_count": output_count,
        "empty_run_count": total_batches - output_count,
        "good_count": good_count, "pass_rate": pass_rate,
        "cycle_time": {"mean_min": cycle_mean, "median_min": cycle_median, "p10_min": cycle_p10},
        "performance": performance,
        "std_cycle_min": std_cycle_min,
        "performance_basis": perf_basis,
        "energy": {"valid_kwh": round(valid_energy, 2), "empty_run_kwh": round(empty_energy, 2),
                   "valid_ratio": valid_energy_ratio, "empty_run_ratio": empty_run_ratio,
                   "per_unit_kwh": per_unit_energy},
    }


def compute_kpi_summary(db, device_code: str, pulse_param: str, days: int = 1,
                         start_time: Optional[datetime] = None,
                         end_time: Optional[datetime] = None,
                         fetched=None, shift=None) -> Dict[str, Any]:
    """Step⑤ 主入口：识别产品型号(房子形状聚类) → 按型号分别算产量(剔除空跑)/合格率/
    节拍/OEE/单件能耗 + AI语义对齐；运转率/可用率是设备级共享指标，不拆型号。

    fetched: 预取的 (seg, merged, name_map, unit_map, meter_ids)。同一个班次里
        KPI/阶段/能耗三个分析共用一次取数，避免同一份数据从库里拉三遍。
    shift:   本次分析对应的班次窗口。给了就用「班次计划生产时间」当可用率的分母，
        这才是标准 OEE 的定义；不给则退回「在线时长」口径。
    """
    if start_time and end_time:
        end = end_time
        start = start_time
    else:
        end = datetime.now()
        start = end - timedelta(days=days)

    if fetched is None:
        fetched = _fetch_batches_and_data(db, device_code, start, end, pulse_param)
    if fetched is None:
        return {"error": "no_data", "step": 5, "msg": "该窗口内无脉搏参数数据，无法计算KPI。"}
    seg, merged, name_map, unit_map, _meter_ids = fetched

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

    # 标准节拍：配置里有就用配置的（冻结基准）；没有就用当前窗口有效批次的 P10
    # 首次自动标定并写回配置，之后不再随窗口变化 —— 这样设备变慢时 performance
    # 才会真的下降。标 source=auto 提示工艺确认，工艺改过的记 manual 不再自动覆盖。
    std_cycle = kpi_cfg.get("std_cycle_min")
    std_cycle_source = kpi_cfg.get("std_cycle_source")
    if std_cycle is None:
        _valid_dur = batches[batches["batch"].isin(
            [b for b in all_batches if not empty_map.get(b, False)])]["dur_min"]
        if len(_valid_dur) >= 3:
            std_cycle = round(float(_valid_dur.quantile(0.1)), 2)
            std_cycle_source = "auto"
            try:
                save_kpi_config(conn, device_code, std_cycle_min=std_cycle,
                                std_cycle_source="auto", user="auto-calibration")
            except Exception as e:
                print(f"[KPI] 标准节拍自动标定写入失败（不影响本次计算）: {e}")

    # 运转率/可用率：设备运行状态本身跟产品型号无关，直接复用 Step③ 的判断，不拆型号。
    # 取 operation_rate（运行 ÷ 在线时长）而非 utilization（运行 ÷ 日历时长）：
    # 后者把断档/关机也算进分母，那是 TEEP 的口径，不是 OEE 的可用率。
    # analyze_state_from_pulse 自己导出的 "availability" 字段就是 operation_rate，
    # 这里原先误取了 utilization，导致 OEE 被系统性低估。
    state = analyze_state_from_pulse(conn, device_code, device_name, pulse_param, days=days,
                                     start_time=start_time, end_time=end_time)
    availability = state.get("availability") if isinstance(state, dict) else None
    utilization = state.get("utilization") if isinstance(state, dict) else None
    availability_basis = "运行时长 ÷ 在线时长（已排除断档/关机）"

    # 有班次上下文时，可用率改用标准 OEE 定义：运行时长 ÷ 计划生产时间(班次时长)。
    # 班次内的关机/断档本来就是停机损失，不该从分母里排除掉 —— 排除了算出来的
    # 是"设备开着的时候干得怎么样"，不是"这个班次产能利用得怎么样"。
    if shift is not None:
        running_h = state.get("running_hours") if isinstance(state, dict) else None
        planned_h = shift.hours
        if running_h is not None and planned_h and planned_h > 0:
            availability = round(running_h / planned_h * 100, 1)
            availability_basis = f"运行时长 ÷ 班次计划生产时间（{round(planned_h, 2)} 小时）"

    # 产品型号识别：房子形状持续性变化检测
    _t = tuning.load(conn, device_code)
    type_map = _detect_product_types(seg, batches,
                                     similarity_threshold=_t["type_shape_similarity"],
                                     persistence=_t["type_persistence"])
    types_present: List[str] = []
    for b in all_batches:
        label = type_map.get(b)
        if label and label not in types_present:
            types_present.append(label)

    def _finalize(batch_ids: List[int], label: str) -> Dict[str, Any]:
        kpi = _kpi_for_batches(batch_ids, batches, empty_map, quality_map, energy_map,
                               std_cycle_min=std_cycle)
        kpi["type_label"] = label
        kpi["availability"] = availability
        # 两个口径都给出来，避免"OEE 40%"被误读成设备有大问题：
        # availability  = 运行 ÷ 在线时长（排除断档/关机）—— OEE 用
        # utilization   = 运行 ÷ 日历时长（含一切停机）  —— 这是 TEEP，老板视角
        kpi["utilization"] = utilization
        kpi["availability_basis"] = availability_basis
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

    overall = _finalize(all_batches, "整体")

    # 各型号解读 + 整体解读 + 型号划分判断，一次并发跑完。
    # 原来是逐个 asyncio.run 串行等待：N 个型号就是 (N+1) 次 KB + (N+1) 次 LLM 顺序排队，
    # 而其中的 KB 问题还是同一个常量（现已由 query_knowledge_base 缓存去重）。
    _targets = product_types + [overall]
    _has_types = len(types_present) >= 2

    def _make(i):
        if i < len(_targets):
            return _kpi_ai_insight(device_name, _targets[i])
        return _product_type_insight(device_name, type_signature_summaries)

    _insights = _run_concurrently(_make, len(_targets) + (1 if _has_types else 0))
    for kpi, ins in zip(_targets, _insights):
        kpi["ai_insight"] = ins
    if _has_types:
        type_insight = _insights[-1]

    return _sanitize_nan({
        "step": 5,
        "device_code": device_code,
        "device_name": device_name,
        "window": {"start": start.strftime("%Y-%m-%d %H:%M:%S"), "end": end.strftime("%Y-%m-%d %H:%M:%S")},
        "empty_run_ratio_used": kpi_cfg["empty_run_ratio"],
        "std_cycle": {
            "min": std_cycle,
            "source": std_cycle_source,          # auto=自动标定 / manual=工艺确认
            "calibrated_at": kpi_cfg.get("std_cycle_at"),
            # 多型号设备的提醒：不同产品节拍本就不同，设备级单一基准会失真
            "multi_type_warning": len(types_present) >= 2,
        },
        "product_types": product_types,
        "type_insight": type_insight,
        "overall": overall,
    })


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


def _stage_energy_cpk(stage_values: Dict[int, List[float]], cpk_target: float = 1.33,
                      filter_pct: float = 0.30) -> Dict[int, Dict[str, Any]]:
    """按阶段，对跨批次能耗序列做中位数过滤 + CPK=1.33 反算规格限，识别单阶段能耗波动。

    算法跟 _stage_duration_cpk 完全一致(只是数据源从阶段时长换成阶段能耗)，
    同样不需要人工预先配置能耗规格限——没有规格限时用 CPK=1.33 反算出隐含的
    上下限，超出这个隐含范围的批次就计入"超差"。
    """
    result: Dict[int, Dict[str, Any]] = {}
    for stage, vals in stage_values.items():
        vals = [v for v in vals if v is not None]
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
        spec_low, spec_high = round(mu - k * sigma, 3), round(mu + k * sigma, 3)
        cpk_info = param_profile.compute_cpk(mu, sigma, spec_low, spec_high)
        out_of_spec = sum(1 for v in vals if v < spec_low or v > spec_high)
        result[stage] = {
            "n": n, "mean_kwh": round(mu, 3), "std_kwh": round(sigma, 3),
            "spec_low_kwh": spec_low, "spec_high_kwh": spec_high,
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
        vals = grp["v"].dropna().tolist()
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


async def _stage_ai_insight(device_name: str, stage: int, entry: Dict[str, Any]) -> Optional[str]:
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
    ecpk = entry.get("energy_cpk") or {}
    if ecpk.get("cpk") is not None:
        lines.append(f"阶段能耗均值{ecpk.get('mean_kwh')}kWh(±{ecpk.get('std_kwh')})，"
                     f"CPK={ecpk.get('cpk')}，超差{ecpk.get('out_of_spec_ratio')}%")
    elif entry.get("energy_avg") is not None:
        lines.append(f"阶段平均能耗：{entry['energy_avg']}")
    facts = "\n".join(lines)

    kb = await _kb_async(device_name, f"该设备第{stage}阶段的工艺标准和常见异常是什么？")
    prompt = (
        f"{facts}\n\n" + (f"知识库参考：{kb[:400]}\n\n" if kb else "")
        + "请用2-3句话指出该阶段是否存在需要关注的异常，以及可能的根因/保养建议"
          "（60字以内，没有异常就说正常，不要编造数据）。"
    )
    return await _llm_text(prompt, max_tokens=150)


def _stage_energy_interp(conn, meter_ids: List[str], seg: pd.DataFrame,
                         start: datetime, end: datetime) -> Dict[str, Dict[str, Any]]:
    """各阶段平均能耗 —— 与 Step⑦ 能耗Tab 完全同一套算法：按电表分开，在累计
    读数曲线上插值取阶段边界差（工具函数定义在下方 Step⑦ 段落）。

    返回 {meter_id: {point, point_name, stages:{stage:avg_kwh}, dropped:{stage:剔除次数},
    stage_values:{stage:[逐次能耗值]}}}，只含窗口内有数据的电表，顺序同 meter_ids。
    stage_values 保留逐批次原始值(不只是均值)，供 _stage_energy_cpk 反算规格限用。

    每台电表只取一个点位（主 ene_eptotal 优先，无数据才退辅 ene_imp），
    避免把两种口径的电能叠加成一个没有意义的数。
    """
    if not meter_ids:
        return {}
    energy_df = _fetch_energy_series(conn, meter_ids, start, end)
    if energy_df.empty:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for mid in meter_ids:
        mdf = energy_df[energy_df["device_id"] == mid]
        if mdf.empty:
            continue
        for p in (_PRIMARY, _SECONDARY):
            sub = mdf[mdf["p_name"] == p].sort_values("gather_time")
            if sub.empty:
                continue
            x = sub["gather_time"].map(lambda t: pd.Timestamp(t).value).to_numpy(dtype="int64")
            y = sub["v"].to_numpy(dtype=float)
            acc: Dict[int, Dict[str, Any]] = {}
            for _, r in seg.iterrows():
                st = int(r["stage"])
                a = acc.setdefault(st, {"sum": 0.0, "cnt": 0, "drop": 0, "values": []})
                d = _interp_delta(x, y, r["t_start"].to_pydatetime(), r["t_end"].to_pydatetime())
                if d is None:          # 电表回绕/重置：剔除并计数，不让它污染均值
                    a["drop"] += 1
                else:
                    a["sum"] += d
                    a["cnt"] += 1
                    a["values"].append(d)
            out[mid] = {
                "point": p,
                "stage_values": {st: a["values"] for st, a in acc.items() if a["cnt"]},
                "point_name": _ENERGY_POINT_NAMES.get(p, p),
                "stages": {st: round(a["sum"] / a["cnt"], 3) for st, a in acc.items() if a["cnt"]},
                "dropped": {st: int(a["drop"]) for st, a in acc.items() if a["drop"]},
            }
            break
    return out


def compute_stage_cpk(db, device_code: str, pulse_param: str, days: int = 7,
                       start_time: Optional[datetime] = None,
                       end_time: Optional[datetime] = None,
                       fetched=None) -> Dict[str, Any]:
    """Step⑥ 主入口：阶段时长CPK + 参数CPK(已确认规格限) + 阶段能耗 + 分阶段AI语义对齐。

    fetched: 预取数据，与 KPI/能耗 共用一次取数（见 compute_kpi_summary）。
    """
    if start_time and end_time:
        end = end_time
        start = start_time
    else:
        end = datetime.now()
        start = end - timedelta(days=days)

    if fetched is None:
        fetched = _fetch_batches_and_data(db, device_code, start, end, pulse_param)
    if fetched is None:
        return {"error": "no_data", "step": 6, "msg": "该窗口内无脉搏参数数据，无法按阶段分析。"}
    seg, merged, name_map, unit_map, meter_ids = fetched

    conn = db.conn
    device_name = db_device_name(db, device_code)
    _t = tuning.load(conn, device_code)

    # 掐头去尾：跟②能耗Tab同一原则——窗口内时间最早/最晚的批次(周期)通常被窗口
    # 边界截断，不是完整周期，独立按本次窗口掐掉再参与统计；样本太少(≤2批)时
    # 无法掐头去尾，保留全部避免分母为 0。
    # 阶段0(待机码，即该设备最小阶段码)不算"阶段"——批次的定义是"待机段+其后的
    # 运行段"(_build_segments)，待机段本身不代表任何工艺阶段，不该进时长/参数/
    # 能耗统计，也不该在结果里单独出现一张"阶段0"卡片。
    min_code = int(seg["stage"].min())
    all_batches = sorted(seg["batch"].unique().tolist())
    if len(all_batches) > 2:
        keep_batches = set(all_batches[1:-1])
        boundary_dropped_batch_ids = [int(all_batches[0]), int(all_batches[-1])]
    else:
        keep_batches = set(all_batches)
        boundary_dropped_batch_ids = []
    seg_f = seg[seg["batch"].isin(keep_batches) & (seg["stage"] != min_code)].copy()
    merged_f = merged[merged["batch"].isin(keep_batches) & (merged["stage"] != min_code)].copy()

    duration_cpk = _stage_duration_cpk(seg_f, cpk_target=_t["cpk_target"],
                                       filter_pct=_t["cpk_filter_pct"])
    confirmed = param_profile.get_confirmed_map(conn, device_code)

    # 阶段能耗与 Step⑦ 能耗Tab 用同一套算法（按电表分开 + 累计曲线插值），
    # 否则同一个"阶段能耗"在两个 Tab 会给出不同数字，现场无从判断信哪个。
    energy_meters = _stage_energy_interp(conn, meter_ids, seg_f, start, end)
    primary_meter = next(iter(energy_meters), None)
    stage_energy: Dict[int, float] = energy_meters[primary_meter]["stages"] if primary_meter else {}
    # 单阶段能耗波动：跟阶段时长同一套 CPK+超差算法，只对主电表算（多电表口径不一，
    # 混在一起算 CPK 没有物理意义），辅电表仍只在 energy_by_meter 里给均值参考。
    stage_energy_cpk: Dict[int, Dict[str, Any]] = (
        _stage_energy_cpk(energy_meters[primary_meter]["stage_values"],
                          cpk_target=_t["cpk_target"], filter_pct=_t["cpk_filter_pct"])
        if primary_meter else {}
    )

    energy_points = [p for p in (_PRIMARY, _SECONDARY) if (merged["p_name"] == p).any()]
    param_stats = _stage_param_stats(merged_f, confirmed, name_map, unit_map,
                                     exclude_params=set(energy_points))

    stages_out = []
    for stage in sorted(seg_f["stage"].unique().tolist()):
        stage = int(stage)
        entry = {
            "stage": stage,
            "duration_cpk": duration_cpk.get(stage),
            "param_stats": param_stats.get(stage, {}),
            "energy_avg": stage_energy.get(stage),
            "energy_cpk": stage_energy_cpk.get(stage),
            # 能耗归属到具体电表，并报出因回绕被剔除的次数（口径与②能耗Tab一致）
            "energy_meter": primary_meter,
            "energy_dropped": (energy_meters[primary_meter]["dropped"].get(stage) if primary_meter else None),
            "energy_by_meter": ({mid: v["stages"].get(stage) for mid, v in energy_meters.items()}
                                if len(energy_meters) > 1 else None),
        }
        stages_out.append(entry)

    # 各阶段的 AI 解读并发跑：原来逐阶段 asyncio.run，8 个阶段就是 8 次 KB + 8 次 LLM
    # 顺序排队，整个④阶段 Tab 的等待时间和阶段数成正比。
    _ins = _run_concurrently(
        lambda i: _stage_ai_insight(device_name, stages_out[i]["stage"], stages_out[i]),
        len(stages_out))
    for entry, ins in zip(stages_out, _ins):
        entry["ai_insight"] = ins

    return _sanitize_nan({
        "step": 6,
        "device_code": device_code,
        "device_name": device_name,
        "stage_param": {"p_name": pulse_param, "display_name": name_map.get(pulse_param, pulse_param)},
        "lawn_code": min_code,
        "boundary_dropped_batch_ids": boundary_dropped_batch_ids,
        "energy_meters": [
            {"meter_id": mid, "point": v["point"], "point_name": v["point_name"]}
            for mid, v in energy_meters.items()
        ],
        "stages": stages_out,
    })


# ══════════════════════════════════════════════════════════
# Step⑦ 能耗拆解：按"房子"(合膏一个完整生产周期) 列出每房子能耗，
# 并拆解房内每个阶段的能耗。组合有功总电能(ene_eptotal) 为主，
# 正向有功电能(ene_imp) 为辅。电表为累计读数，用线性插值取阶段边界值做差。
# ══════════════════════════════════════════════════════════

_PRIMARY = "ene_eptotal"   # 组合有功总电能（主）
_SECONDARY = "ene_imp"     # 正向有功电能（辅）
_ENERGY_POINT_NAMES = {_PRIMARY: "组合有功总电能", _SECONDARY: "正向有功电能"}


def _fetch_energy_series(conn, meter_ids: List[str], start: datetime, end: datetime) -> pd.DataFrame:
    """直接从 device_energy_info 拉电表累计读数长表(不经过 _attach，保留完整累计曲线供插值)。

    必须带出 device_id：一台设备可能关联多个电表(如固化室A/B区各一个)，每个电表
    有自己独立的累计读数曲线。把多台电表的读数混成一条曲线再插值是没有物理意义的
    （交错的两条递增曲线插出来的差值既不是A也不是B），所以调用方必须按 device_id
    分组后再各自插值。
    """
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '300s'")
    conn.commit()
    sql = """
        SELECT e.device_id, e.point_id AS p_name, e.point_time AS gather_time,
               e.point_value::double precision AS v
        FROM device_energy_info e
        WHERE e.device_id = ANY(%s)
          AND e.point_id = ANY(%s)
          AND e.point_time >= %s AND e.point_time < %s
        ORDER BY e.device_id, e.point_time
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (meter_ids, [_PRIMARY, _SECONDARY], start, end))
        rows = cur.fetchall()
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["device_id", "p_name", "gather_time", "v"])
    if not df.empty:
        df["gather_time"] = pd.to_datetime(df["gather_time"])
    return df


def _interp_delta(series_x: np.ndarray, series_y: np.ndarray,
                  t_start: datetime, t_end: datetime) -> Optional[float]:
    """在累计曲线上线性插值取 t_end 与 t_start 的差(=该时段能耗)。
    series_x 升序 epoch 纳秒(int64)，series_y 对应累计读数。delta<0(电表回绕/重置)返回 None。
    注意：series_x 与边界时刻都用 pandas Timestamp.value(ns)，口径一致，避免本地时区偏移。"""
    if len(series_x) == 0:
        return None
    if len(series_x) == 1:
        return 0.0
    xs, xe = pd.Timestamp(t_start).value, pd.Timestamp(t_end).value
    v_end = float(np.interp(xe, series_x, series_y))
    v_start = float(np.interp(xs, series_x, series_y))
    delta = v_end - v_start
    return round(float(delta), 4) if delta >= 0 else None


def _meter_breakdown(houses_seg: pd.DataFrame, idle_seg: pd.DataFrame, series: Dict[str, Any],
                     has_primary: bool, has_secondary: bool,
                     code2name: Dict[int, str]) -> Dict[str, Any]:
    """单个电表的房子/阶段能耗拆解。houses_seg 是设备级的房子切分(与电表无关)，
    idle_seg 是同一设备的待机(草坪)分段(与电表无关)，series 只含该电表自己的
    累计曲线，保证插值口径干净。"""

    def _deltas(t0, t1):
        return {
            "primary_kwh": _interp_delta(series[_PRIMARY][0], series[_PRIMARY][1], t0, t1) if has_primary else None,
            "secondary_kwh": _interp_delta(series[_SECONDARY][0], series[_SECONDARY][1], t0, t1) if has_secondary else None,
        }

    # 掐头去尾：本次窗口(班次/天)里时间最早和最晚的房子通常被窗口边界截断，
    # 不是完整周期，会拉偏均值——独立按本次窗口掐掉，不是对用户选的整个日期
    # 范围只掐一次。样本太少(≤2栋)时无法掐头去尾，保留全部避免均值分母为 0。
    all_ids = sorted(houses_seg["house_id"].unique().tolist())
    if len(all_ids) > 2:
        keep_ids = set(all_ids[1:-1])
        boundary_dropped_house_ids = [int(all_ids[0]), int(all_ids[-1])]
    else:
        keep_ids = set(all_ids)
        boundary_dropped_house_ids = []
    houses_seg = houses_seg[houses_seg["house_id"].isin(keep_ids)]

    houses_out = []
    # stage -> 累加器。dur/dur_cnt 与能耗用同一套 segment 计数，保证
    # 平均时长和平均能耗分母一致（否则一栋房子内同一阶段出现多次时，
    # 两个均值口径不同，相除算出来的功率是错的）。
    stage_accum: Dict[int, Dict[str, float]] = {}
    for hid, grp in houses_seg.groupby("house_id"):
        grp = grp.sort_values("t_start")
        t0, t1 = grp["t_start"].min().to_pydatetime(), grp["t_end"].max().to_pydatetime()
        dur_min = round((t1 - t0).total_seconds() / 60, 2)
        house = {
            "house_id": int(hid),
            "t_start": t0.strftime("%Y-%m-%d %H:%M:%S"),
            "t_end": t1.strftime("%Y-%m-%d %H:%M:%S"),
            "dur_min": dur_min,
            **_deltas(t0, t1),
            "stages": [],
        }
        for _, r in grp.iterrows():
            st = int(r["stage"])
            s0, s1 = r["t_start"].to_pydatetime(), r["t_end"].to_pydatetime()
            s_dur = round((s1 - s0).total_seconds() / 60, 2)
            d = _deltas(s0, s1)
            house["stages"].append({
                "stage": st,
                "name": code2name.get(st, f"阶段{st}"),
                "dur_min": s_dur,
                **d,
            })
            acc = stage_accum.setdefault(st, {"p": 0.0, "s": 0.0, "dur": 0.0,
                                              "p_cnt": 0, "s_cnt": 0, "dur_cnt": 0,
                                              "houses": set()})
            acc["dur"] += s_dur
            acc["dur_cnt"] += 1
            acc["houses"].add(int(hid))
            if d["primary_kwh"] is not None:
                acc["p"] += d["primary_kwh"]; acc["p_cnt"] += 1
            if d["secondary_kwh"] is not None:
                acc["s"] += d["secondary_kwh"]; acc["s_cnt"] += 1
        houses_out.append(house)

    stage_summary = []
    for st in sorted(stage_accum):
        acc = stage_accum[st]
        stage_summary.append({
            "stage": st,
            "name": code2name.get(st, f"阶段{st}"),
            "appear_count": len(acc["houses"]),        # 出现过该阶段的房子数
            "segment_count": acc["dur_cnt"],           # 该阶段出现的总次数(可>房子数)
            "avg_primary_kwh": round(acc["p"] / acc["p_cnt"], 4) if acc["p_cnt"] else None,
            "avg_secondary_kwh": round(acc["s"] / acc["s_cnt"], 4) if acc["s_cnt"] else None,
            "avg_dur_min": round(acc["dur"] / acc["dur_cnt"], 2) if acc["dur_cnt"] else None,
            # 均值只按有效次数算，这里报出被剔除的次数，避免分母悄悄变小
            "primary_drop_count": (acc["dur_cnt"] - acc["p_cnt"]) if has_primary else 0,
            "secondary_drop_count": (acc["dur_cnt"] - acc["s_cnt"]) if has_secondary else 0,
        })

    # 能耗为 None ＝ 电表累计读数回绕/重置(delta<0)被剔除：
    # has_primary/has_secondary 为真时该曲线必定非空，_interp_delta 不会因缺数据返回 None，
    # 所以这里的 None 只有回绕这一个来源。合计/均值只用有效房子，
    # 同时把剔除的房子数报给前端 —— 分母变小必须是看得见的。
    valid_p = [h["primary_kwh"] for h in houses_out if h["primary_kwh"] is not None]
    valid_s = [h["secondary_kwh"] for h in houses_out if h["secondary_kwh"] is not None]

    # 有效/无效能耗：房子(非待机阶段)＝运行＝有效能耗；待机(草坪)分段＝非运行＝
    # 无效能耗。待机分段与房子内阶段用同一套插值口径(_deltas)，回绕(delta<0)
    # 同样记为 None 并单独报剔除数，不悄悄拉低总量。
    idle_deltas_p, idle_deltas_s = [], []
    for _, r in idle_seg.iterrows():
        s0, s1 = r["t_start"].to_pydatetime(), r["t_end"].to_pydatetime()
        d = _deltas(s0, s1)
        if has_primary and d["primary_kwh"] is not None:
            idle_deltas_p.append(d["primary_kwh"])
        if has_secondary and d["secondary_kwh"] is not None:
            idle_deltas_s.append(d["secondary_kwh"])
    idle_seg_count = len(idle_seg)

    return {
        "houses": houses_out,
        "summary": {
            "house_count": len(houses_out),
            "boundary_dropped_house_ids": boundary_dropped_house_ids,
            "total_primary_kwh": round(sum(valid_p), 4) if valid_p else None,
            "total_secondary_kwh": round(sum(valid_s), 4) if valid_s else None,
            "avg_primary_kwh": round(sum(valid_p) / len(valid_p), 4) if valid_p else None,
            "avg_secondary_kwh": round(sum(valid_s) / len(valid_s), 4) if valid_s else None,
            # 有效/剔除房子数：均值和合计的真实分母
            "primary_valid_house_count": len(valid_p) if has_primary else None,
            "primary_dropped_house_count": (len(houses_out) - len(valid_p)) if has_primary else 0,
            "secondary_valid_house_count": len(valid_s) if has_secondary else None,
            "secondary_dropped_house_count": (len(houses_out) - len(valid_s)) if has_secondary else 0,
            "stage_summary": stage_summary,
            # 运行(房子)＝有效能耗；待机(草坪)＝无效能耗——与 total_*_kwh 同口径，
            # 只是换个名字明确"运行/非运行"语义，数值上 valid_*_kwh == total_*_kwh。
            "valid_primary_kwh": round(sum(valid_p), 4) if valid_p else None,
            "valid_secondary_kwh": round(sum(valid_s), 4) if valid_s else None,
            "invalid_primary_kwh": round(sum(idle_deltas_p), 4) if idle_deltas_p else None,
            "invalid_secondary_kwh": round(sum(idle_deltas_s), 4) if idle_deltas_s else None,
            "invalid_primary_drop_count": (idle_seg_count - len(idle_deltas_p)) if has_primary else 0,
            "invalid_secondary_drop_count": (idle_seg_count - len(idle_deltas_s)) if has_secondary else 0,
        },
    }


def compute_energy_breakdown(db, device_code: str, pulse_param: str, days: int = 1,
                             start_time: Optional[datetime] = None,
                             end_time: Optional[datetime] = None,
                             selected_points: Optional[List[str]] = None,
                             fetched=None) -> Dict[str, Any]:
    """Step⑦ 主入口：每房子(生产周期)能耗 + 房内每阶段能耗拆解。

    房子 = 脉搏阶段参数的连续非"待机码"段(0值=草坪不算房子)。
    能耗 = 关联电表累计读数在房子/阶段起止时刻的线性插值差。
    selected_points: 前端"参数筛选"勾选的能耗点位(子集 of [ene_eptotal, ene_imp])。
        None=两个都用(向后兼容)；空列表=未勾选任何能耗点位→返回 no_energy_selected。
        只计算/返回被勾选且有数据的点位(ene_eptotal 为主、ene_imp 为辅)。
    """
    if start_time and end_time:
        end, start = end_time, start_time
    else:
        end = datetime.now()
        start = end - timedelta(days=days)

    # 确定要处理的能耗点位(按 主→辅 优先级)
    whitelist = [_PRIMARY, _SECONDARY]
    if selected_points is None:
        active = list(whitelist)
    else:
        sel = set(selected_points)
        active = [p for p in whitelist if p in sel]
        if not active:
            return {"error": "no_energy_selected", "step": 7,
                    "msg": "未勾选任何能耗参数。请在①状态&效率页的参数筛选中勾选 ene_eptotal 或 ene_imp。"}

    meter_ids = db.get_energy_device_ids(device_code)
    if not meter_ids:
        return {"error": "no_meter", "step": 7,
                "msg": "该设备未关联电表(device_energy_meter)，无法计算能耗。"}

    if fetched is None:
        fetched = _fetch_batches_and_data(db, device_code, start, end, pulse_param, meter_ids=meter_ids)
    if fetched is None:
        return {"error": "no_data", "step": 7, "msg": "该窗口内无脉搏参数数据，无法识别房子周期。"}
    seg, _merged, name_map, _unit_map, _mids = fetched

    conn = db.conn
    device_name = db_device_name(db, device_code)

    # 阶段码 -> 状态名(出料/进铅粉/加酸反应...)，来自界面配置或 STATE_GROUPS 默认
    code2name: Dict[int, str] = {}
    groups, _src = load_state_groups(conn, device_code)
    if groups:
        for nm, codes in groups:
            for c in codes:
                code2name[int(c)] = nm

    # 识别"房子"：连续非待机码(最小码)段为一栋房子。
    # 房子切分来自脉搏参数，是设备级的，与电表无关 —— 只算一次，各电表共用。
    min_code = int(seg["stage"].min())
    s = seg.sort_values("t_start").reset_index(drop=True)
    is_lawn = s["stage"].eq(min_code)
    new_house = (~is_lawn) & (is_lawn.shift(fill_value=True))
    s["house_id"] = new_house.cumsum()
    houses_seg = s[~is_lawn].copy()
    idle_seg = s[is_lawn].copy()
    if houses_seg.empty:
        return {"error": "no_house", "step": 7, "msg": "该窗口内未识别到生产周期(房子)。"}

    # 逐个电表独立计算：每台电表有自己的累计读数曲线，混在一起插值没有物理意义。
    # 这里也不做跨电表求和 —— 现场电表覆盖并不完整，合计口径另行处理，
    # 页面按电表逐个看。
    energy_df = _fetch_energy_series(conn, meter_ids, start, end)
    meters_out: List[Dict[str, Any]] = []
    for mid in meter_ids:
        mdf = energy_df[energy_df["device_id"] == mid] if not energy_df.empty else energy_df
        series: Dict[str, Any] = {}
        for p in active:
            sub = mdf[mdf["p_name"] == p].sort_values("gather_time") if not mdf.empty else mdf
            if sub.empty:
                series[p] = (np.array([]), np.array([]))
            else:
                # 用 Timestamp.value(纳秒) 取 epoch，避免 pandas 不同版本 datetime64[ns/us] 精度差
                x = sub["gather_time"].map(lambda t: pd.Timestamp(t).value).to_numpy(dtype="int64")
                y = sub["v"].to_numpy(dtype=float)
                series[p] = (x, y)
        has_primary = _PRIMARY in active and len(series.get(_PRIMARY, (np.array([]),))[0]) > 0
        has_secondary = _SECONDARY in active and len(series.get(_SECONDARY, (np.array([]),))[0]) > 0
        if not (has_primary or has_secondary):
            continue  # 该电表在本窗口无数据，不列出

        bd = _meter_breakdown(houses_seg, idle_seg, series, has_primary, has_secondary, code2name)
        meters_out.append({
            "meter_id": mid,
            "energy_points": {
                "primary": {"p_name": _PRIMARY, "display_name": _ENERGY_POINT_NAMES[_PRIMARY], "has_data": has_primary},
                "secondary": {"p_name": _SECONDARY, "display_name": _ENERGY_POINT_NAMES[_SECONDARY], "has_data": has_secondary},
            },
            **bd,
        })

    if not meters_out:
        return {"error": "no_energy_data", "step": 7,
                "msg": "勾选的能耗参数在该窗口内无数据。"}

    return _sanitize_nan({
        "step": 7,
        "device_code": device_code,
        "device_name": device_name,
        "stage_param": {"p_name": pulse_param, "display_name": name_map.get(pulse_param, pulse_param)},
        "meter_ids": meter_ids,
        "lawn_code": min_code,
        "meters": meters_out,
    })
