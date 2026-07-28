# cython: annotation_typing=False, infer_types=False, language_level=3
"""趋势/漂移检测算法（纯函数，numpy 实现，不引新依赖）。

与现有 anomaly_detector（IQR+孤立森林，抓离群点）互补：本模块抓"慢漂移"——
参数（尤其温度、阶段时长）跟过去 N 天相比逐渐变大/变小。慢漂移时新值相对最近
数据始终"在范围内"，IQR 抓不到，必须用基线对比 + 单调趋势检验。

核心三件套：
  1) robust_stats   —— 中位数 / MAD / 稳健 z（抗离群批次，不用均值/标准差）
  2) mann_kendall   —— 非参单调趋势检验（判断"逐渐"，给 p 值）
  3) sens_slope     —— 趋势斜率（每单位时间变化量 = "逐渐变化值"的速率）

classify_severity 把以上信号 + 阈值配置落成 info/warning/critical。
"""

import math
from typing import List, Optional, Sequence, Tuple, Dict, Any

import numpy as np

# 1 / Φ^{-1}(0.75)，把 MAD 标定到与标准差同尺度（正态下）
_MAD_TO_SIGMA = 1.4826


def _clean(values: Sequence[Optional[float]]) -> np.ndarray:
    """剔除 None/NaN/Inf，返回 float 数组。"""
    arr = np.asarray([v for v in values
                      if v is not None and not (isinstance(v, float) and
                                                (math.isnan(v) or math.isinf(v)))],
                     dtype=float)
    return arr[np.isfinite(arr)]


def robust_stats(values: Sequence[Optional[float]]) -> Dict[str, float]:
    """中位数 / MAD / 稳健尺度。MAD=0（常量序列）时尺度回退到 1e-9 避免除零。"""
    arr = _clean(values)
    if arr.size == 0:
        return {"n": 0, "median": float("nan"), "mad": float("nan"), "scale": float("nan")}
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    scale = mad * _MAD_TO_SIGMA
    # MAD=0(常量/近常量基线)时**不**把 scale 抬到 1e-9 地板——那会让 robust_z=差值/1e-9
    # 爆炸成 1e9 级，把微小变化误判成显著漂移。保持 scale=0，robust_z 遇 scale<=0 返回 0，
    # severity 退化为仅由 change_pct 判定（无波动基线下相对变化才是可靠信号）。
    return {"n": int(arr.size), "median": med, "mad": mad, "scale": scale}


def robust_z(value: float, median: float, scale: float) -> float:
    """单值相对基线的稳健 z 分。scale 应为 robust_stats 的 scale（MAD·1.4826）。"""
    if scale is None or not math.isfinite(scale) or scale <= 0:
        return 0.0
    return float((value - median) / scale)


def change_pct(recent: float, baseline: float) -> float:
    """相对变化百分比。基线≈0 时退化为绝对差（避免除零放大）。"""
    if baseline is None or not math.isfinite(baseline):
        return 0.0
    denom = abs(baseline)
    if denom < 1e-9:
        return float(recent - baseline) * 100.0
    return float((recent - baseline) / denom * 100.0)


def mann_kendall(values: Sequence[Optional[float]]) -> Dict[str, Any]:
    """Mann-Kendall 单调趋势检验（正态近似 + tie 校正）。

    返回 {trend: up/down/none, p, S, z, n}。n<4 数据不足，返回 none。
    抗离群、无需分布假设，适合工业漂移序列。
    """
    arr = _clean(values)
    n = arr.size
    if n < 4:
        return {"trend": "none", "p": 1.0, "S": 0.0, "z": 0.0, "n": int(n)}

    # S = Σ_{i<j} sign(x_j - x_i)
    s = 0
    for i in range(n - 1):
        s += int(np.sum(np.sign(arr[i + 1:] - arr[i])))

    # 方差（含并列值 tie 校正）
    _, counts = np.unique(arr, return_counts=True)
    tie = np.sum(counts * (counts - 1) * (2 * counts + 5))
    var_s = (n * (n - 1) * (2 * n + 5) - tie) / 18.0
    if var_s <= 0:
        return {"trend": "none", "p": 1.0, "S": float(s), "z": 0.0, "n": int(n)}

    # 连续性校正
    if s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0

    # 双尾 p（标准正态），erfc 实现，避免引 scipy
    p = math.erfc(abs(z) / math.sqrt(2.0))

    if p < 0.05 and s > 0:
        trend = "up"
    elif p < 0.05 and s < 0:
        trend = "down"
    else:
        trend = "none"
    return {"trend": trend, "p": float(p), "S": float(s), "z": float(z), "n": int(n)}


