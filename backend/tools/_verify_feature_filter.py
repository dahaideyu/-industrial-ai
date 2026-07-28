# cython: annotation_typing=False, infer_types=False, language_level=3
"""一次性验证脚本：确认特征视图实时路径只取运行(code 1)时段参数算特征。
用法(Windows, cntlm 隧道在跑)：
  PYTHONUTF8=1 PG_HOST=127.0.0.1 PG_PORT=15432 \
    backend/venv/Scripts/python.exe backend/tools/_verify_feature_filter.py
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve()
BACKEND = HERE.parent.parent          # backend/
sys.path.insert(0, str(BACKEND))      # for modules.*
sys.path.insert(0, str(HERE.parent))  # for extract_device_features

from extract_device_features import (
    get_conn, get_device_list, fetch_status_for_range,
    build_running_intervals, RUNNING_CODES,
)
from modules.device_param.routes import _build_features_on_the_fly


def find_device_window():
    """找一个有 code-1 运行事件、且在设备清单里的设备 + 1天窗口。"""
    devices = get_device_list()
    by_nid = {d["numeric_id"]: d for d in devices}

    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT device_id, MAX(start_time) AS last_run, COUNT(*) AS n
            FROM dev_device_status_record
            WHERE status = 1
            GROUP BY device_id
            ORDER BY last_run DESC
        """)
        rows = cur.fetchall()
    conn.close()

    # 取「在设备清单里」的、last_run 最新的设备
    for device_numeric_id, last_run, n in rows:
        dev = by_nid.get(device_numeric_id)
        if dev:
            day = pd.Timestamp(last_run).normalize().to_pydatetime()
            print(f"(候选: nid={device_numeric_id} status=1 共 {n} 段, 最近 {last_run})")
            return dev, day, day + timedelta(days=1, seconds=-1)

    # 没有交集：打印诊断信息
    print("status=1 的 device_id:", [r[0] for r in rows[:10]])
    print("设备清单 numeric_id:", sorted(by_nid.keys())[:20])
    return None


def main():
    found = find_device_window()
    if not found:
        print("找不到任何 code-1 运行事件，无法验证")
        return
    dev, st, et = found
    print(f"设备: {dev['device_code']} ({dev.get('device_name')}) nid={dev['numeric_id']}")
    print(f"窗口: {st} ~ {et}")

    # 独立构造运行时段（真值）
    status_df = fetch_status_for_range(dev["numeric_id"], st, et)
    n_run = 0 if status_df.empty else int((status_df["status"] == 1).sum())
    print(f"该窗口状态事件: {0 if status_df.empty else len(status_df)} 条, 其中 code-1 运行: {n_run} 段")
    intervals = build_running_intervals(status_df, RUNNING_CODES, et)

    # 跑被测函数（已含过滤）
    df = _build_features_on_the_fly(dev["device_code"], st, et)
    if df is None or df.empty:
        print("特征为空（该窗口无运行数据或无参数）")
        return
    print(f"\n特征结果: {len(df)} 行 x {len(df.columns)} 列")
    print(f"时间范围: {df.index.min()} ~ {df.index.max()}")

    # 验证：每个特征时间戳都落在某个运行时段内
    if intervals is None:
        print("\n[!] build_running_intervals=None（无运行事件）→ filter_to_running 回退保留全部，符合预期")
        return
    starts, ends = intervals
    iv = df.index.values.astype("datetime64[ns]")
    pos = np.searchsorted(starts, iv, side="right") - 1
    inside = (pos >= 0)
    inside[inside] = iv[inside] <= ends[pos[inside]]
    n_inside = int(inside.sum())
    n_total = len(df)
    print(f"\n验证: {n_inside}/{n_total} 行落在运行时段内")
    if n_inside == n_total:
        print("✓ 通过：所有特征行都在运行(code 1)时段内")
    else:
        print(f"✗ 失败：有 {n_total - n_inside} 行落在非运行时段")
        bad = df.index[~inside][:10]
        print("  越界样例:", [str(x) for x in bad])

    # 对比：若不过滤会有多少行（粗略：直接 pivot 当天所有数据的网格行数）
    from extract_device_features import fetch_one_day, pivot_to_wide, filter_to_running
    conn = get_conn()
    raw = fetch_one_day(conn, dev["device_code"], st.date())
    conn.close()
    if not raw.empty:
        wide = pivot_to_wide(raw)
        unfiltered = len(wide)
        filtered = len(filter_to_running(wide, intervals))
        print(f"\n过滤对比(当天网格): 全量 {unfiltered} 行 → 运行过滤后 {filtered} 行 "
              f"(保留 {filtered/unfiltered*100:.1f}%)" if unfiltered else "")


if __name__ == "__main__":
    main()
