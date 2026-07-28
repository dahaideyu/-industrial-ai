# cython: annotation_typing=False, infer_types=False, language_level=3
"""数据驱动的参数分组分析：基于运行时段参数的实际相关性(Spearman)做层次聚类。

不依赖 Excel / 命名，纯看参数随时间的协同变化。

- 服务端 time_bucket 聚合(5min)降低传输量(cntlm 隧道慢/易断)。
- 每天结果缓存到 features_output/_corr_cache/，断了重跑可续、二次秒回。
- 仅保留运行(code1)时段网格行算相关。

用法(cntlm 隧道在跑)：
  PYTHONUTF8=1 PG_HOST=127.0.0.1 PG_PORT=15432 \
    backend/venv/Scripts/python.exe backend/tools/_analyze_param_corr_groups.py [device_code] [days]
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_device_features import (
    get_conn, get_device_list, fetch_status_for_range,
    build_running_intervals, filter_to_running, RUNNING_CODES,
)

# 复用已知中文显示名（合膏机；名字跨 10 台合膏机共通）
CN = {}
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent /
                           "modules" / "device_warning" / "ai_analysis"))
    from point_config import PROCESS_POINT_DISPLAY_NAMES
    for m in PROCESS_POINT_DISPLAY_NAMES.values():
        CN.update(m)
except Exception:
    pass

CACHE = Path(__file__).resolve().parent.parent.parent / "features_output" / "_corr_cache"
CACHE.mkdir(parents=True, exist_ok=True)
BUCKET = "5 minutes"

AGG_SQL = r"""
    SELECT time_bucket(%s, gather_time) AS ts, p_name, avg(p_value::float8) AS v
    FROM dev_device_param_detail_record
    WHERE device_code = %s
      AND gather_time >= %s AND gather_time < %s
      AND p_value ~ '^-?[0-9]+(\.[0-9]+)?$'
    GROUP BY ts, p_name ORDER BY ts
"""


def pick_device(target_code=None):
    devices = get_device_list()
    by_code = {d["device_code"]: d for d in devices}
    if target_code and target_code in by_code:
        return by_code[target_code]
    by_nid = {d["numeric_id"]: d for d in devices}
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""SELECT device_id, COUNT(*) FROM dev_device_status_record
                       WHERE status=1 GROUP BY device_id ORDER BY 2 DESC""")
        rows = cur.fetchall()
    conn.close()
    for nid, _ in rows:
        if nid in by_nid:
            return by_nid[nid]
    return None


def fetch_day_wide(device_code, day):
    """取单天 5min 聚合宽表(ts × p_name)，带 parquet 缓存 + 重试。"""
    cache_f = CACHE / f"{device_code}_{day}.parquet"
    if cache_f.exists():
        return pd.read_parquet(cache_f)

    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    for attempt in range(3):
        conn = None
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute(AGG_SQL, (BUCKET, device_code, start, end))
                rows = cur.fetchall()
            df = pd.DataFrame(rows, columns=["ts", "p_name", "v"])
            if df.empty:
                wide = pd.DataFrame()
            else:
                wide = df.pivot_table(index="ts", columns="p_name", values="v")
                wide.index = pd.to_datetime(wide.index)
                wide.columns.name = None
            wide.to_parquet(cache_f)  # 缓存(空也缓存，避免重复打空天)
            print(f"  {day}: {len(wide)} 行 x {wide.shape[1]} 参数 (已缓存)")
            return wide
        except Exception as e:
            print(f"  [warn] {day} 第{attempt+1}次失败: {str(e)[:70]}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return pd.DataFrame()


def build_running_wide(dev, days):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""SELECT MAX(gather_time) FROM dev_device_param_detail_record
                       WHERE device_code=%s""", (dev["device_code"],))
        data_end = cur.fetchone()[0]
    conn.close()
    if data_end is None:
        return pd.DataFrame()
    et = pd.Timestamp(data_end).to_pydatetime()
    st = et - timedelta(days=days)

    status_df = fetch_status_for_range(dev["numeric_id"], st, et)
    run_intervals = build_running_intervals(status_df, RUNNING_CODES, et)

    parts = []
    cur_date = st.date()
    while cur_date <= et.date():
        wide = fetch_day_wide(dev["device_code"], cur_date)
        if not wide.empty:
            wide = filter_to_running(wide, run_intervals)
            if not wide.empty:
                parts.append(wide)
        cur_date += timedelta(days=1)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, axis=0).sort_index()


def cluster_by_corr(wide, corr_threshold=0.5):
    keep = []
    for c in wide.columns:
        s = wide[c]
        if s.notna().mean() < 0.3 or (s.std(skipna=True) or 0) < 1e-9:
            continue
        keep.append(c)
    sub = wide[keep]
    print(f"参与聚类的参数: {len(keep)}/{wide.shape[1]} (丢弃缺失多/常量列)")

    corr = sub.corr(method="spearman").fillna(0.0)
    dist = (1.0 - corr.abs()).to_numpy(copy=True)   # 可写副本，修复 read-only
    np.fill_diagonal(dist, 0.0)
    dist = (dist + dist.T) / 2.0                      # 强制对称(浮点保险)

    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import squareform
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method="average")
    labels = fcluster(Z, t=1.0 - corr_threshold, criterion="distance")

    groups = {}
    for col, lab in zip(keep, labels):
        groups.setdefault(lab, []).append(col)
    return groups, corr


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    thr = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5

    dev = pick_device(target)
    if not dev:
        print("找不到设备")
        return
    print(f"设备: {dev['device_code']} ({dev.get('device_name')}) nid={dev['numeric_id']}")

    wide = build_running_wide(dev, days)
    if wide.empty:
        print("无运行时段数据")
        return
    print(f"\n运行时段宽表: {len(wide)} 行 x {wide.shape[1]} 参数 "
          f"({wide.index.min()} ~ {wide.index.max()})\n")

    groups, corr = cluster_by_corr(wide, corr_threshold=thr)

    def cn(c):
        return f"{c} ({CN[c]})" if c in CN else c

    multi = {g: m for g, m in groups.items() if len(m) >= 2}
    singles = [m[0] for g, m in groups.items() if len(m) == 1]
    print(f"\n===== 相关性分组 (|Spearman|>={thr}) : {len(groups)} 组, "
          f"其中多参数组 {len(multi)} 个, 孤立参数 {len(singles)} 个 =====")
    for gid in sorted(multi, key=lambda g: -len(multi[g])):
        members = multi[gid]
        s = corr.loc[members, members].abs().values
        iu = np.triu_indices(len(members), k=1)
        print(f"\n● 组{gid} ({len(members)}个) 组内平均|corr|={s[iu].mean():.2f}")
        for c in members:
            print(f"    - {cn(c)}")
    if singles:
        print(f"\n● 孤立参数(与他人相关性<{thr}):")
        for c in singles:
            print(f"    - {cn(c)}")

    print("\n===== Top 20 强相关对 =====")
    cols = list(corr.columns)
    cc = corr.abs().values.copy()
    np.fill_diagonal(cc, 0.0)
    pairs = [(cols[i], cols[j], cc[i, j])
             for i in range(len(cols)) for j in range(i + 1, len(cols))]
    for a, b, v in sorted(pairs, key=lambda x: -x[2])[:20]:
        print(f"    {v:.3f}  {cn(a)}  <->  {cn(b)}")


if __name__ == "__main__":
    main()
