# cython: annotation_typing=False, infer_types=False, language_level=3
"""
设备特征提取脚本 — "获取设备特征" 完整 Pipeline

数据源: TimescaleDB (PostgreSQL)，连接信息从 .env 或环境变量读取。

Pipeline:
  Step 1  按天批量抽取原始参数 (UNION 旧表 dev_device_param_detail_record
          + 新表 device_alarm_info，自适应跨越 2026-04-21 停采边界) + 状态事件
  Step 2  Pivot → 宽表 (5分钟重采样)，约 55~70 列
  Step 2.5 仅保留"运行"状态时段的参数行 (剔除关机/待机/告警等非运行数据)
  Step 3  滑动窗口统计 (均值/std/max/min × 4 窗口)  → +220 列
  Step 4  变化率特征 (diff/dt)                       → +55 列
  Step 5  多参数交互特征 (ratio/delta, 自动选高相关对)  → +40 列
  Step 6  告警/状态计数特征                           → +12 列
  合计: ~380+ 列 ("设备完整状态向量")

运行:
  # 列出所有设备
  python extract_device_features.py

  # 单设备 7 天
  python extract_device_features.py --device_code 102000000996 --days 7 --out features.parquet

  # 所有设备
  python extract_device_features.py --all_devices --days 7
"""

import sys, os, argparse, logging
from datetime import datetime, timedelta, date
from collections import defaultdict

import dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── 数据库 ────────────────────────────────────────────────
def _get_pg_config() -> dict:
    """从 .env 或环境变量读取 PostgreSQL 连接配置"""
    # 尝试加载 .env（优先 backend/.env，其次项目根目录 .env）
    for env_path in [
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    ]:
        if os.path.exists(env_path):
            dotenv.load_dotenv(env_path)
            break
    dotenv.load_dotenv()  # 兜底

    cfg = dict(
        host=os.getenv("PG_HOST", "127.0.0.1"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
        connect_timeout=60,
        keepalives=1,
        keepalives_idle=20,
        keepalives_interval=5,
        keepalives_count=3,
        options="-c statement_timeout=0 -c tcp_keepalives_idle=20",
    )
    return cfg

PG = _get_pg_config()
log.info("DB: %s:%s (user=%s)", PG["host"], PG["port"], PG["user"])

# ── 特征工程配置 ─────────────────────────────────────────
RESAMPLE_FREQ = "5min"   # 重采样频率 (5分钟是数据最低采集粒度)

# 运行时段判定：仅 code 1(运行) 反映设备真实切削工况，用于特征计算。
# 注意：上下料(code 5) 虽在 dev_device_status 中也归类为"运行"，但属辅助动作、
# 参数值非真实工况，按用户决定排除；其余(关机/待机/告警等)同样剔除。
RUNNING_CODES = {1}

WINDOWS = [
    ("5min",  "5min"),
    ("15min", "15min"),
    ("30min", "30min"),
    ("60min", "60min"),
]
STAT_FUNCS = ["mean", "std", "max", "min"]


def get_conn():
    return psycopg2.connect(**PG)


# ═══════════════════════════════════════════════════════════
# Step 1: 数据抽取 (按天批量)
# ═══════════════════════════════════════════════════════════

def get_device_list() -> list:
    """
    device_info 列: device_id (varchar 设备编码), device_name, id (numeric)
    """
    conn = get_conn()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT di.device_id  AS device_code,
                   di.device_name,
                   di.id         AS numeric_id,
                   COUNT(dp.id)  AS param_count
            FROM device_info di
            LEFT JOIN dev_device_param dp ON dp.device_no = di.device_id
            GROUP BY di.device_id, di.device_name, di.id
            ORDER BY di.id
        """)
        devices = [dict(r) for r in cur.fetchall()]
    conn.close()
    return devices


def get_device_params(device_code: str) -> list:
    """从 dev_device_param 获取参数定义 (快, 非 hypertable)"""
    conn = get_conn()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT name, description, unit, type
            FROM dev_device_param
            WHERE device_no = %s
            ORDER BY name
        """, (device_code,))
        params = [dict(r) for r in cur.fetchall()]
    conn.close()
    return params


def build_running_intervals(status_df: pd.DataFrame, running_codes: set,
                            data_end: datetime):
    """从状态事件构造排序的运行时段 (starts64, ends64)；无运行记录返回 None。"""
    if status_df.empty:
        return None
    run = status_df[status_df["status"].isin(running_codes)].sort_values("start_time")
    if run.empty:
        return None
    starts = run["start_time"].values.astype("datetime64[ns]")
    ends = (run["end_time"].fillna(pd.Timestamp(data_end))
            .values.astype("datetime64[ns]"))
    return starts, ends


