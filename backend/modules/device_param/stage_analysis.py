# cython: annotation_typing=False, infer_types=False, language_level=3
"""按工艺阶段(如合膏阶段状态 Tec_DQD_DH)拆分参数，供前端"阶段分析"视图使用。

合膏是批次/循环工艺：一个批次顺序走多个阶段码(0→1→2…)。本模块把阶段码当作
工序标签，将其它参数按 (批次, 阶段) 聚合，产出：

  1) 阶段配方表(stage recipe)：每个阶段码一行，跨批次中位时长 + 累计时间 +
     段内各参数均值/变化Δ，对应工艺配方表的"段号→时间→各列参数"。
  2) 阶段概览：每个阶段码的段数、批次数。
  3) 锁定单阶段(focus)：该阶段在各批次内的参数均值/Δ，用于看跨批次漂移。

离线版同逻辑见 backend/tools/analyze_stage_segments.py。此处为 API 版：
- 数据源 device_alarm_info(实时表)，用 point_value 列(整数, 快)，阶段趋势够用。
- 阶段码是稀疏状态量，须前向填充(merge_asof)而非取均值。
- GAP_TOL_MIN 防批次间停机空档被吞进上一阶段。
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd
from psycopg2.extras import RealDictCursor

# 批次间停机空档超过此分钟数，不再把时间/参数行归给上一阶段
GAP_TOL_MIN = 10

# ── 状态(粗) → 阶段码(细) 分组 ──
# 数据里只有"阶段码"(Tec_DQD_DH 取整 0-15)，"状态"(固化/转换/干燥)不是独立字段，
# 而是按工艺把若干阶段码归并成的高层状态。下表按工艺规则配置；可按设备增改。
# 合膏机阶段码→工序映射（基于实测参数变化特征推断，可按批次工艺校准）：
#   0=待机, 11=出料(铅重急降), 12=进铅粉(铅重爬升),
#   13=加水(水重急降), 14=抽真空搅拌(真空急降),
#   1-5/15=加酸反应(酸重慢降/升温), 6-10=深度搅拌(参数稳定)
STATE_GROUPS = {
    "102000000996": [
        ("进窑", [0]),
        ("固化", list(range(1, 9))),
        ("转换", list(range(9, 15))),
        ("干燥", list(range(15, 21))),
    ],
    # 合膏机通用（含 QSDLHG 的设备编码）
    "_QSDLHG": [
        ("待机", [0]),
        ("出料", [11]),
        ("进铅粉", [12]),
        ("加水", [13]),
        ("抽真空搅拌", [14]),
        ("加酸反应", [1, 2, 3, 4, 5, 15]),
        ("深度搅拌", [6, 7, 8, 9, 10]),
    ],
}


def _mapping_from_groups(groups):
    """[(name,[codes]),...] → (阶段码->状态名 dict, 状态名顺序 list)。groups 空→(None,None)。"""
    if not groups:
        return None, None
    code2state, order = {}, []
    for name, codes in groups:
        order.append(name)
        for c in codes:
            code2state[int(c)] = name
    return code2state, order


def _ensure_config_table(conn):
    """状态分组配置表(工艺可在界面编辑，按设备存一行 JSONB)。"""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_stage_state_config (
                device_code VARCHAR(64) PRIMARY KEY,
                config      JSONB NOT NULL,
                updated_at  TIMESTAMP DEFAULT now(),
                updated_by  VARCHAR(128)
            )
        """)
    conn.commit()


def load_state_groups(conn, device_code):
    """返回 (groups, source)。groups=[(name,[codes]),...]。

    优先读 device_stage_state_config(界面保存的)，其次硬编码 STATE_GROUPS 默认，
    都没有则 (None,'none')。source ∈ {'db','default','none'}。
    """
    try:
        _ensure_config_table(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT config FROM device_stage_state_config WHERE device_code=%s",
                        (device_code,))
            row = cur.fetchone()
        if row and row[0]:
            groups = [(g["state"], [int(c) for c in g.get("codes", [])])
                      for g in row[0] if g.get("state")]
            if groups:
                return groups, "db"
    except Exception as e:
        print(f"[stage] load_state_groups failed: {e}")
    default = STATE_GROUPS.get(device_code)
    # 通配符匹配：key 以 _ 开头的按尾缀(设备编码关键字)匹配
    if default is None:
        for key, val in STATE_GROUPS.items():
            if key.startswith("_") and key[1:] in device_code:
                default = val
                break
    return (default, "default") if default else (None, "none")


