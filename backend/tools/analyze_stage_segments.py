# cython: annotation_typing=False, infer_types=False, language_level=3
"""按工艺阶段(合膏阶段状态 Tec_DQD_DH)拆分参数，做跨批次/跨天对比。

动机
----
合膏是**批次/循环**工艺：一个批次顺序走 进料→加酸→搅拌→抽真空→出料…
现有特征管线(`extract_device_features.py`)用 5min 重采样 + code1 运行过滤，
把不同阶段拍平到一锅里，阶段特有的参数行为被平均掉。本脚本改用阶段状态码
`Tec_DQD_DH` 作为**更精确的工序标签**：

  1) 解码阶段：列出阶段码分布、各码停留时长。
  2) 数批次：值发生跳变=一次阶段切换；同一阶段码一天出现 N 次≈跑了 N 批。
  3) 按阶段拆参数：原始分辨率(不重采样)把阶段码 merge_asof 贴到每条参数行，
     按 (批次, 阶段) 聚合其他参数的 mean/std/min/max/时长/段内变化(slope)，
     再锁定某个阶段(如 进料/加酸)看其他参数跨批次/跨天怎么变。

为什么不用 5min 重采样：很多阶段短于 5min，avg 会糊掉阶段边界与段内趋势。
状态码是稀疏采样的**状态量**，必须前向填充(merge_asof)而非取均值。

用法(cntlm 隧道在跑)：
  PYTHONUTF8=1 PG_HOST=127.0.0.1 PG_PORT=15432 \
    backend/venv/Scripts/python.exe backend/tools/analyze_stage_segments.py \
      --device 102000000996 --days 7 [--stage 进料码] [--params Tec_Hg_tep,Tec_Sszkd]

  --stage 省略时给出全部阶段概览；指定后输出该阶段的跨批次对比表。
  --params 省略时用合膏机核心参数；--params all 用全部数值参数。
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_device_features import get_conn, get_device_list  # noqa: E402

# 复用中文显示名(合膏机参数名跨 10 台共通)
CN = {}
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent /
                           "modules" / "device_warning" / "ai_analysis"))
    from point_config import PROCESS_POINT_DISPLAY_NAMES  # noqa: E402
    for _m in PROCESS_POINT_DISPLAY_NAMES.values():
        CN.update(_m)
except Exception:
    pass

# 阶段状态参数(合膏机)。其它设备若有类似阶段量，加到这里即可复用全部逻辑。
STAGE_PARAM = "Tec_DQD_DH"      # 合膏阶段状态
END_PARAM = "Tec_End"           # 合膏结束标志位(批次边界校验)

# 默认对比的"其他参数"(合膏机工艺核心；--params all 改用全部数值参数)
DEFAULT_TARGETS = [
    "Tec_Hg_tep", "Tec_Hg_tep_Max", "Tec_Sszkd",
    "Tec_lead_Real_weight", "Tec_sour_Real_weight", "Tec_Water_Real_weight",
]

OUT_DIR = Path(__file__).resolve().parent.parent.parent / "features_output" / "_stage"

# 阶段切换前状态码一直保持，但若设备停机则停止上报。超过此空档(分钟)不再
# 把时间算进该阶段、也不把空档里的参数行归给它，避免批次间停机吞进上一阶段。
GAP_TOL_MIN = 10

# 同时跨新旧两表(2026-04-21 停采边界)取选定 p_name 的原始逐行数据。
# 新表 device_alarm_info 的 point_value 列被取整(如温度 70 vs raw_json 70.8)。
# 默认(fast)直接用列值——阶段趋势分析够用且快~10x；--precise 走 raw_json LATERAL
# 取全精度(每行扫整快照点位，5 秒采样下多天会慢)。两者都 UNION 旧表(跨停采边界)。
_NEW_FAST = "a.point_value::text AS p_value"
_NEW_PRECISE = """COALESCE((
        SELECT pts.elem->>'point_value'
        FROM jsonb_array_elements(a.raw_json->'devices') dev
        CROSS JOIN jsonb_array_elements(dev->'points') AS pts(elem)
        WHERE pts.elem->>'point_id' = a.point_id LIMIT 1
    ), a.point_value::text) AS p_value"""


def build_sql(precise: bool) -> str:
    new_val = _NEW_PRECISE if precise else _NEW_FAST
    return f"""