def filter_to_running(wide: pd.DataFrame, intervals) -> pd.DataFrame:
    """仅保留时间戳落在运行时段内的行 (向量化 searchsorted，时段已排序且互不重叠)。"""
    if wide.empty or intervals is None:
        return wide
    starts, ends = intervals
    iv = wide.index.values.astype("datetime64[ns]")
    pos = np.searchsorted(starts, iv, side="right") - 1
    mask = pos >= 0
    mask[mask] = iv[mask] <= ends[pos[mask]]
    return wide[mask]


def fetch_one_day(conn, device_code: str, day: date) -> pd.DataFrame:
    """抽取单天原始参数数据 (约 116K 行)

    数据源 UNION 新旧两表，自适应跨越 2026-04-21 停采边界：
      - 旧表 dev_device_param_detail_record：覆盖历史数据（≤ 2026-04-21 停采）。
      - 新表 device_alarm_info（实时点位采集表）：覆盖停采后至今。
        全精度值取自 raw_json->devices[]->points[]->point_value（LATERAL 按
        point_id 匹配），回退 point_value 列。与 services.get_param_data 一致。
    某一天通常只有一张表有数据，UNION 成本≈有数据的那张表。
    """
    start = datetime.combine(day, datetime.min.time())
    end   = start + timedelta(days=1)

    with conn.cursor() as cur:
        t0 = __import__("time").time()
        cur.execute("""
            SELECT gather_time, p_name, p_value FROM (
                SELECT gather_time, p_name, p_value::text AS p_value
                FROM dev_device_param_detail_record
                WHERE device_code = %s
                  AND gather_time >= %s AND gather_time < %s
                UNION ALL
                SELECT a.point_time AS gather_time, a.point_id AS p_name,
                       COALESCE(pt.pv, a.point_value::text) AS p_value
                FROM device_alarm_info a
                LEFT JOIN LATERAL (
                    SELECT pts.elem->>'point_value' AS pv
                    FROM jsonb_array_elements(a.raw_json->'devices') dev
                    CROSS JOIN jsonb_array_elements(dev->'points') AS pts(elem)
                    WHERE pts.elem->>'point_id' = a.point_id
                    LIMIT 1
                ) pt ON true
                WHERE a.device_id = %s
                  AND a.point_time >= %s AND a.point_time < %s
            ) u
        """, (device_code, start, end, device_code, start, end))
        rows = cur.fetchall()
        elapsed = __import__("time").time() - t0

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["gather_time", "p_name", "p_value"])
    df["gather_time"] = pd.to_datetime(df["gather_time"])
    df["p_value"] = pd.to_numeric(df["p_value"], errors="coerce")
    log.info(f"  {day}: {len(df):,} rows, {df['p_name'].nunique()} params  ({elapsed:.1f}s)")
    return df


