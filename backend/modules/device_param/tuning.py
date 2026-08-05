# cython: annotation_typing=False, infer_types=False, language_level=3
"""可调参数集中配置（按设备）。

这些阈值原本散在各个函数体里硬编码：脉冲检测的 0.5/0.3、同变分组的 0.8、
产品型号的 0.85/3、阶段 CPK 的 1.33/0.30、离线判定的 10 分钟……
工艺想调一个值就得改代码重新部署，等于没有"标准作业"可言 —— 标准必须是
工艺自己能看见、能改、能追溯的东西，而不是埋在源码里的字面量。

用法：
    cfg = tuning.load(conn, device_code)
    if score > cfg["pulse_step_score"]: ...

未配置的设备自动拿默认值，因此可以安全地在任何地方调用。
"""
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json, RealDictCursor

# (键, 默认值, 类型, 中文名, 说明, 最小值, 最大值)
_SPEC = [
    # ── 脉冲/节拍识别 ──
    ("pulse_step_score", 0.5, float, "脉冲阶梯度阈值",
     "波形有多像阶梯状才算脉冲型。调低会把更多参数认成脉搏", 0.0, 1.0),
    ("pulse_cycle_score", 0.3, float, "脉冲周期性阈值",
     "循环规律性达到多少才算脉冲型", 0.0, 1.0),
    ("pulse_min_points", 50, int, "脉冲检测最少点数",
     "少于这个点数不做脉冲检测（样本不足判不准）", 10, 100000),

    # ── 同变参数分组 ──
    ("co_change_jaccard", 0.8, float, "同步变化相似度阈值",
     "两个参数的跳变时刻重合到什么程度算「同步变化」（配方切换时整组刷新）", 0.1, 1.0),
    ("co_change_min_transitions", 4, int, "同变最少跳变次数",
     "跳变次数少于此值的参数不参与同变分组，避免偶然重合", 2, 1000),
    ("co_change_bucket_sec", 10, int, "同变时刻对齐窗口(秒)",
     "两个参数的跳变时刻相差多少秒内算同一时刻", 1, 600),

    # ── 产品型号识别 ──
    ("type_shape_similarity", 0.85, float, "型号形状相似度阈值",
     "两个生产循环的阶段时长轮廓相似到什么程度算同一型号", 0.5, 1.0),
    ("type_persistence", 3, int, "型号切换确认次数",
     "连续多少个循环出现新形状才确认换型号（防止单次异常被当成换型）", 1, 50),

    # ── 阶段 CPK ──
    ("cpk_target", 1.33, float, "CPK 目标值",
     "反推规格限用的目标过程能力指数，行业常用 1.33", 0.5, 3.0),
    ("cpk_filter_pct", 0.30, float, "CPK 中位数过滤比例",
     "偏离中位数超过这个比例的批次不参与 CPK 计算（剔除异常批）", 0.05, 0.9),

    # ── 状态划分 ──
    ("offline_gap_min", 10, int, "离线判定间隔(分钟)",
     "采样断档超过这么久就判为设备离线（没通电/没联网）", 1, 1440),

    # ── 空跑判定 ──
    ("empty_run_ratio", 0.30, float, "空跑判定阈值",
     "批次内物料重量峰值低于历史中位值的这个比例视为空跑", 0.01, 1.0),

    # ── 取数与展示 ──
    ("screen_per_param_limit", 10000, int, "筛选每参数取样上限",
     "参数筛选时每个参数最多取多少个点", 100, 200000),
    ("stale_lookback_limit", 500, int, "历史回退取样条数",
     "近期无数据的参数，回退取多少条历史数据来判断形态", 50, 10000),
    ("ai_top_params", 8, int, "AI 分析参数个数",
     "提交给 AI 做整体分析的参数个数（只挑波动最大的）", 1, 50),
    ("flat_range_ratio", 0.01, float, "恒定判定极差比",
     "极差占均值的比例低于此值视为恒定不变", 0.0001, 0.5),
]

DEFAULTS: Dict[str, Any] = {k: v for k, v, *_ in _SPEC}
_TYPES = {k: t for k, _, t, *_ in _SPEC}
_BOUNDS = {k: (lo, hi) for k, _, _, _, _, lo, hi in _SPEC}


def schema() -> List[Dict[str, Any]]:
    """给前端渲染配置表单用：每项的默认值、范围、中文名和说明。"""
    return [
        {"key": k, "default": d, "type": t.__name__, "label": label,
         "desc": desc, "min": lo, "max": hi}
        for k, d, t, label, desc, lo, hi in _SPEC
    ]


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_param_tuning (
                device_code VARCHAR(64) PRIMARY KEY,
                overrides   JSONB       NOT NULL DEFAULT '{}'::jsonb,
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_by  VARCHAR(128)
            )
        """)
    conn.commit()


def load(conn, device_code: str) -> Dict[str, Any]:
    """默认值 + 该设备的覆盖项。任何时候都返回完整可用的配置。"""
    cfg = dict(DEFAULTS)
    if conn is None or not device_code:
        return cfg
    try:
        ensure_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT overrides FROM device_param_tuning WHERE device_code=%s",
                        (device_code,))
            row = cur.fetchone()
        for k, v in ((row or {}).get("overrides") or {}).items():
            if k in cfg and v is not None:
                cfg[k] = _coerce(k, v)
    except Exception as e:
        # 读配置失败绝不能拖垮分析：默认值本来就是能跑的
        print(f"[调参] 读取失败，使用默认值 device={device_code}: {e}")
    return cfg


def _coerce(key: str, value: Any) -> Any:
    t = _TYPES.get(key, float)
    try:
        v = t(value)
    except (TypeError, ValueError):
        return DEFAULTS[key]
    lo, hi = _BOUNDS.get(key, (None, None))
    if lo is not None and v < lo:
        return lo
    if hi is not None and v > hi:
        return hi
    return v


def validate(overrides: Dict[str, Any]):
    """返回 (清洗后的覆盖项, 被忽略的键)。越界值夹到边界，未知键丢弃。"""
    clean, ignored = {}, []
    for k, v in (overrides or {}).items():
        if k not in DEFAULTS:
            ignored.append(k)
            continue
        if v is None:            # 显式置空 = 恢复默认
            continue
        clean[k] = _coerce(k, v)
    return clean, ignored


def save(conn, device_code: str, overrides: Dict[str, Any],
         user: Optional[str] = None) -> Dict[str, Any]:
    """整体覆盖该设备的调参项（只存与默认值不同的部分）。"""
    clean, _ = validate(overrides)
    # 与默认值相同的不存，保持覆盖集最小，将来改默认值能自动生效
    diff = {k: v for k, v in clean.items() if v != DEFAULTS[k]}
    ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO device_param_tuning (device_code, overrides, updated_at, updated_by)
            VALUES (%s, %s, now(), %s)
            ON CONFLICT (device_code) DO UPDATE SET
                overrides = EXCLUDED.overrides, updated_at = now(), updated_by = EXCLUDED.updated_by
        """, (device_code, Json(diff), user))
    conn.commit()
    return load(conn, device_code)