SELECT gather_time, p_name, p_value FROM (
    SELECT gather_time, p_name, p_value::text AS p_value
    FROM dev_device_param_detail_record
    WHERE device_code = %s AND gather_time >= %s AND gather_time < %s
      AND p_name = ANY(%s)
    UNION ALL
    SELECT a.point_time AS gather_time, a.point_id AS p_name, {new_val}
    FROM device_alarm_info a
    WHERE a.device_id = %s AND a.point_time >= %s AND a.point_time < %s
      AND a.point_id = ANY(%s)
) u ORDER BY gather_time
"""


def cn(p):
    return f"{p}({CN[p]})" if p in CN else p


def pick_device(target_code):
    devices = get_device_list()
    by_code = {d["device_code"]: d for d in devices}
    return by_code.get(target_code)


def data_end(device_code):
    """该设备最新数据时间(决定回溯窗口终点)。

    优先查新表 device_alarm_info 并带时间下界(走 point_time 索引，秒回)：
    数据 2026-04-21 后都在新表且实时更新。下界逐步放宽，仍空才回退旧表的
    MAX(无时间下界，慢，仅历史设备才会走到)。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for days in (2, 30, 365):
                cur.execute(
                    """SELECT MAX(point_time) FROM device_alarm_info
                       WHERE device_id=%s
                         AND point_time > now() - (%s || ' days')::interval""",
                    (device_code, days))
                v = cur.fetchone()[0]
                if v is not None:
                    return v
            cur.execute("""SELECT MAX(gather_time) FROM dev_device_param_detail_record
                           WHERE device_code=%s""", (device_code,))
            return cur.fetchone()[0]
    finally:
        conn.close()


