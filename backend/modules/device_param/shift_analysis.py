# cython: annotation_typing=False, infer_types=False, language_level=3
"""按班次编排设备分析：一个班次取一次数，四类分析共用，结果分别落库。

原来的流程是每个 Tab 一个端点，各自用任意起止时间独立取数：用户在 ②③④ 之间
切一次 Tab，同一份数据就从库里拉一遍、算一遍；换个时间范围，全部重来。这里把
班次作为分析单位后：

  取一次数 ──┬─→ ①状态&效率
             ├─→ ②能耗
             ├─→ ③KPI（可用率用班次时长当计划生产时间，OEE 名副其实）
             └─→ ④阶段CPK

结果按 (设备, 班次, 类型) 落库。班次结束后数据不再变，缓存永久有效；
进行中的班次标 partial，前端显示计算时刻并允许刷新。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from . import shift_store
from .analysis_service import analyze_state_from_pulse
from .kpi_analysis import (_fetch_batches_and_data, compute_energy_breakdown,
                           compute_kpi_summary, compute_stage_cpk)
from .stage_analysis import analyze_stages, db_device_name
from .shift import ShiftWindow, shifts_in_range, full_days_in_range
from .shift_store import (ALL_TYPES, TYPE_ENERGY, TYPE_KPI, TYPE_STAGE,
                          TYPE_STAGE_RECIPE, TYPE_STATE)


def _needs_batch_data(types: Sequence[str]) -> bool:
    """②③④ 都建立在批次/阶段切分之上；只要①状态就不必做这次重活。"""
    return any(t in (TYPE_ENERGY, TYPE_KPI, TYPE_STAGE, TYPE_STAGE_RECIPE) for t in types)


def analyze_one_shift(db, device_code: str, device_name: str, pulse_param: str,
                      shift: ShiftWindow,
                      analysis_types: Sequence[str] = ALL_TYPES,
                      force: bool = False,
                      selected_points: Optional[List[str]] = None,
                      now: Optional[datetime] = None) -> Dict[str, Any]:
    """算（或读缓存）一个班次的分析结果。

    force=True 跳过缓存强制重算（前端"重新分析"按钮）。
    返回 {shift: {...}, results: {type: result}, cached: [已命中缓存的类型]}
    """
    conn = db.conn
    types = [t for t in analysis_types if t in ALL_TYPES] or list(ALL_TYPES)

    # 班次尚未结束：原始数据还在变化，任何结果都只是半截快照，容易被当成
    # 定论用来考核——直接拒绝分析，等班次结束再算，避免用不完整数据出结果。
    if not shift.is_closed(now):
        msg = f"{shift.label} 尚未结束（{shift.end:%H:%M} 交班后可分析），暂不分析进行中的班次"
        results = {t: {"error": "shift_open", "msg": msg} for t in types}
        return {"shift": shift.to_dict(now), "results": results,
                "cached": [], "computed": [], "skipped": True}

    results: Dict[str, Any] = {}
    cached_types: List[str] = []

    # 1) 先批量读缓存，命中的不再计算
    if not force:
        for t in types:
            hit = shift_store.load(conn, device_code, shift, t, pulse_param)
            if hit is not None:
                results[t] = hit
                cached_types.append(t)
    todo = [t for t in types if t not in results]
    if not todo:
        return {"shift": shift.to_dict(now), "results": results,
                "cached": cached_types, "computed": []}

    # 2) 共享取数：②③④ 用同一份 seg/merged，不各拉一遍
    fetched = None
    if _needs_batch_data(todo):
        fetched = _fetch_batches_and_data(db, device_code, shift.start, shift.end, pulse_param)

    def _run(t: str):
        if t == TYPE_STATE:
            return analyze_state_from_pulse(conn, device_code, device_name, pulse_param,
                                            start_time=shift.start, end_time=shift.end)
        if t == TYPE_KPI:
            # shift 传进去 → 可用率分母用班次计划生产时间（标准 OEE 口径）
            return compute_kpi_summary(db, device_code, pulse_param,
                                       start_time=shift.start, end_time=shift.end,
                                       fetched=fetched, shift=shift)
        if t == TYPE_STAGE:
            return compute_stage_cpk(db, device_code, pulse_param,
                                     start_time=shift.start, end_time=shift.end,
                                     fetched=fetched)
        if t == TYPE_ENERGY:
            return compute_energy_breakdown(db, device_code, pulse_param,
                                            start_time=shift.start, end_time=shift.end,
                                            selected_points=selected_points, fetched=fetched)
        if t == TYPE_STAGE_RECIPE:
            return analyze_stages(db, device_code, shift.start, shift.end,
                                  stage_param_override=pulse_param, fetched=fetched)
        return {"error": "unknown_type", "msg": f"未知分析类型: {t}"}

    computed: List[str] = []
    for t in todo:
        try:
            res = _run(t) or {}
        except Exception as e:
            import traceback
            traceback.print_exc()
            results[t] = {"error": "exception", "msg": f"{t} 分析失败: {e}"}
            continue
        results[t] = res
        computed.append(t)
        # 出错的结果不落库，否则错误会被当成"已分析"永久缓存住
        if "error" not in res:
            try:
                # 走到这里 shift 必然已结束（上面已拦截未结束班次），
                # 结果永久有效，partial 用 shift_store.save 的默认推导即可(False)。
                shift_store.save(conn, device_code, shift, t, res,
                                 pulse_param=pulse_param, now=now)
            except Exception as e:
                print(f"[班次分析] 结果落库失败（不影响返回）{shift.key}/{t}: {e}")

    return {"shift": shift.to_dict(now), "results": results,
            "cached": cached_types, "computed": computed}


def analyze_range(db, device_code: str, pulse_param: str,
                  start: datetime, end: datetime,
                  analysis_types: Sequence[str] = ALL_TYPES,
                  force: bool = False,
                  selected_points: Optional[List[str]] = None,
                  device_name: Optional[str] = None,
                  max_shifts: int = 60,
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    """把时间范围拆成班次逐个分析，结果按班次返回（前端按班次分组展示）。

    首尾不完整的班次会被裁剪并标 partial —— 它们的指标只覆盖部分时间，
    不能和整班的数字直接比较。
    """
    windows = shifts_in_range(start, end)
    if not windows:
        return {"error": "no_shift", "msg": "所选时间范围内没有可分析的班次。"}
    truncated = len(windows) > max_shifts
    if truncated:
        windows = windows[-max_shifts:]      # 超量时保留最近的班次

    dev_name = device_name or db_device_name(db, device_code)
    shifts_out = []
    for w in windows:
        shifts_out.append(analyze_one_shift(
            db, device_code, dev_name, pulse_param, w,
            analysis_types=analysis_types, force=force,
            selected_points=selected_points, now=now,
        ))

    return {
        "device_code": device_code,
        "device_name": dev_name,
        "pulse_param": pulse_param,
        "range": {"start": start.strftime("%Y-%m-%d %H:%M:%S"),
                  "end": end.strftime("%Y-%m-%d %H:%M:%S")},
        "shift_count": len(shifts_out),
        "truncated": truncated,
        "truncate_note": (f"所选范围内班次超过 {max_shifts} 个，只显示最近 {max_shifts} 个班次。"
                          if truncated else None),
        "shifts": shifts_out,
    }


def analyze_full_days_range(db, device_code: str, pulse_param: str,
                            start: datetime, end: datetime,
                            analysis_types: Sequence[str] = (TYPE_ENERGY,),
                            force: bool = False,
                            selected_points: Optional[List[str]] = None,
                            device_name: Optional[str] = None,
                            max_days: int = 31,
                            now: Optional[datetime] = None) -> Dict[str, Any]:
    """把时间范围拆成"天"(06:00→次日06:00)逐个分析，结果按天返回。

    与 analyze_range() 同构，只是以天(而不是班次)为单位——浏览 3 天/1 个月这种
    跨度较大的范围时用天粒度，行数少一半，且掐头去尾是按天独立算的(见
    kpi_analysis._meter_breakdown)，不是把两个班次的结果简单相加。
    默认只分析能耗(②)，因为天粒度目前只有这一个 Tab 需要；analyze_one_shift()
    本身不关心传进去的是班次还是天窗口，以后要加 KPI/阶段的天粒度只需要在
    analysis_types 里加类型，不用改这个函数。
    """
    windows = full_days_in_range(start, end)
    if not windows:
        return {"error": "no_day", "msg": "所选时间范围内没有可分析的天。"}
    truncated = len(windows) > max_days
    if truncated:
        windows = windows[-max_days:]        # 超量时保留最近的天

    dev_name = device_name or db_device_name(db, device_code)
    days_out = []
    for w in windows:
        days_out.append(analyze_one_shift(
            db, device_code, dev_name, pulse_param, w,
            analysis_types=analysis_types, force=force,
            selected_points=selected_points, now=now,
        ))

    return {
        "device_code": device_code,
        "device_name": dev_name,
        "pulse_param": pulse_param,
        "range": {"start": start.strftime("%Y-%m-%d %H:%M:%S"),
                  "end": end.strftime("%Y-%m-%d %H:%M:%S")},
        "day_count": len(days_out),
        "truncated": truncated,
        "truncate_note": (f"所选范围内天数超过 {max_days} 个，只显示最近 {max_days} 天。"
                          if truncated else None),
        "days": days_out,
    }