def save_state_groups(conn, device_code, config, user=None):
    """保存界面编辑的分组。config=[{state, codes:[...]}, ...]，返回规整后的 config。"""
    import json
    _ensure_config_table(conn)
    cfg = [{"state": g["state"], "codes": sorted({int(c) for c in g.get("codes", [])})}
           for g in config if g.get("state")]
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO device_stage_state_config (device_code, config, updated_at, updated_by)
            VALUES (%s, %s, now(), %s)
            ON CONFLICT (device_code)
            DO UPDATE SET config=EXCLUDED.config, updated_at=now(), updated_by=EXCLUDED.updated_by
        """, (device_code, json.dumps(cfg, ensure_ascii=False), user))
    conn.commit()
    return cfg


def detect_stage_param(name_map: Dict[str, str], conn=None,
                       device_code: Optional[str] = None) -> Optional[str]:
    """找"阶段"参数。优先已确认参数画像(is_stage_param)，回退中文名含'阶段'，再回退已知编码。

    conn/device_code 给定时才查画像；缺失/未确认一律回退现逻辑，不破坏现状。
    """
    if conn is not None and device_code:
        try:
            from . import param_profile
            for p, prof in param_profile.get_confirmed_map(conn, device_code).items():
                if prof.get("is_stage_param") and p in name_map:
                    return p
        except Exception as e:
            print(f"[stage] profile 查阶段参数失败，回退: {e}")
    for code, desc in name_map.items():
        if desc and "阶段" in desc:
            return code
    for known in ("Tec_DQD_DH",):
        if known in name_map:
            return known
    return None


def _fetch_long(conn, device_code: str, start: datetime, end: datetime,
                p_names: Optional[List[str]] = None,
                meter_ids: Optional[List[str]] = None) -> pd.DataFrame:
    """拉取长表 (gather_time, p_name, p_value)。

    device_alarm_info(工艺点位，按 point_value 列，快) + meter_ids 非空时额外 UNION
    device_energy_info(该设备关联电表的能耗点位，见 services.get_energy_device_ids)，
    让能耗点位跟工艺点位一起走后面的分段/跨批次聚合(_build_segments/_attach)——两者
    对 p_name 通用，能耗混进来后阶段配方表/跨批次漂移会自动带上能耗的均值和段内Δ。

    注意：这是唯一需要拉大量原始数据的路径，数据库在远程，数据量大时传输需要时间，
    所以单独设 statement_timeout=300s（不跟常规查询的 60s 共享）。
    """
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '300s'")
    conn.commit()
    def _query(table: str, alias: str, id_params: List[str],
               pt_names: Optional[List[str]] = None) -> pd.DataFrame:
        conds = [f"{alias}.device_id = ANY(%s)", f"{alias}.point_time >= %s", f"{alias}.point_time < %s"]
        params: List[Any] = [id_params, start, end]
        _pn = pt_names if pt_names is not None else p_names
        if _pn:
            conds.append(f"{alias}.point_id = ANY(%s)")
            params.append(_pn)
        sql = """
            SELECT {alias}.point_time AS gather_time, {alias}.point_id AS p_name,
                   {alias}.point_value::text AS p_value
            FROM {table} {alias}
            WHERE {where}
            ORDER BY {alias}.point_time ASC
            LIMIT 200000
        """.format(alias=alias, table=table, where=" AND ".join(conds))
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["gather_time", "p_name", "p_value"])

    frames = [_query("device_alarm_info", "a", [device_code])]
    if meter_ids:
        frames.append(_query("device_energy_info", "e", meter_ids,
                             pt_names=["ene_eptotal", "ene_imp"]))
    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    if not df.empty:
        df["gather_time"] = pd.to_datetime(df["gather_time"])
    return df


def _build_segments(stage_long: pd.DataFrame) -> pd.DataFrame:
    """阶段状态长表 → 段表：连续相同阶段码=一段。

    返回 [seg_id, stage, t_start, t_end, dur_min, batch]。
    批次=阶段码回到最小码(循环起点)递增。
    """
    s = (stage_long[["gather_time", "p_value"]]
         .assign(code=pd.to_numeric(stage_long["p_value"], errors="coerce"))
         .dropna(subset=["code"])
         .sort_values("gather_time"))
    if s.empty:
        return pd.DataFrame()
    s["code"] = s["code"].round().astype(int)

    change = s["code"].ne(s["code"].shift())
    s["seg_id"] = change.cumsum()
    seg = (s.groupby("seg_id")
             .agg(stage=("code", "first"),
                  t_start=("gather_time", "first"),
                  t_last=("gather_time", "last"))
             .reset_index())
    # 段终点延伸到下一段起点(状态量切换前保持)，封顶 t_last+空档容差
    nxt = seg["t_start"].shift(-1)
    cap = seg["t_last"] + pd.Timedelta(minutes=GAP_TOL_MIN)
    seg["t_end"] = nxt.where(nxt.notna(), seg["t_last"]).clip(upper=cap)
    seg["dur_min"] = (seg["t_end"] - seg["t_start"]).dt.total_seconds() / 60

    min_code = seg["stage"].min()
    seg["batch"] = (seg["stage"].eq(min_code) &
                    seg["stage"].shift().ne(min_code)).cumsum()
    return seg


def _attach(target_long: pd.DataFrame, seg: pd.DataFrame) -> pd.DataFrame:
    """merge_asof 把段标签(stage/seg_id/batch)前向填充贴到每条参数行。"""
    t = (target_long.assign(v=pd.to_numeric(target_long["p_value"], errors="coerce"))
                     .dropna(subset=["v"])
                     .sort_values("gather_time"))
    if t.empty:
        return t
    seg_keys = seg[["t_start", "t_end", "seg_id", "stage", "batch"]].sort_values("t_start")
    merged = pd.merge_asof(t, seg_keys, left_on="gather_time",
                           right_on="t_start", direction="backward")
    merged = merged.dropna(subset=["seg_id"])
    # 剔除落在封顶终点之后的行(批次间停机空档不归任何阶段)
    return merged[merged["gather_time"] <= merged["t_end"]]


def _infer_phase(mean: Dict[str, float], delta: Dict[str, float],
                 name_map: Dict[str, str]) -> str:
    """从一段参数均值/Δ反推工序名(合膏机)。纯启发式，仅供参考。

    依据中文名匹配：铅重快升=进铅；酸重快升=加酸；酸重快降=反应耗酸；
    真空度绝对值大=抽真空；温度快升=升温；铅重快降=出料。
    """
    def by_kw(d, kw):
        for code, val in d.items():
            nm = name_map.get(code, code)
            if kw in nm:
                return val
        return None
    lead_d = by_kw(delta, "铅")
    sour_d = by_kw(delta, "酸")
    vac_m = by_kw(mean, "真空")
    tep_d = by_kw(delta, "温")
    tags = []
    if lead_d is not None and lead_d > 50:
        tags.append("进铅")
    if sour_d is not None and sour_d > 20:
        tags.append("加酸")
    if sour_d is not None and sour_d < -20:
        tags.append("反应耗酸")
    if vac_m is not None and abs(vac_m) > 600:
        tags.append("抽真空")
    if tep_d is not None and tep_d > 5:
        tags.append("升温")
    if lead_d is not None and lead_d < -100:
        tags.append("出料")
    return "/".join(tags)


def analyze_stages(
    db,
    device_code: str,
    start: datetime,
    end: datetime,
    focus_stage: Optional[int] = None,
    focus_state: Optional[str] = None,
) -> Dict[str, Any]:
    """主入口：返回阶段配方表 + 概览(+ 锁定阶段的跨批次表)。db 为已连接的 TimescaleDB。"""
    conn = db.conn
    name_map = db.get_point_names(device_code)   # p_name -> 中文名
    unit_map = db.get_point_units(device_code)   # p_name -> 单位

    stage_param = detect_stage_param(name_map, conn=conn, device_code=device_code)
    if not stage_param:
        return {"error": "no_stage_param",
                "msg": "该设备没有可识别的'阶段'参数(中文名含'阶段')，无法按阶段分析。"}

    meter_ids = db.get_energy_device_ids(device_code)
    raw = _fetch_long(conn, device_code, start, end, meter_ids=meter_ids)
    if raw.empty:
        return {"error": "no_data", "msg": "该时间范围内无参数数据。"}

    stage_long = raw[raw["p_name"] == stage_param]
    if stage_long.empty:
        return {"error": "no_stage_data",
                "msg": f"窗口内无阶段参数 {stage_param} 数据。"}

    seg = _build_segments(stage_long)
    if seg.empty:
        return {"error": "no_segments", "msg": "未能从阶段参数构造出段。"}

    target_long = raw[raw["p_name"] != stage_param]
    merged = _attach(target_long, seg)

    # 段内均值 / 段内变化Δ（先按 seg 聚合，再跨批次平均）
    per_seg = (merged.groupby(["stage", "seg_id", "p_name"])["v"]
               .agg(mean="mean", first="first", last="last").reset_index())
    per_seg["delta"] = per_seg["last"] - per_seg["first"]
    mean_by = (per_seg.groupby(["stage", "p_name"])["mean"].mean())
    delta_by = (per_seg.groupby(["stage", "p_name"])["delta"].mean())

    # 每阶段时长(跨批次中位)、段数
    dur_med = seg.groupby("stage")["dur_min"].median()
    seg_cnt = seg.groupby("stage")["seg_id"].count()

    # 出现的参数集合(只保留有数值的)
    present = sorted(per_seg["p_name"].unique().tolist())
    params_meta = [{"p_name": p,
                    "display_name": name_map.get(p, p),
                    "unit": unit_map.get(p, "")}
                   for p in present]

    groups, groups_source = load_state_groups(conn, device_code)
    code2state, state_order = _mapping_from_groups(groups)

    def _state_of(st):
        if code2state is None:
            return None
        return code2state.get(int(st), "其他")

    stages_out = []
    cum = 0.0
    for st in sorted(seg["stage"].unique().tolist()):
        d = round(float(dur_med.get(st, 0.0)), 2)
        cum = round(cum + d, 2)
        means = {p: round(float(mean_by.get((st, p))), 3)
                 for p in present if (st, p) in mean_by.index}
        deltas = {p: round(float(delta_by.get((st, p))), 3)
                  for p in present if (st, p) in delta_by.index}
        phase = _infer_phase(means, deltas, name_map)
        state = _state_of(st)
        # 无配置映射时，用启发式推断的阶段名作为显示名
        display_state = state if state and state != "其他" else (phase or state or "")
        stages_out.append({
            "stage": int(st),
            "state": display_state,
            "phase_guess": phase,
            "dur_min": d,
            "cum_min": cum,
            "seg_count": int(seg_cnt.get(st, 0)),
            "means": means,
            "deltas": deltas,
        })

    # ── 状态级聚合(把阶段码归并成状态) ──
    states_out = []
    state_map_out = []
    if code2state is not None:
        seg_s = seg.assign(state=seg["stage"].map(lambda c: _state_of(c)))
        merged_s = merged.assign(state=merged["stage"].map(lambda c: _state_of(c)))
        # 每状态时长：每批次该状态内各段时长之和，再跨批次取中位
        st_dur = (seg_s.groupby(["batch", "state"])["dur_min"].sum()
                       .groupby("state").median())
        st_segcnt = seg_s.groupby("state")["seg_id"].count()
        # 每状态参数：批次内该状态窗口的 mean / Δ(末-首)，再跨批次平均
        ps = (merged_s.sort_values("gather_time")
              .groupby(["state", "batch", "p_name"])["v"]
              .agg(mean="mean", first="first", last="last").reset_index())
        ps["delta"] = ps["last"] - ps["first"]
        s_mean = ps.groupby(["state", "p_name"])["mean"].mean()
        s_delta = ps.groupby(["state", "p_name"])["delta"].mean()
        present_states = [s for s in (state_order or []) if s in st_segcnt.index]
        # 配置外的码归到"其他"，补到末尾
        for extra in sorted(set(seg_s["state"]) - set(present_states)):
            present_states.append(extra)
        cum_s = 0.0
        for name in present_states:
            d = round(float(st_dur.get(name, 0.0)), 2)
            cum_s = round(cum_s + d, 2)
            codes = sorted(int(c) for c, s in (code2state or {}).items()
                           if s == name and c in set(seg["stage"].tolist()))
            means = {p: round(float(s_mean.get((name, p))), 3)
                     for p in present if (name, p) in s_mean.index}
            deltas = {p: round(float(s_delta.get((name, p))), 3)
                      for p in present if (name, p) in s_delta.index}
            states_out.append({
                "state": name,
                "stage_codes": codes,
                "dur_min": d,
                "cum_min": cum_s,
                "seg_count": int(st_segcnt.get(name, 0)),
                "means": means,
                "deltas": deltas,
            })
        state_map_out = [{"state": n, "codes": c} for n, c in (groups or [])]

    # ── 周期-阶段排列(每周期内各段的实际起止与时长，供前端画周期排列图) ──
    batches_out = []
    for b, grp in seg.groupby("batch"):
        grp = grp.sort_values("t_start")
        batches_out.append({
            "batch": int(b),
            "start": grp["t_start"].min().strftime("%Y-%m-%d %H:%M:%S"),
            "end": grp["t_end"].max().strftime("%Y-%m-%d %H:%M:%S"),
            "dur_min": round(float(grp["dur_min"].sum()), 1),
            "segments": [{
                "stage": int(r.stage),
                "state": _state_of(r.stage),
                "start": r.t_start.strftime("%H:%M"),
                "dur_min": round(float(r.dur_min), 1),
            } for r in grp.itertuples()],
        })

    result = {
        "device_code": device_code,
        "device_name": db_device_name(db, device_code),
        "stage_param": {"p_name": stage_param,
                        "display_name": name_map.get(stage_param, stage_param)},
        "window": {
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end.strftime("%Y-%m-%d %H:%M:%S"),
            "days": round((end - start).total_seconds() / 86400, 2),
            "batch_count": int(seg["batch"].nunique()),
            # 一个周期(批次走完全部阶段)的中位时长，用于按周期长决定回溯窗口
            "cycle_min": round(float(seg.groupby("batch")["dur_min"].sum().median()), 2),
        },
        "params": params_meta,
        "batches": batches_out,
        "stages": stages_out,
        "states": states_out,
        "state_map": state_map_out,
        "state_map_is_default": groups_source != "db",
    }

    if focus_stage is not None:
        result["focus"] = _focus(merged, "stage", merged["stage"] == focus_stage,
                                 {"stage": int(focus_stage)})
    elif focus_state is not None and code2state is not None:
        mask = merged["stage"].map(lambda c: _state_of(c)) == focus_state
        result["focus"] = _focus(merged, "state", mask, {"state": focus_state})

    return result


def db_device_name(db, device_code: str) -> str:
    try:
        with db.conn.cursor() as cur:
            cur.execute("SELECT device_name FROM device_info WHERE device_id=%s LIMIT 1",
                        (device_code,))
            r = cur.fetchone()
            return r[0] if r else device_code
    except Exception:
        return device_code


def _focus(merged: pd.DataFrame, level: str, mask, label: Dict[str, Any]) -> Dict[str, Any]:
    """锁定某阶段/状态：每批次该窗口内各参数 mean / Δ(末-首)，按时间排序(看跨批次漂移)。

    level='stage' 时按 (批次,段) 分组；'state' 时按批次整段窗口分组(状态跨多段)。
    """
    sub = merged[mask]
    out = {**label, "level": level, "batches": []}
    if sub.empty:
        return out
    group_keys = ["batch", "seg_id"] if level == "stage" else ["batch"]
    batches = []
    for keys, grp in sub.groupby(group_keys):
        batch = keys[0] if isinstance(keys, tuple) else keys
        grp = grp.sort_values("gather_time")
        t0 = grp["gather_time"].min()
        row = {
            "batch": int(batch),
            "day": t0.strftime("%Y-%m-%d"),
            "start": t0.strftime("%Y-%m-%d %H:%M:%S"),
            "dur_min": round((grp["gather_time"].max() - t0).total_seconds() / 60, 1),
            "means": {}, "deltas": {},
        }
        for p, pg in grp.groupby("p_name"):
            pg = pg.sort_values("gather_time")
            row["means"][p] = round(float(pg["v"].mean()), 3)
            row["deltas"][p] = round(float(pg["v"].iloc[-1] - pg["v"].iloc[0]), 3)
        batches.append(row)
    batches.sort(key=lambda r: r["start"])
    out["batches"] = batches
    return out