def list_param_names(device_code):
    """该设备全部参数名(用于 --params all)。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM dev_device_param WHERE device_no=%s",
                        (device_code,))
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def fetch_raw(device_code, p_names, start, end, precise=False):
    """按天拉取选定参数的原始逐行(避免单次大查询在慢隧道上超时)。"""
    sql = build_sql(precise)
    parts = []
    cur_day = start
    while cur_day < end:
        nxt = min(cur_day + timedelta(days=1), end)
        conn = get_conn()
        try:
            with conn.cursor() as c:
                c.execute(sql, (device_code, cur_day, nxt, p_names,
                                device_code, cur_day, nxt, p_names))
                rows = c.fetchall()
            if rows:
                parts.append(pd.DataFrame(
                    rows, columns=["gather_time", "p_name", "p_value"]))
            print(f"  {cur_day:%Y-%m-%d}: {len(rows):,} 行")
        finally:
            conn.close()
        cur_day = nxt
    if not parts:
        return pd.DataFrame(columns=["gather_time", "p_name", "p_value"])
    df = pd.concat(parts, ignore_index=True)
    df["gather_time"] = pd.to_datetime(df["gather_time"])
    return df


def build_stage_segments(stage_long, end_long, batch_by="cycle"):
    """从阶段状态长表构造段表：每个连续相同阶段码 = 一段。

    返回 DataFrame[seg_id, stage, t_start, t_end, dur_min, batch]，按时间排序。
    batch：默认('cycle')用阶段码回到最小码(循环起点)递增；batch_by='end' 才用
    Tec_End 上升沿(实测该设备 Tec_End 恒为 1，不可用作批次划分)。
    """
    s = (stage_long[["gather_time", "p_value"]]
         .assign(code=pd.to_numeric(stage_long["p_value"], errors="coerce"))
         .dropna(subset=["code"])
         .sort_values("gather_time"))
    s["code"] = s["code"].round().astype(int)
    if s.empty:
        return pd.DataFrame()

    # 连续相同码压缩成段
    change = s["code"].ne(s["code"].shift())
    s["seg_id"] = change.cumsum()
    seg = (s.groupby("seg_id")
             .agg(stage=("code", "first"),
                  t_start=("gather_time", "first"),
                  t_last=("gather_time", "last"))   # 段内实际最后一个采样
             .reset_index())
    # 段终点延伸到下一段起点(状态量在切换前一直保持)，但封顶在 t_last+空档容差，
    # 防止批次间停机把空档算进上一阶段。
    nxt = seg["t_start"].shift(-1)
    cap = seg["t_last"] + pd.Timedelta(minutes=GAP_TOL_MIN)
    seg["t_end"] = nxt.where(nxt.notna(), seg["t_last"]).clip(upper=cap)
    seg["dur_min"] = (seg["t_end"] - seg["t_start"]).dt.total_seconds() / 60

    # 批次划分。默认用"阶段码回到最小码(循环起点)=新批次"——直接来自可信的阶段
    # 信号；实测 Tec_End 不是每批脉冲(整天只 2 个上升沿)，故仅 batch_by='end' 才用它。
    if batch_by == "end" and end_long is not None and not end_long.empty:
        e = (end_long.assign(v=pd.to_numeric(end_long["p_value"], errors="coerce"))
                     .dropna(subset=["v"]).sort_values("gather_time"))
        rising = e[(e["v"] > 0) & (e["v"].shift(fill_value=0) <= 0)]["gather_time"]
        seg["batch"] = np.searchsorted(rising.values, seg["t_start"].values, side="right")
    else:
        min_code = seg["stage"].min()
        seg["batch"] = (seg["stage"].eq(min_code) &
                        seg["stage"].shift().ne(min_code)).cumsum()
    return seg


def attach_segment(target_long, seg):
    """把段标签(stage/seg_id/batch)用 merge_asof 贴到每条参数行(前向填充)。"""
    t = (target_long.assign(v=pd.to_numeric(target_long["p_value"], errors="coerce"))
                     .dropna(subset=["v"])
                     .sort_values("gather_time"))
    seg_keys = seg[["t_start", "t_end", "seg_id", "stage", "batch"]].sort_values("t_start")
    merged = pd.merge_asof(t, seg_keys, left_on="gather_time",
                           right_on="t_start", direction="backward")
    merged = merged.dropna(subset=["seg_id"])
    # 剔除落在阶段(封顶)终点之后的行——批次间停机空档不归属任何阶段
    return merged[merged["gather_time"] <= merged["t_end"]]


def stage_overview(seg):
    print("\n===== 阶段码分布(整窗) =====")
    g = (seg.groupby("stage")
            .agg(段数=("seg_id", "count"),
                 总时长_min=("dur_min", "sum"),
                 中位时长_min=("dur_min", "median"))
            .reset_index().sort_values("stage"))
    g["总时长_min"] = g["总时长_min"].round(1)
    g["中位时长_min"] = g["中位时长_min"].round(2)
    print(g.to_string(index=False))

    print("\n===== 每日各阶段出现次数(≈批次数) =====")
    d = seg.copy()
    d["day"] = d["t_start"].dt.date
    pivot = (d.groupby(["day", "stage"]).size()
              .unstack("stage", fill_value=0).sort_index())
    print(pivot.to_string())
    print(f"\n批次总数(整窗): {seg['batch'].nunique()}")


def stage_signature(merged):
    """阶段指纹：全部阶段 × 各参数的「段内均值」和「段内变化Δ」两张矩阵。

    Δ = 每段(末-首)再对该阶段所有段取均值；正=该阶段内升，负=降，≈0=平稳。
    一眼识别工序：重量Δ大=进料/加酸，真空Δ大=抽真空，温度Δ大=升温搅拌。
    """
    m = merged.sort_values("gather_time")
    g = m.groupby(["stage", "seg_id", "p_name"])["v"]
    per_seg = pd.DataFrame({"mean": g.mean(),
                            "delta": g.last() - g.first()}).reset_index()
    mean_mx = (per_seg.groupby(["stage", "p_name"])["mean"].mean()
                      .unstack("p_name").round(2).sort_index())
    delta_mx = (per_seg.groupby(["stage", "p_name"])["delta"].mean()
                       .unstack("p_name").round(2).sort_index())
    rename = {p: (CN[p] if p in CN else p) for p in mean_mx.columns}
    mean_mx = mean_mx.rename(columns=rename)
    delta_mx = delta_mx.rename(columns=rename)
    with pd.option_context("display.max_columns", None, "display.width", 220):
        print("\n===== 阶段指纹 · 段内均值 (stage × 参数) =====")
        print(mean_mx.to_string())
        print("\n===== 阶段指纹 · 段内变化Δ(末-首, 该阶段所有段均值) =====")
        print(delta_mx.to_string())


def infer_phase(stage_mean, stage_delta):
    """从一段的参数均值/Δ反推工序名（合膏机）。纯启发式、仅供参考。

    依据：铅重快升=进料；酸重快升=加酸；酸重降+温升=搅拌反应；真空度拉高(绝对值大)
    =抽真空；铅重快降=出料。无对应参数则留空。
    """
    def g(d, key):  # 容错取值（参数中文名）
        return d.get(key)
    lead_d = g(stage_delta, "铅实时重量")
    sour_d = g(stage_delta, "酸实时重量")
    vac_m = g(stage_mean, "合膏实时真空度")
    tep_d = g(stage_delta, "合膏温度")
    tags = []
    if lead_d is not None and lead_d > 50:
        tags.append("进铅")
    if sour_d is not None and sour_d > 20:
        tags.append("加酸")
    if sour_d is not None and sour_d < -20:
        tags.append("反应耗酸")
    if vac_m is not None and vac_m > 600:
        tags.append("抽真空")
    if tep_d is not None and tep_d > 5:
        tags.append("升温")
    if lead_d is not None and lead_d < -100:
        tags.append("出料")
    return "/".join(tags) if tags else ""


def stage_recipe(merged, seg, device_code, save=False):
    """图片式"阶段配方表"：每个阶段码一行，列出 段时长(中位)、累计时间，
    以及该段内各参数的均值（跨批次平均）。对应图片里 段号→时间(h)→各列参数。

    时长取跨批次中位数（抗异常批），累计时间为按阶段码顺序的时长累加。
    """
    # 每阶段时长（跨批次中位）
    dur = (seg.groupby("stage")["dur_min"].median().round(2)
              .rename("时长_min").reset_index().sort_values("stage"))
    dur["累计_min"] = dur["时长_min"].cumsum().round(2)

    # 每阶段各参数均值（先段内均值，再跨批次平均），及Δ（用于工序推测）
    m = merged.sort_values("gather_time")
    g = m.groupby(["stage", "seg_id", "p_name"])["v"]
    per_seg = pd.DataFrame({"mean": g.mean(),
                            "delta": g.last() - g.first()}).reset_index()
    mean_mx = (per_seg.groupby(["stage", "p_name"])["mean"].mean()
                      .unstack("p_name").round(2))
    delta_mx = (per_seg.groupby(["stage", "p_name"])["delta"].mean()
                       .unstack("p_name").round(2))
    rename = {p: (CN[p] if p in CN else p) for p in mean_mx.columns}
    mean_mx = mean_mx.rename(columns=rename)
    delta_mx = delta_mx.rename(columns=rename)

    # 工序推测列
    phases = {st: infer_phase(mean_mx.loc[st].to_dict(),
                              delta_mx.loc[st].to_dict())
              for st in mean_mx.index}

    table = dur.merge(mean_mx.reset_index(), on="stage", how="left")
    table.insert(1, "工序推测", table["stage"].map(phases))
    table = table.rename(columns={"stage": "阶段码"})

    print(f"\n===== 合膏阶段配方表 · {device_code} "
          f"(每阶段：跨批次中位时长 + 段内参数均值) =====")
    print("说明：阶段码=Tec_DQD_DH；时长/累计单位=分钟；工序推测为参数行为反推，仅供参考")
    with pd.option_context("display.max_columns", None, "display.width", 240):
        print(table.to_string(index=False))

    if save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        f = OUT_DIR / f"{device_code}_recipe.csv"
        table.to_csv(f, index=False, encoding="utf-8-sig")
        print(f"\n已保存配方表: {f}")
    return table


def stage_param_table(merged, seg, stage_code):
    """锁定某阶段：每个批次该阶段内，其他参数的 mean / 段内变化(末-首)。"""
    sub = merged[merged["stage"] == stage_code]
    if sub.empty:
        print(f"\n阶段码 {stage_code} 无数据")
        return None

    recs = []
    for (batch, seg_id), grp in sub.groupby(["batch", "seg_id"]):
        t0 = grp["gather_time"].min()
        row = {"batch": int(batch), "day": t0.date(), "start": t0,
               "dur_min": round((grp["gather_time"].max() - t0).total_seconds() / 60, 1)}
        for p, pg in grp.groupby("p_name"):
            pg = pg.sort_values("gather_time")
            row[f"{p}__mean"] = round(pg["v"].mean(), 3)
            row[f"{p}__delta"] = round(pg["v"].iloc[-1] - pg["v"].iloc[0], 3)
        recs.append(row)

    tbl = pd.DataFrame(recs).sort_values("start").reset_index(drop=True)
    print(f"\n===== 阶段码 {stage_code}：跨批次参数对比 "
          f"(__mean=段内均值, __delta=段内末-首变化) =====")
    print(f"参数中文名: " + ", ".join(
        cn(p) for p in sorted(sub["p_name"].unique())))
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(tbl.to_string(index=False))
    return tbl


def main():
    ap = argparse.ArgumentParser(description="按工艺阶段拆分参数做跨批次对比")
    ap.add_argument("--device", default="102000000996", help="设备编码")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--stage", type=int, default=None,
                    help="锁定的阶段码；省略则只给概览")
    ap.add_argument("--params", default=None,
                    help="对比参数(逗号分隔)；'all'=全部数值参数；省略=合膏机核心")
    ap.add_argument("--save", action="store_true", help="把对比表存到 features_output/_stage/")
    ap.add_argument("--recipe", action="store_true",
                    help="输出图片式阶段配方表(每阶段一行：时长/累计/各参数均值)")
    ap.add_argument("--precise", action="store_true",
                    help="走 raw_json 取全精度值(慢)；默认用 point_value 列(取整, 快)")
    ap.add_argument("--batch_by", choices=["cycle", "end"], default="cycle",
                    help="批次划分：cycle=阶段回到最小码(默认)；end=Tec_End 上升沿")
    args = ap.parse_args()

    dev = pick_device(args.device)
    if not dev:
        print(f"找不到设备 {args.device}")
        return
    print(f"设备: {dev['device_code']} ({dev.get('device_name')})")

    de = data_end(args.device)
    if de is None:
        print("无数据")
        return
    end = pd.Timestamp(de).to_pydatetime()
    start = end - timedelta(days=args.days)
    print(f"窗口: {start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M}  ({args.days}天)")

    # 目标参数集合
    if args.params == "all":
        targets = [p for p in list_param_names(args.device)
                   if p not in (STAGE_PARAM, END_PARAM)]
    elif args.params:
        targets = [p.strip() for p in args.params.split(",") if p.strip()]
    else:
        targets = DEFAULT_TARGETS
    fetch_names = list(dict.fromkeys([STAGE_PARAM, END_PARAM] + targets))

    print(f"\n拉取原始数据({len(fetch_names)} 个参数, "
          f"{'全精度' if args.precise else '列值/快'})...")
    raw = fetch_raw(args.device, fetch_names, start, end, precise=args.precise)
    if raw.empty:
        print("窗口内无数据")
        return

    stage_long = raw[raw["p_name"] == STAGE_PARAM]
    if stage_long.empty:
        print(f"该设备窗口内无阶段参数 {STAGE_PARAM}，无法按阶段分析")
        return
    end_long = raw[raw["p_name"] == END_PARAM]
    target_long = raw[raw["p_name"].isin(targets)]

    seg = build_stage_segments(stage_long, end_long, batch_by=args.batch_by)
    if seg.empty:
        print("阶段段表为空")
        return
    stage_overview(seg)

    merged = attach_segment(target_long, seg)
    stage_signature(merged)

    if args.recipe:
        stage_recipe(merged, seg, args.device, save=args.save)

    if args.stage is not None:
        tbl = stage_param_table(merged, seg, args.stage)
        if tbl is not None and args.save:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            f = OUT_DIR / f"{args.device}_stage{args.stage}_{args.days}d.csv"
            tbl.to_csv(f, index=False, encoding="utf-8-sig")
            print(f"\n已保存: {f}")
    else:
        print("\n提示: 加 --stage <阶段码> 查看该阶段其他参数的跨批次/跨天对比。")


if __name__ == "__main__":
    main()