def sens_slope(times: Sequence[float], values: Sequence[Optional[float]]) -> float:
    """Sen's slope：所有点对斜率的中位数（每单位时间变化量）。

    times 与 values 等长；times 用"天"为单位则斜率即"每天变化量"。
    抗离群，比最小二乘稳健。点数 < 2 返回 0。
    """
    t = np.asarray(times, dtype=float)
    v = np.asarray([np.nan if x is None else x for x in values], dtype=float)
    mask = np.isfinite(t) & np.isfinite(v)
    t, v = t[mask], v[mask]
    if t.size < 2:
        return 0.0
    slopes = []
    for i in range(t.size - 1):
        dt = t[i + 1:] - t[i]
        dv = v[i + 1:] - v[i]
        ok = dt != 0
        if np.any(ok):
            slopes.append(dv[ok] / dt[ok])
    if not slopes:
        return 0.0
    return float(np.median(np.concatenate(slopes)))


# ── 阈值配置默认值（无界面配置时） ──
DEFAULT_THRESHOLDS = {
    "baseline_days": 30,   # 基线回溯天数
    "recent_days": 3,      # 近期窗口（用于 baseline vs recent 对比）
    "min_base_days": 10,   # 基线有效天数下限，不足只给"数据不足"
    "warn_pct": 10.0,      # |相对变化| 警告阈
    "crit_pct": 20.0,      # |相对变化| 严重阈
    "warn_z": 3.0,         # |稳健 z| 警告阈
    "crit_z": 5.0,         # |稳健 z| 严重阈
}

# ── 7 天滑动窗口档（分阶段·单参数 漂移用） ──
# 窗口短(7天)，故 recent/min_base 相应收紧；z/pct 阈沿用（仍是 6σ 那套质量判据）。
WINDOW_7D = {
    **DEFAULT_THRESHOLDS,
    "baseline_days": 7,
    "recent_days": 2,
    "min_base_days": 4,
}


def classify_severity(
    change_percent: float,
    z: float,
    mk_trend: str,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """综合相对变化、稳健 z、MK 趋势，落 severity 与 direction。

    规则：先按 |change_pct| 与 |z| 取较高级别；MK 无显著趋势则最多 warning
    （避免把单纯波动判成 critical）。direction 由变化符号决定。
    """
    cfg = {**DEFAULT_THRESHOLDS, **(cfg or {})}
    ac, az = abs(change_percent), abs(z)

    level = 0  # 0 info / 1 warning / 2 critical
    if ac >= cfg["crit_pct"] or az >= cfg["crit_z"]:
        level = 2
    elif ac >= cfg["warn_pct"] or az >= cfg["warn_z"]:
        level = 1

    # 没有统计上显著的单调趋势 → 封顶 warning（可能只是阶跃/波动，非"逐渐"）
    if level == 2 and mk_trend == "none":
        level = 1

    severity = ["info", "warning", "critical"][level]
    if change_percent > 0:
        direction = "up"
    elif change_percent < 0:
        direction = "down"
    else:
        direction = "flat"
    return {"severity": severity, "direction": direction}


def detect_step_change(daily_medians: Sequence[Optional[float]],
                       baseline_scale: float) -> bool:
    """粗判"疑似阶跃/配方切换"：最后一天相对其余中位的跳变远大于历史日间跳变。

    用于给预警标 note 并降级（阶跃不是"逐渐漂移"）。daily_medians 按时间升序。
    """
    arr = _clean(daily_medians)
    if arr.size < 5 or baseline_scale is None or baseline_scale <= 0:
        return False
    last = arr[-1]
    prev = arr[:-1]
    prev_med = float(np.median(prev))
    jump = abs(last - prev_med) / baseline_scale
    # 历史日间一阶差分的稳健尺度
    diffs = np.abs(np.diff(prev))
    typical = float(np.median(diffs)) if diffs.size else 0.0
    typical_z = abs(last - prev_med) / (typical * _MAD_TO_SIGMA) if typical > 1e-9 else jump
    return bool(jump >= 6.0 and typical_z >= 6.0)