def fetch_status_for_range(device_id, start: datetime, end: datetime) -> pd.DataFrame:
    """抽取状态事件 (小表, 快)"""
    conn = get_conn()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT r.device_id, r.status, r.start_time, r.end_time,
                   r.duration, r.qualified_count, r.unqualified_count,
                   COALESCE(s.name, r.status::text) AS status_name
            FROM dev_device_status_record r
            LEFT JOIN dev_device_status s ON s.code = r.status
            WHERE r.device_id = %s
              AND r.start_time >= %s AND r.start_time < %s
            ORDER BY r.start_time
        """, (device_id, start, end))
        rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["start_time"] = pd.to_datetime(df["start_time"])
    df["end_time"]   = pd.to_datetime(df["end_time"])
    log.info(f"  Status events: {len(df):,}")
    return df


# ═══════════════════════════════════════════════════════════
# Step 2: Pivot → 宽表
# ═══════════════════════════════════════════════════════════

def pivot_to_wide(param_df: pd.DataFrame, freq: str = RESAMPLE_FREQ) -> pd.DataFrame:
    if param_df.empty:
        return pd.DataFrame()

    wide = (
        param_df
        .pivot_table(index="gather_time", columns="p_name",
                     values="p_value", aggfunc="mean")
        .resample(freq).mean()
        .interpolate(method="time", limit=3)
    )
    wide.columns.name = None
    return wide


# ═══════════════════════════════════════════════════════════
# Step 3 + 4: 滑动窗口统计 + 变化率
# ═══════════════════════════════════════════════════════════

def add_rolling_features(wide: pd.DataFrame) -> pd.DataFrame:
    raw_cols = list(wide.columns)
    parts = [wide]

    for win_name, win_offset in WINDOWS:
        rolled = wide[raw_cols].rolling(win_offset, min_periods=1)
        for func in STAT_FUNCS:
            agg = getattr(rolled, func)()
            agg.columns = [f"{c}__{win_name}_{func}" for c in raw_cols]
            parts.append(agg)

    # 变化率 (差分/时间间隔)
    dt_min = (wide.index.to_series().diff()
              .dt.total_seconds().div(60).clip(lower=0.001))
    diff_df = wide[raw_cols].diff().div(dt_min, axis=0)
    diff_df.columns = [f"{c}__diff_per_min" for c in raw_cols]
    parts.append(diff_df)

    return pd.concat(parts, axis=1)


# ═══════════════════════════════════════════════════════════
# Step 5: 交互特征
# ═══════════════════════════════════════════════════════════

def add_interaction_features(df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    raw_cols = [c for c in df.columns if "__" not in c]
    if len(raw_cols) < 2:
        return df

    # 用样本计算相关性 (快速)
    sample = df[raw_cols].dropna(how="all").head(500)
    corr = sample.corr(numeric_only=True).abs()

    pairs, seen = [], set()
    for (a, b), _ in corr.unstack().sort_values(ascending=False).items():
        if a == b:
            continue
        key = tuple(sorted([a, b]))
        if key in seen:
            continue
        seen.add(key)
        pairs.append((a, b))
        if len(pairs) >= top_n:
            break

    inter = {}
    for a, b in pairs:
        if a not in df.columns or b not in df.columns:
            continue
        inter[f"iact__{a}_div_{b}"] = df[a] / df[b].replace(0, np.nan)
        inter[f"iact__{a}_sub_{b}"] = df[a] - df[b]

    if inter:
        df = pd.concat([df, pd.DataFrame(inter, index=df.index)], axis=1)
    return df


# ═══════════════════════════════════════════════════════════
# Step 6: 告警/状态特征
# ═══════════════════════════════════════════════════════════

def add_alarm_features(df: pd.DataFrame, status_df: pd.DataFrame,
                       windows_min: list = None) -> pd.DataFrame:
    if status_df.empty:
        return df
    if windows_min is None:
        windows_min = [5, 15, 30, 60]

    ALARM_STATUSES = {2, 3, 4, 5}
    status_df = status_df.copy()
    status_df["is_alarm"] = status_df["status"].isin(ALARM_STATUSES).astype(int)
    status_df["is_stop"]  = (status_df["status"] == 1).astype(int)

    rows = defaultdict(list)
    for ts in df.index:
        for w in windows_min:
            ws = ts - timedelta(minutes=w)
            sub = status_df[(status_df["start_time"] >= ws) &
                            (status_df["start_time"] <= ts)]
            rows[f"alarm_cnt_{w}min"].append(sub["is_alarm"].sum())
            rows[f"stop_cnt_{w}min"].append(sub["is_stop"].sum())

        cur = status_df[(status_df["start_time"] <= ts) &
                        (status_df["end_time"].isna() |
                         (status_df["end_time"] >= ts))]
        if not cur.empty:
            last = cur.iloc[-1]
            rows["current_status"].append(last["status"])
            rows["current_status_sec"].append(
                (ts - last["start_time"]).total_seconds())
        else:
            rows["current_status"].append(np.nan)
            rows["current_status_sec"].append(np.nan)

        alm = status_df[(status_df["start_time"] <= ts) &
                        (status_df["is_alarm"] == 1)]
        rows["min_since_last_alarm"].append(
            (ts - alm["start_time"].max()).total_seconds() / 60
            if not alm.empty else np.nan)

    return pd.concat([df, pd.DataFrame(rows, index=df.index)], axis=1)


# ═══════════════════════════════════════════════════════════
# 主 Pipeline
# ═══════════════════════════════════════════════════════════

def build_features(device_code: str, device_id: str, days: int = 7,
                   out_path: str = None, running_only: bool = True) -> pd.DataFrame:

    # 数据截止日期：优先用环境变量，否则用最新数据日期
    end_str = os.getenv("FEATURE_END_DATE", "")
    if end_str:
        end_dt = datetime.strptime(end_str, "%Y-%m-%d")
    else:
        end_dt = datetime(2026, 4, 21)  # 默认最新数据日期
    start_dt = end_dt - timedelta(days=days)

    log.info(f"===== {device_code}  [{start_dt:%Y-%m-%d} ~ {end_dt:%Y-%m-%d}]  {days}天 =====")

    # 抽取状态事件 (一次性, 快)
    status_df = fetch_status_for_range(device_id, start_dt, end_dt)

    # 运行时段：仅保留运行(code 1)时段的参数值用于特征计算
    run_intervals = None
    if running_only:
        running_codes = RUNNING_CODES
        run_intervals = build_running_intervals(status_df, running_codes, end_dt)
        if run_intervals is None:
            log.warning("无运行时段记录，跳过运行状态过滤 (保留全部数据)")
        else:
            log.info(f"运行状态过滤启用: codes={sorted(running_codes)}, "
                     f"运行时段 {len(run_intervals[0]):,} 段")

    # 按天批量抽取 + 特征工程
    daily_parts = []
    grid_rows = run_rows = 0
    conn = get_conn()
    try:
        for n in range(days):
            day = (start_dt + timedelta(days=n)).date()
            raw = fetch_one_day(conn, device_code, day)
            if raw.empty:
                log.info(f"  {day}: no data, skip")
                continue

            wide = pivot_to_wide(raw)
            if wide.empty:
                continue

            if run_intervals is not None:
                grid_rows += len(wide)
                wide = filter_to_running(wide, run_intervals)
                run_rows += len(wide)
                if wide.empty:
                    log.info(f"  {day}: 无运行时段数据, skip")
                    continue

            feats = add_rolling_features(wide)
            daily_parts.append(feats)
    finally:
        conn.close()

    if run_intervals is not None and grid_rows:
        log.info(f"运行状态过滤: 保留 {run_rows:,}/{grid_rows:,} 行 "
                 f"({run_rows / grid_rows:.1%}), 剔除非运行 {grid_rows - run_rows:,} 行")

    if not daily_parts:
        log.warning("无数据")
        return pd.DataFrame()

    # 拼接所有天
    features = pd.concat(daily_parts, axis=0)
    features = features.sort_index()

    # 交互特征 + 告警特征 (在全量数据上计算)
    features = add_interaction_features(features)
    features = add_alarm_features(features, status_df)

    # 清理全空列/行
    before = len(features.columns)
    features = features.dropna(axis=1, how="all")
    features = features.replace([np.inf, -np.inf], np.nan)
    after = len(features.columns)

    _print_summary(features)
    log.info(f"最终: {len(features):,} 行 × {len(features.columns)} 列  "
             f"(清理 {before - after} 全空列)")

    if out_path:
        if out_path.endswith(".parquet"):
            features.to_parquet(out_path)
        else:
            features.to_csv(out_path)
        log.info(f"已保存: {out_path}")

    return features


def _print_summary(df: pd.DataFrame):
    cats = defaultdict(int)
    for c in df.columns:
        if c.startswith("iact__"):                cats["交互特征"] += 1
        elif "__diff_per_min" in c:               cats["变化率"] += 1
        elif any(f"__{w}_{s}" in c
                 for w,_ in WINDOWS for s in STAT_FUNCS): cats["滑动窗口"] += 1
        elif any(c.startswith(p) for p in
                 ("alarm_cnt","stop_cnt","current_status","min_since")): cats["告警/状态"] += 1
        else:                                     cats["原始参数"] += 1

    print("\n── 特征列汇总 ──────────────────────────────────")
    for cat, n in cats.items():
        print(f"  {cat:<12}: {n:>4} 列")
    print(f"  {'合计':<12}: {sum(cats.values()):>4} 列")
    print("────────────────────────────────────────────────\n")


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="设备特征提取 (TimescaleDB → Parquet)")
    parser.add_argument("--device_code", default=None)
    parser.add_argument("--all_devices",  action="store_true")
    parser.add_argument("--days",  type=int, default=90, help="天数 (默认90天)")
    parser.add_argument("--out",   default=None, help="输出路径 (.csv 或 .parquet)")
    parser.add_argument("--no_running_filter", action="store_true",
                        help="关闭运行状态过滤 (默认仅保留运行 code 1 时段)")
    args = parser.parse_args()
    running_only = not args.no_running_filter

    devices = get_device_list()

    if args.all_devices:
        for dev in devices:
            suffix = ".parquet"
            out = args.out or os.path.join(
                "..", "features_output", f"features_{dev['device_code']}{suffix}")
            build_features(dev["device_code"], dev["numeric_id"],
                           days=args.days, out_path=out, running_only=running_only)

    elif args.device_code:
        dev = next((d for d in devices if d["device_code"] == args.device_code), None)
        if not dev:
            print(f"未找到设备: {args.device_code}")
            print("可用:", [d["device_code"] for d in devices])
            return
        out = args.out or f"features_{args.device_code}.parquet"
        # device_code (varchar) 用于 param 表查询
        # numeric_id 用于 status_record 关联 (INTEGER 类型)
        df = build_features(dev["device_code"], dev["numeric_id"],
                            days=args.days, out_path=out, running_only=running_only)
        if not df.empty:
            print(f"\n前5行 × 前8列:")
            print(df.iloc[:5, :8].to_string())

    else:
        # 列出设备
        print(f"\n可用设备 ({len(devices)} 台):")
        print(f"  {'设备编码':<25} {'名称':<20} {'参数数'}")
        for d in devices:
            print(f"  {d['device_code']:<25} {d['device_name']:<20} {d['param_count']}")
        print(f"\n数据范围: 2025-10-30 ~ 2026-04-21 (24+ 周)")
        print(f"\n运行示例:")
        print(f"  python extract_device_features.py --device_code 102000000996 --days 7")
        print(f"  python extract_device_features.py --all_devices --days 7")


if __name__ == "__main__":
    main()
