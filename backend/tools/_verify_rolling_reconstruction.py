# cython: annotation_typing=False, infer_types=False, language_level=3
"""一次性验证脚本：确认 device_alarm_5min 连续聚合(005迁移新增)能代数重建
前端 DeviceParams.vue computeFeatureSeries() 的滑动均值/滑动标准差/变化率
（精确复刻，容差内），为 Phase 3(接口切换)托底。

用法(Windows, cntlm 隧道在跑)：
  PYTHONUTF8=1 PG_HOST=127.0.0.1 PG_PORT=15432 \
    backend/venv/Scripts/python.exe backend/tools/_verify_rolling_reconstruction.py

前提：迁移 005_device_5min_cagg.sql 已在目标库执行且 CAGG 已物化到待验证窗口
（迁移脚本本身会 refresh 最近30天）。
"""
import sys
from pathlib import Path
from datetime import timedelta

import pandas as pd

HERE = Path(__file__).resolve()
BACKEND = HERE.parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE.parent))

from extract_device_features import get_conn, get_device_list

# 与前端 FEATURE_CHARTS / computeFeatureSeries 的窗口定义一致：5/15/30/60min = 1/3/6/12 个5min桶
WINDOWS = {"5min": 1, "15min": 3, "30min": 6, "60min": 12}
TOL = 1e-3  # 前端 toFixed(4)，留一点余量应对浮点/聚合顺序误差


def find_device_window(conn, devices, lookback_hours=24, max_gap_hours=48):
    """从设备清单里找一个 device_alarm_info 有近期数据的设备，返回 (device_code, start, end)。"""
    with conn.cursor() as cur:
        for dev in devices:
            code = dev["device_code"]
            cur.execute(
                "SELECT MAX(point_time) FROM device_alarm_info WHERE device_id = %s",
                (code,),
            )
            last = cur.fetchone()[0]
            if last is None:
                continue
            # 用该设备实际最新数据时间收尾，避免容器/隧道时区和 wall-clock 对不上
            end = last
            start = end - timedelta(hours=lookback_hours)
            return code, dev.get("device_name"), start, end
    return None


def fetch_raw_points(conn, device_code, p_name, start, end):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT point_time, COALESCE(point_value_full, point_value::numeric) AS v
            FROM device_alarm_info
            WHERE device_id = %s AND point_id = %s
              AND point_time >= %s AND point_time < %s
              AND (point_value_full IS NOT NULL OR point_value IS NOT NULL)
            ORDER BY point_time
            """,
            (device_code, p_name, start, end),
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["point_time", "v"])


def fetch_5min_buckets(conn, device_code, p_name, start, end):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bucket, avg_val
            FROM device_alarm_5min
            WHERE device_id = %s AND point_id = %s
              AND bucket >= %s AND bucket < %s
            ORDER BY bucket
            """,
            (device_code, p_name, start, end),
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["bucket", "avg_val"])


def _rolling_features(series):
    """给定一串"5min桶均值"序列，套用与前端 computeFeatureSeries 完全一致的窗口算法。"""
    out = {}
    for w, n in WINDOWS.items():
        out[("mean", w)] = series.rolling(window=n, min_periods=1).mean()
    for w, n in WINDOWS.items():
        if w == "5min":
            continue  # 前端「滑动标准差」图只画 15/30/60min（单点标准差无意义）
        out[("std", w)] = series.rolling(window=n, min_periods=2).std(ddof=1)
    out[("diff", None)] = series.diff() / 5
    return out


def compute_ground_truth(raw_df):
    """原样重实现 DeviceParams.vue computeFeatureSeries()：5min分桶均值 → 滑窗统计。"""
    df = raw_df.copy()
    df["bucket"] = df["point_time"].dt.floor("5min")
    gv = df.groupby("bucket")["v"].mean().sort_index()
    return gv, _rolling_features(gv)


def compute_from_cagg(bucket_df):
    """从 device_alarm_5min 的 avg_val 序列直接重建同样的统计量。"""
    av = bucket_df.set_index("bucket")["avg_val"].astype(float).sort_index()
    return av, _rolling_features(av)


def compare(gv_truth, res_truth, gv_cagg, res_cagg, label):
    ok = True
    common = gv_truth.index.intersection(gv_cagg.index)
    if len(common) == 0:
        print(f"  [{label}] 无重叠的5min桶，跳过（CAGG可能还没物化到这段时间）")
        return False

    d = (gv_truth.loc[common] - gv_cagg.loc[common]).abs()
    print(f"  [{label}] 桶均值本身: {len(common)} 个桶, max|diff|={d.max():.6g}")
    if d.max() > TOL:
        ok = False

    for key, a in res_truth.items():
        b = res_cagg.get(key)
        if b is None:
            continue
        idx = a.dropna().index.intersection(b.dropna().index)
        if len(idx) == 0:
            continue
        diff = (a.loc[idx] - b.loc[idx]).abs()
        mism = int((diff > TOL).sum())
        kind, w = key
        wl = w or "-"
        status = "OK" if mism == 0 else "MISMATCH"
        print(f"  [{label}] {kind:4s} {wl:6s}: {len(idx)} 点比对, max|diff|={diff.max():.6g}, 超差 {mism} 个 [{status}]")
        if mism:
            ok = False
    return ok


def main():
    devices = get_device_list()
    if not devices:
        print("设备清单为空，无法验证")
        return

    conn = get_conn()
    found = find_device_window(conn, devices)
    if not found:
        print("所有设备在 device_alarm_info 里都没有数据，无法验证")
        conn.close()
        return

    device_code, device_name, start, end = found
    print(f"设备: {device_code} ({device_name})")
    print(f"窗口: {start} ~ {end}")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT point_id, COUNT(*) AS n
            FROM device_alarm_info
            WHERE device_id = %s AND point_time >= %s AND point_time < %s
            GROUP BY point_id ORDER BY n DESC LIMIT 5
            """,
            (device_code, start, end),
        )
        top_params = [r[0] for r in cur.fetchall()]

    if not top_params:
        print("该窗口无数据，换个设备/时间范围重试")
        conn.close()
        return
    print(f"代表性参数(按数据量取前5): {top_params}")

    all_ok = True
    for p_name in top_params:
        raw_df = fetch_raw_points(conn, device_code, p_name, start, end)
        bucket_df = fetch_5min_buckets(conn, device_code, p_name, start, end)
        if raw_df.empty or bucket_df.empty:
            print(f"\n[{p_name}] 原始点或CAGG桶为空，跳过")
            continue
        gv_truth, res_truth = compute_ground_truth(raw_df)
        gv_cagg, res_cagg = compute_from_cagg(bucket_df)
        print(f"\n[{p_name}] 原始点 {len(raw_df)} 行 -> 现算 {len(gv_truth)} 个5min桶 / CAGG {len(gv_cagg)} 个桶")
        ok = compare(gv_truth, res_truth, gv_cagg, res_cagg, p_name)
        all_ok = all_ok and ok

    conn.close()
    print("\n" + ("全部通过：CAGG 代数重建与现算一致 [PASS]" if all_ok else "存在不一致，见上方明细 [FAIL]"))


if __name__ == "__main__":
    main()
