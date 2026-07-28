# cython: annotation_typing=False, infer_types=False, language_level=3
"""设备参数 API 路由"""
import os
from datetime import datetime, date, timedelta
from typing import Optional, List
from collections import defaultdict

import numpy as np
import pandas as pd

from fastapi import APIRouter, Query
from pydantic import BaseModel

from core.response import success_response, error_response
from .services import TimescaleDB
from .analysis_service import analyze_device_params
from .anomaly_detector import AnomalyDetector, get_detector
from .stage_analysis import analyze_stages, save_state_groups, detect_stage_param
from . import stats_store
from . import param_profile
from . import advanced_analysis
from . import insight_cache
from . import analysis_log
from .rollup_worker import run_rollup_job

router = APIRouter(prefix="/api/device-params", tags=["device-params"])


class ParamDataRequest(BaseModel):
    device_code: str
    p_name: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    hours: int = 24


class ParamAnalysisRequest(BaseModel):
    device_code: str
    device_name: Optional[str] = None
    p_name: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    hours: int = 24
    analyze_running_only: Optional[bool] = True


@router.get("/devices")
def list_devices():
    """获取所有设备列表"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)

    try:
        devices = db.get_devices()
        return success_response(data=devices)
    except Exception as e:
        return error_response(msg=f"查询设备列表失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/points")
def list_points(
    device_code: str = Query(..., description="设备编号")
):
    """获取指定设备的参数点位列表"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)

    try:
        points = db.get_points(device_code)
        return success_response(data=points)
    except Exception as e:
        return error_response(msg=f"查询点位列表失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/data")
def get_param_data(
    device_code: str = Query(..., description="设备编号"),
    p_name: Optional[str] = Query(None, description="点位名称（留空查询所有点位）"),
    p_names: Optional[List[str]] = Query(None, description="多个点位名称，逗号分隔（优先级高于 p_name）"),
    start_time: Optional[str] = Query(None, description="开始时间 (YYYY-MM-DD HH:MM:SS)"),
    end_time: Optional[str] = Query(None, description="结束时间 (YYYY-MM-DD HH:MM:SS)"),
    hours: int = Query(24, ge=1, le=168, description="查询最近多少小时（当未指定时间范围时）"),
    limit: int = Query(300000, ge=1, le=500000, description="最大返回条数"),
    interval: str = Query("raw", description="聚合粒度: raw(原始) / auto(按跨度自动) / 5min / 15min / 1hour / 4hour / 1day"),
):
    """
    获取设备参数时间序列数据

    返回结果按点位名称分组，便于前端绘制多系列折线图。

    interval=raw（默认）返回原始数据；其余值走 time_bucket 聚合，
    每个点附带 value(avg)/min/max/std/count，并在返回中带回实际使用的 interval。
    """
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)

    try:
        # 解析时间
        st: Optional[datetime] = None
        et: Optional[datetime] = None

        if start_time:
            try:
                st = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    st = datetime.strptime(start_time, "%Y-%m-%d")
                except ValueError:
                    return error_response(msg="开始时间格式错误", code=400)
        if end_time:
            try:
                et = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    et = datetime.strptime(end_time, "%Y-%m-%d")
                    et = et + timedelta(days=1, seconds=-1)
                except ValueError:
                    return error_response(msg="结束时间格式错误", code=400)

        if not st and not et:
            et = datetime.now()
            st = et - timedelta(hours=hours)

        # 聚合模式：time_bucket 多粒度，避免大跨度返回海量原始点
        if interval and interval != "raw":
            agg = db.get_param_data_aggregated(
                device_code=device_code, start_time=st, end_time=et,
                p_name=p_name, p_names=p_names, interval=interval,
            )
            series = agg["series"]
            name_map = db.get_point_names(device_code)
            unit_map = db.get_point_units(device_code)
            stage_param = detect_stage_param(name_map)
            if stage_param and stage_param in series:
                # 阶段码是离散标识，聚合(AVG)无意义，用原始值替换
                raw_rows = db.get_param_data(
                    device_code=device_code, p_name=stage_param,
                    start_time=st, end_time=et, limit=100000,
                )
                raw_pts = []
                for row in raw_rows:
                    v = row["p_value_num"] if row["p_value_num"] is not None else row["p_value_raw"]
                    if isinstance(v, (int, float)):
                        v = int(round(float(v)))
                    raw_pts.append({
                        "time": row["gather_time"].strftime("%Y-%m-%d %H:%M:%S") if row["gather_time"] else None,
                        "value": v,
                    })
                series[stage_param] = raw_pts
            total = sum(len(v) for v in series.values())
            return success_response(data={
                "device_code": device_code,
                "p_name": p_name,
                "start_time": st.strftime("%Y-%m-%d %H:%M:%S") if st else None,
                "end_time": et.strftime("%Y-%m-%d %H:%M:%S") if et else None,
                "interval": agg["interval"],
                "aggregated": True,
                "series": series,
                "display_names": {k: name_map.get(k, k) for k in series.keys()},
                "units": {k: unit_map.get(k, "") for k in series.keys()},
                "total": total,
            })

        rows = db.get_param_data(
            device_code=device_code,
            p_name=p_name,
            p_names=p_names,
            start_time=st,
            end_time=et,
            limit=limit,
        )

        # 获取点位名称映射
        name_map = db.get_point_names(device_code)
        unit_map = db.get_point_units(device_code)

        # 按点位分组
        grouped: dict = {}
        for row in rows:
            point = row["p_name"]
            if point not in grouped:
                grouped[point] = []
            grouped[point].append({
                "time": row["gather_time"].strftime("%Y-%m-%d %H:%M:%S") if row["gather_time"] else None,
                "value": row["p_value_num"] if row["p_value_num"] is not None else row["p_value_raw"],
                "raw_value": row["p_value_raw"],
            })

        # 构建 display_name 映射（p_name -> 中文名）
        display_names = {k: name_map.get(k, k) for k in grouped.keys()}
        # 构建 unit 映射（p_name -> 单位）
        units = {k: unit_map.get(k, "") for k in grouped.keys()}

        return success_response(data={
            "device_code": device_code,
            "p_name": p_name,
            "start_time": st.strftime("%Y-%m-%d %H:%M:%S") if st else None,
            "end_time": et.strftime("%Y-%m-%d %H:%M:%S") if et else None,
            "series": grouped,
            "display_names": display_names,
            "units": units,
            "total": len(rows),
        })
    except Exception as e:
        return error_response(msg=f"查询参数数据失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/running-periods")
def get_running_periods(
    device_code: str = Query(..., description="设备编号"),
    start_time: str = Query(..., description="开始时间 (YYYY-MM-DD HH:MM:SS)"),
    end_time: str = Query(..., description="结束时间 (YYYY-MM-DD HH:MM:SS)"),
):
    """查询设备在指定时间范围内的运行时段"""
    try:
        st = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        et = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return error_response(msg="时间格式错误，应为 YYYY-MM-DD HH:MM:SS", code=400)

    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)

    try:
        status_code = db.get_running_status_code()
        if status_code is None:
            return success_response(data=[])

        device_id = db.get_device_id_by_code(device_code)
        if device_id is None:
            return success_response(data={
                "status_code": status_code,
                "periods": [],
            })
        periods = db.get_running_periods(device_id, status_code, st, et)
        return success_response(data={
            "status_code": status_code,
            "periods": periods,
        })
    except Exception as e:
        return error_response(msg=f"查询运行时段失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/aligned-data")
def get_aligned_data(
    device_code: str = Query(..., description="设备编号"),
    start_time: str = Query(..., description="开始时间 (YYYY-MM-DD HH:MM:SS)"),
    end_time: str = Query(..., description="结束时间 (YYYY-MM-DD HH:MM:SS)"),
    alarm_window_min: int = Query(15, ge=5, le=120, description="告警计数滑动窗口(分钟)"),
    limit: int = Query(5000, ge=1, le=20000, description="最大返回条数"),
):
    """
    获取参数+告警时间对齐数据

    以参数采集时间线为主轴，将告警事件左连接，返回:
    - aligned_rows: [timestamp, param1...paramN, active_alarms, alarm_count_{window}min]
    - alarm_events: 完整告警事件列表（用于前端独立渲染告警带）
    - params_meta: 参数元数据 (display_name, unit)
    """
    st = _parse_time(start_time)
    et = _parse_time(end_time)
    if not st or not et:
        return error_response(msg="时间格式错误，应为 YYYY-MM-DD HH:MM:SS", code=400)

    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)

    try:
        # 1. 获取设备 ID
        device_id = db.get_device_id_by_code(device_code)
        if device_id is None:
            return error_response(msg=f"未找到设备: {device_code}", code=404)

        # 2. 获取参数数据
        rows = db.get_param_data(
            device_code=device_code, p_name=None,
            start_time=st, end_time=et, limit=limit,
        )

        # 3. 获取告警事件
        alarm_events = db.get_alarm_events(device_id, st, et)

        # 4. 构建参数元数据
        name_map = db.get_point_names(device_code)
        unit_map = db.get_point_units(device_code)

        # 5. 时间对齐：以参数时间戳为主轴
        # 收集所有时间戳和参数值
        time_params: dict = defaultdict(dict)  # {timestamp: {p_name: value}}
        param_names: set = set()

        for row in rows:
            ts = row["gather_time"]
            if isinstance(ts, datetime):
                ts_key = ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts_key = str(ts)
            pn = row["p_name"]
            try:
                val = float(row["p_value"])
            except (ValueError, TypeError):
                val = None
            time_params[ts_key][pn] = val
            param_names.add(pn)

        # 按时间排序
        sorted_times = sorted(time_params.keys())

        # 6. 为每个时间点计算告警衍生列
        alarm_window = timedelta(minutes=alarm_window_min)
        ALARM_STATUSES = {2, 3, 4, 5}  # 报警、待机、调试、上下料

        # 将告警事件解析为可查询结构
        parsed_alarms = []
        for ev in alarm_events:
            s = ev["start_time"]
            e = ev.get("end_time")
            if isinstance(s, str):
                s_dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            else:
                s_dt = s
            if e and isinstance(e, str):
                e_dt = datetime.strptime(e, "%Y-%m-%d %H:%M:%S")
            elif e and isinstance(e, datetime):
                e_dt = e
            else:
                e_dt = None
            parsed_alarms.append({
                **ev,
                "start_dt": s_dt,
                "end_dt": e_dt,
            })

        aligned_rows = []
        for ts_str in sorted_times:
            ts_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")

            # 当前活跃的告警
            active_now = []
            for al in parsed_alarms:
                if al["start_dt"] <= ts_dt and (al["end_dt"] is None or al["end_dt"] >= ts_dt):
                    active_now.append({
                        "status": al["status"],
                        "status_name": al["status_name"],
                        "start_time": al["start_time"],
                    })

            # 过去 N 分钟内各类告警的累计次数
            ws = ts_dt - alarm_window
            alarm_count_window = 0
            active_alarm_types: set = set()

            for al in parsed_alarms:
                if al["start_dt"] >= ws and al["start_dt"] <= ts_dt:
                    if al["status"] in ALARM_STATUSES:
                        alarm_count_window += 1
                        active_alarm_types.add(al["status_name"])

            # 当前是否存在某类告警
            row = {
                "timestamp": ts_str,
                "params": time_params[ts_str],
                "active_alarms": active_now,
                "is_any_alarm": 1 if active_now else 0,
                f"alarm_count_{alarm_window_min}min": alarm_count_window,
                "active_alarm_types": list(active_alarm_types),
            }
            aligned_rows.append(row)

        # 7. 构建参数元数据
        params_meta = {}
        for pn in sorted(param_names):
            params_meta[pn] = {
                "display_name": name_map.get(pn, pn),
                "unit": unit_map.get(pn, ""),
            }

        return success_response(data={
            "device_code": device_code,
            "start_time": st.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": et.strftime("%Y-%m-%d %H:%M:%S"),
            "alarm_window_min": alarm_window_min,
            "total_rows": len(aligned_rows),
            "alarm_events": alarm_events,
            "aligned_rows": aligned_rows[:500],  # 前端折线图最多 500 点
            "params_meta": params_meta,
        })
    except Exception as e:
        return error_response(msg=f"查询对齐数据失败: {str(e)}", code=500)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════
# 阶段分析（按工艺阶段拆分参数）
# ═══════════════════════════════════════════════════════

@router.get("/stage-analysis")
def get_stage_analysis(
    device_code: str = Query(..., description="设备编号"),
    days: float = Query(3, ge=0.25, le=14, description="回溯天数(以最新数据为终点)"),
    start_time: Optional[str] = Query(None, description="开始时间(覆盖 days)"),
    end_time: Optional[str] = Query(None, description="结束时间(覆盖 days)"),
    focus_stage: Optional[int] = Query(None, description="锁定阶段码，返回该阶段跨批次对比"),
    focus_state: Optional[str] = Query(None, description="锁定状态名(固化/转换/干燥…)，返回该状态跨批次对比"),
    min_cycles: int = Query(3, ge=1, le=20, description="对比最少周期数：窗口不足时按周期长自动回溯扩展"),
):
    """
    按工艺阶段(合膏阶段状态 Tec_DQD_DH)拆分参数，支持状态(粗)与阶段(细)两级。

    返回：
    - stage_param: 识别到的阶段参数
    - stages: 阶段配方表(每阶段：状态/时长/累计/段内各参数均值与变化Δ + 工序推测)
    - states: 状态级配方表(把阶段码归并成 固化/转换/干燥… 后的聚合)
    - state_map: 状态→阶段码 分组配置
    - params: 出现的参数(中文名/单位)
    - window.batch_count: 窗口内批次数
    - focus(可选): 锁定阶段/状态的跨批次明细(focus_stage 或 focus_state)
    """
    st = _parse_time(start_time) if start_time else None
    et = _parse_time(end_time) if end_time else None
    if start_time and st is None:
        return error_response(msg="开始时间格式错误", code=400)
    if end_time and et is None:
        return error_response(msg="结束时间格式错误", code=400)

    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        # 显式时间范围：原样分析(钻取时复用同一窗口，不自动扩展)
        if st and et:
            result = analyze_stages(db, device_code, st, et,
                                    focus_stage=focus_stage, focus_state=focus_state)
            if result.get("error"):
                return error_response(msg=result.get("msg", "阶段分析失败"), code=400)
            return success_response(data=result)

        # 否则以最新数据为终点回溯 days；若批次(周期)数 < min_cycles，按需自动扩窗
        latest = db.get_latest_param_time(device_code)
        et = latest or datetime.now()
        days_try = days
        result = None
        for _ in range(4):
            st = et - timedelta(days=days_try)
            result = analyze_stages(db, device_code, st, et,
                                    focus_stage=focus_stage, focus_state=focus_state)
            if result.get("error"):
                return error_response(msg=result.get("msg", "阶段分析失败"), code=400)
            bc = result.get("window", {}).get("batch_count", 0)
            if bc >= min_cycles or days_try >= 30:
                break
            # 按"还差几个周期"放大窗口(至少×2)，封顶 30 天
            factor = max(2, (min_cycles + 1) / max(bc, 1))
            days_try = min(round(days_try * factor, 2), 30)
        result["window"]["requested_days"] = days
        result["window"]["auto_extended"] = result["window"]["days"] > days + 0.01
        result["window"]["min_cycles"] = min_cycles
        return success_response(data=result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"阶段分析失败: {str(e)}", code=500)
    finally:
        db.close()


class StageStateConfigRequest(BaseModel):
    device_code: str
    config: List[dict]   # [{"state": "固化", "codes": [1,2,...]}, ...]
    updated_by: Optional[str] = None


@router.post("/stage-state-config")
def save_stage_state_config(req: StageStateConfigRequest):
    """保存工艺在界面编辑的"状态→阶段码"分组(按设备)。保存后阶段分析即按新分组聚合。"""
    if not req.device_code:
        return error_response(msg="缺少 device_code", code=400)
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        cfg = save_state_groups(db.conn, req.device_code, req.config, user=req.updated_by)
        return success_response(data={"device_code": req.device_code, "config": cfg})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"保存状态分组失败: {str(e)}", code=500)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════
# 趋势漂移：预计算汇总只读 + 预警快照 + 配置 + 手动触发
# ═══════════════════════════════════════════════════════

@router.get("/stats-summary")
def get_stats_summary(
    device_code: str = Query(..., description="设备编号"),
    metric: str = Query(..., description="参数 p_name，或合成键 stage_dur_min(阶段时长)"),
    days: int = Query(30, ge=1, le=365, description="回溯天数"),
    stage: Optional[int] = Query(None, description="阶段码；留空=整天汇总"),
    end_date: Optional[str] = Query(None, description="结束日 YYYY-MM-DD，缺省=今天"),
    running_only: bool = Query(True, description="是否仅运行时段口径"),
):
    """读底表按任意天数汇总：均值/方差/标准差/极值精确重算，中位数为日中位近似。"""
    try:
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    except ValueError:
        return error_response(msg="结束日格式错误，应为 YYYY-MM-DD", code=400)
    start_d = end_d - timedelta(days=days)

    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        stats_store.ensure_tables(db.conn)
        data = stats_store.rollup(db.conn, device_code, metric, start_d, end_d,
                                  stage=stage, running_only=running_only)
        return success_response(data=data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"汇总查询失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/stats-overview")
def get_stats_overview(
    device_code: str = Query(..., description="设备编号"),
    days: int = Query(30, ge=1, le=365, description="回溯天数"),
    end_date: Optional[str] = Query(None, description="结束日 YYYY-MM-DD，缺省=今天"),
    running_only: bool = Query(True, description="仅运行时段口径"),
):
    """全部参数的趋势总览：每参数 统计(均值/中位/方差/标准差/均差/极值) + 内联趋势 + 序列。

    即使没有任何漂移预警，本接口也返回所有参数的统计与趋势小图数据（页面不再空白）。
    """
    try:
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    except ValueError:
        return error_response(msg="结束日格式错误，应为 YYYY-MM-DD", code=400)
    start_d = end_d - timedelta(days=days)

    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        stats_store.ensure_tables(db.conn)
        metrics = stats_store.stats_overview(db.conn, db, device_code, start_d, end_d,
                                             running_only=running_only)
        return success_response(data={"device_code": device_code, "days": days,
                                      "start": str(start_d), "end": str(end_d),
                                      "count": len(metrics), "metrics": metrics})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"趋势总览查询失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/stats-series")
def get_stats_series(
    device_code: str = Query(..., description="设备编号"),
    metric: str = Query(..., description="参数 p_name 或合成键 stage_dur_min"),
    days: int = Query(30, ge=1, le=365, description="回溯天数"),
    stage: Optional[int] = Query(None, description="阶段码；留空=整天"),
    end_date: Optional[str] = Query(None, description="结束日 YYYY-MM-DD，缺省=今天"),
    running_only: bool = Query(True, description="仅运行时段口径"),
):
    """日级序列（给前端画 sparkline / 趋势小图）。"""
    try:
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    except ValueError:
        return error_response(msg="结束日格式错误，应为 YYYY-MM-DD", code=400)
    start_d = end_d - timedelta(days=days)

    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        stats_store.ensure_tables(db.conn)
        series = stats_store.daily_series(db.conn, device_code, metric, start_d, end_d,
                                          stage=stage, running_only=running_only)
        return success_response(data={"device_code": device_code, "metric": metric,
                                      "stage": stage, "series": series})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"序列查询失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/trend-alerts")
def get_trend_alerts(
    device_code: str = Query(..., description="设备编号"),
    severity: Optional[str] = Query(None, description="筛选 info/warning/critical"),
    baseline_days: Optional[int] = Query(None, description="基线天数(对应快照)"),
    eval_date: Optional[str] = Query(None, description="评估日 YYYY-MM-DD，缺省=最新"),
):
    """读漂移预警快照（页面"趋势预警"列表 / 日报消费）。"""
    ed = None
    if eval_date:
        try:
            ed = datetime.strptime(eval_date, "%Y-%m-%d").date()
        except ValueError:
            return error_response(msg="评估日格式错误，应为 YYYY-MM-DD", code=400)

    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        stats_store.ensure_tables(db.conn)
        alerts = stats_store.read_trend_alerts(db.conn, device_code, eval_date=ed,
                                               severity=severity,
                                               baseline_days=baseline_days)
        return success_response(data={"device_code": device_code,
                                      "eval_date": str(ed) if ed else None,
                                      "count": len(alerts), "alerts": alerts})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"读取趋势预警失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/drift-config")
def get_drift_config(device_code: str = Query(..., description="设备编号")):
    """读盯参/阈值配置（无配置时返回按数据派生的默认 + is_default=True）。"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        stats_store.ensure_tables(db.conn)
        watch, source = stats_store.load_drift_config(db.conn, db, device_code)
        return success_response(data={"device_code": device_code,
                                      "is_default": source != "db",
                                      "watch": watch})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"读取漂移配置失败: {str(e)}", code=500)
    finally:
        db.close()


class DriftConfigRequest(BaseModel):
    device_code: str
    config: List[dict]   # [{"metric","stage?","baseline_days?","warn_pct?",...,"enabled?"}]
    updated_by: Optional[str] = None


@router.post("/drift-config")
def save_drift_config_route(req: DriftConfigRequest):
    """保存界面编辑的盯参/阈值配置（按设备）。"""
    if not req.device_code:
        return error_response(msg="缺少 device_code", code=400)
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        cfg = stats_store.save_drift_config(db.conn, req.device_code, req.config,
                                            user=req.updated_by)
        return success_response(data={"device_code": req.device_code, "config": cfg})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"保存漂移配置失败: {str(e)}", code=500)
    finally:
        db.close()


@router.post("/rollup/run")
def run_rollup(
    device_code: Optional[str] = Query(None, description="仅处理该设备；留空=全部"),
    days: int = Query(0, ge=0, le=365, description="回填天数(0=只算评估日当天)"),
    eval_date: Optional[str] = Query(None, description="评估日 YYYY-MM-DD，缺省=昨天"),
    running_only: bool = Query(True, description="统计口径：仅运行时段"),
    force: bool = Query(False, description="重算已存在的日"),
    background: bool = Query(False, description="后台异步执行(大跨度回填用,立即返回免超时)"),
):
    """手动触发汇总/回填（首次回填、联调用，免等定时）。

    大跨度回填较慢：background=true 时后台执行立即返回（**最近的天最先生成**，
    前端稍后刷新即可陆续看到）；background=false 同步返回完整 summary。
    """
    ed = None
    if eval_date:
        try:
            ed = datetime.strptime(eval_date, "%Y-%m-%d").date()
        except ValueError:
            return error_response(msg="评估日格式错误，应为 YYYY-MM-DD", code=400)
    try:
        if background:
            import threading

            def _bg():
                try:
                    run_rollup_job(report_date=ed, backfill_days=days,
                                   device_code=device_code, running_only=running_only,
                                   force=force)
                except Exception as ex:
                    import logging
                    logging.getLogger(__name__).error(f"后台回填失败: {ex}", exc_info=True)

            threading.Thread(target=_bg, name="rollup-backfill", daemon=True).start()
            return success_response(data={"triggered": True, "background": True,
                                          "msg": "已在后台回填，最近的天最先生成，请稍后刷新。"})
        result = run_rollup_job(report_date=ed, backfill_days=days,
                                device_code=device_code, running_only=running_only,
                                force=force)
        return success_response(data=result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"汇总任务失败: {str(e)}", code=500)


# ═══════════════════════════════════════════════════════
# 参数画像自适应层（AI 建议 + 人确认）+ Cpk 过程能力
# ═══════════════════════════════════════════════════════

@router.post("/profile/suggest")
async def suggest_param_profile(
    device_code: str = Query(..., description="设备编号"),
    use_llm: bool = Query(True, description="是否调用 LLM 提语义（关掉则纯统计签名）"),
    sample_days: int = Query(1, ge=1, le=7, description="统计签名采样天数"),
):
    """AI 识别：对设备全部参数产出"建议"画像(confirmed=false)，写库并返回供界面审阅。"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        profiles = await param_profile.build_profiles(
            db, device_code, sample_days=sample_days, use_llm=use_llm)
        n = param_profile.save_suggestions(db.conn, device_code, profiles)
        return success_response(data={"device_code": device_code, "count": n,
                                      "profiles": profiles})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"参数画像识别失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/profile")
def get_param_profile(device_code: str = Query(..., description="设备编号")):
    """读设备全部参数画像（含 confirmed 状态）。"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        profiles = param_profile.load_profiles(db.conn, device_code)
        return success_response(data={"device_code": device_code,
                                      "count": len(profiles), "profiles": profiles})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"读取参数画像失败: {str(e)}", code=500)
    finally:
        db.close()


class ProfileConfirmRequest(BaseModel):
    device_code: str
    p_name: str
    profile: dict
    updated_by: Optional[str] = None


@router.post("/profile")
def save_param_profile(req: ProfileConfirmRequest):
    """工艺编辑/确认单个参数画像（confirmed=true，高风险用途生效前置）。"""
    if not req.device_code or not req.p_name:
        return error_response(msg="缺少 device_code 或 p_name", code=400)
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        param_profile.save_confirmed(db.conn, req.device_code, req.p_name,
                                     req.profile, user=req.updated_by)
        return success_response(data={"device_code": req.device_code, "p_name": req.p_name})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"保存参数画像失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/cpk")
def get_cpk(
    device_code: str = Query(..., description="设备编号"),
    days: int = Query(30, ge=1, le=365, description="回溯天数"),
    p_name: Optional[str] = Query(None, description="参数；留空=所有连续/设定量参数"),
    end_date: Optional[str] = Query(None, description="结束日 YYYY-MM-DD，缺省=今天"),
    running_only: bool = Query(True, description="仅运行时段口径"),
    refresh: bool = Query(False, description="强制现算并刷新缓存(仅全参数时缓存)"),
):
    """过程能力 Cpk/Cp/Ca：读 device_param_daily_stats 精确 mean/std + 画像 spec。"""
    try:
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    except ValueError:
        return error_response(msg="结束日格式错误，应为 YYYY-MM-DD", code=400)
    start_d = end_d - timedelta(days=days)

    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        stats_store.ensure_tables(db.conn)

        def _c():
            profiles = {pr["p_name"]: pr
                        for pr in param_profile.load_profiles(db.conn, device_code)}
            if p_name:
                targets = [p_name]
            else:
                targets = [k for k, v in profiles.items()
                           if v.get("ptype") in ("continuous", "setpoint")]
            out = []
            for pn in targets:
                r = stats_store.rollup(db.conn, device_code, pn, start_d, end_d,
                                       stage=None, running_only=running_only)
                if not r or not r.get("cnt"):
                    continue
                prof = profiles.get(pn, {})
                bands = prof.get("bands", {}) or {}
                sl, sh = bands.get("spec_low"), bands.get("spec_high")
                cpk = param_profile.compute_cpk(r["mean"], r["std"], sl, sh)
                out.append({"p_name": pn, "display_name": prof.get("display_name", pn),
                            "unit": prof.get("unit", ""), "mean": r["mean"], "std": r["std"],
                            "min": r["min"], "max": r["max"], "spec_low": sl, "spec_high": sh,
                            "spec_source": bands.get("spec_source"), "n_days": r.get("n_days"),
                            **cpk})
            out.sort(key=lambda x: (x["cpk"] is None, x["cpk"] if x["cpk"] is not None else 1e9))
            return {"days": days, "count": len(out), "cpk": out}

        # 仅"全参数 + 默认结束日"时走缓存；指定单参数/历史日现算
        if p_name or end_date:
            data = {**_c(), "cached": False}
        else:
            params = {"days": days, "running_only": running_only}
            data = _cached_or_compute(db, device_code, "cpk", params, refresh, _c)
        return success_response(data={"device_code": device_code, **data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"Cpk 计算失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/auto-thresholds")
def get_auto_thresholds(device_code: str = Query(..., description="设备编号")):
    """已确认画像派生的自动阈值 {中文名:(正常下,正常上,报警下,报警上)}，喂给预测性维护异常检测，替代硬编码。"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        thr = param_profile.get_threshold_config(db.conn, device_code)
        items = [{"param": k, "normal_low": v[0], "normal_high": v[1],
                  "warn_low": v[2], "warn_high": v[3]} for k, v in thr.items()]
        return success_response(data={"device_code": device_code, "count": len(items),
                                      "thresholds": items})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"读取自动阈值失败: {str(e)}", code=500)
    finally:
        db.close()


class RecalcSpecRequest(BaseModel):
    device_code: str
    p_name: str
    cpk_target: float = 1.33


@router.post("/profile/recalc-spec")
def recalc_param_spec(req: RecalcSpecRequest):
    """基于原始数据重算规格上下限（CPK=1.33 算法）。

    拉取该参数最近 14 天原始数据（上限 10 万条）→ 中位数 → ±15% 过滤离群 →
    计算 μ/σ → 按 CPK=1.33 反推 USL/LSL。
    """
    if not req.device_code or not req.p_name:
        return error_response(msg="缺少 device_code 或 p_name", code=400)
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        result = param_profile.recalc_spec_limits(
            db.conn, req.device_code, req.p_name, cpk_target=req.cpk_target)
        if "error" in result:
            return error_response(msg=result["error"], code=400)
        return success_response(data=result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"重算规格限失败: {str(e)}", code=500)
    finally:
        db.close()


class RecalcCpkRequest(BaseModel):
    device_code: str
    p_name: str
    spec_low: float
    spec_high: float


@router.post("/profile/recalc-cpk")
def recalc_param_cpk(req: RecalcCpkRequest):
    """用 device_param_daily_stats + 给定上下限计算 CPK（与 /cpk 端点同源）。"""
    if not req.device_code or not req.p_name:
        return error_response(msg="缺少 device_code 或 p_name", code=400)
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        result = param_profile.calc_cpk_from_raw(
            db.conn, req.device_code, req.p_name,
            spec_low=req.spec_low, spec_high=req.spec_high)
        if "error" in result:
            return error_response(msg=result["error"], code=400)
        return success_response(data=result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"重算 CPK 失败: {str(e)}", code=500)
    finally:
        db.close()



# ═══════════════════════════════════════════════════════
# Pillar 3 高级分析：RUL/触限ETA · 跨设备对标 · 故障前兆自学习
# （懒加载缓存：当天首次现算并写 device_param_insight，之后读缓存秒开；refresh=true 强制现算）
# ═══════════════════════════════════════════════════════

def _cached_or_compute(db, device_code, kind, params, refresh, compute_fn):
    """通用懒加载缓存包装。compute_fn() 返回 payload dict。"""
    if not refresh:
        c = insight_cache.read(db.conn, device_code, kind, params)
        if c is not None:
            return {**(c["payload"] or {}), "cached": True, "computed_at": c["computed_at"]}
    payload = compute_fn()
    insight_cache.write(db.conn, device_code, kind, params, payload)
    return {**payload, "cached": False}


@router.get("/rul")
def get_rul(
    device_code: str = Query(..., description="设备编号"),
    days: int = Query(60, ge=10, le=365, description="拟合回溯天数"),
    running_only: bool = Query(True),
    refresh: bool = Query(False, description="强制现算并刷新缓存"),
):
    """剩余寿命/触限 ETA：按 Sen 斜率把连续参数外推到画像上限/下限，估"还有几天触限"。"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        stats_store.ensure_tables(db.conn)
        params = {"days": days, "running_only": running_only}

        def _c():
            items = advanced_analysis.rul_eta(db.conn, db, device_code, days=days,
                                              running_only=running_only)
            return {"count": len(items), "items": items}

        data = _cached_or_compute(db, device_code, "rul", params, refresh, _c)
        return success_response(data={"device_code": device_code, **data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"RUL 估计失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/benchmark")
def get_benchmark(
    device_code: str = Query(..., description="设备编号"),
    days: int = Query(30, ge=1, le=365),
    running_only: bool = Query(True),
    refresh: bool = Query(False, description="强制现算并刷新缓存"),
):
    """跨设备对标：同名参数跨设备 z-score，找"与同伴不一样"的离群参数/设备。"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        stats_store.ensure_tables(db.conn)
        params = {"days": days, "running_only": running_only}

        def _c():
            items = advanced_analysis.benchmark(db.conn, db, device_code, days=days,
                                                running_only=running_only)
            return {"count": len(items), "items": items}

        data = _cached_or_compute(db, device_code, "benchmark", params, refresh, _c)
        return success_response(data={"device_code": device_code, **data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"对标失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/precursors")
def get_precursors(
    device_code: str = Query(..., description="设备编号"),
    days: int = Query(30, ge=1, le=180),
    pre_min: int = Query(30, ge=5, le=240, description="告警前回看分钟数"),
    running_only: bool = Query(True),
    refresh: bool = Query(False, description="强制现算并刷新缓存"),
):
    """故障前兆自学习：对齐历史告警前窗口，聚合"出事前偏移最大"的参数。"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        stats_store.ensure_tables(db.conn)
        params = {"days": days, "pre_min": pre_min, "running_only": running_only}

        def _c():
            return advanced_analysis.learn_precursors(
                db.conn, db, device_code, days=days, pre_min=pre_min,
                running_only=running_only)

        data = _cached_or_compute(db, device_code, "precursors", params, refresh, _c)
        return success_response(data={"device_code": device_code, **data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"前兆学习失败: {str(e)}", code=500)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════
# Pillar 2：AI 自主诊断 agent（独立 agentic_param，ReAct 编排各分析）
# ═══════════════════════════════════════════════════════

@router.post("/diagnose")
def diagnose_device(
    device_code: str = Query(..., description="设备编号"),
    extra_hint: Optional[str] = Query(None, description="额外关注点(可选)"),
    persist: bool = Query(False, description="是否把结果落 device_diagnosis 缓存"),
):
    """对单台设备跑自主诊断 agent：自主调用画像/趋势/Cpk/RUL/对标/前兆/告警工具，产出诊断。

    同步执行（多轮 LLM，较慢）。改阈值/画像类建议仅作"待人工确认"，不自动生效。
    """
    try:
        from .agentic_param import run_diagnosis
        result = run_diagnosis(device_code, extra_hint=extra_hint or "")
        if persist and result.get("diagnosis"):
            from . import diag_worker
            from datetime import date as _date
            db = TimescaleDB()
            if db.connect():
                try:
                    diag_worker.ensure_diag_table(db.conn)
                    diag_worker._upsert(db.conn, device_code, _date.today(), result)
                finally:
                    db.close()
        return success_response(data=result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"诊断失败: {str(e)}", code=500)


@router.get("/diagnosis")
def get_cached_diagnosis(device_code: str = Query(..., description="设备编号")):
    """读最近一次（定时/手动持久化的）AI 诊断简报缓存，免重跑慢 agent。"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        from . import diag_worker
        data = diag_worker.read_latest(db.conn, device_code)
        return success_response(data=data or {"device_code": device_code, "diagnosis": None})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"读取诊断缓存失败: {str(e)}", code=500)
    finally:
        db.close()


@router.post("/diagnose/run-all")
def run_all_diagnosis(device_code: Optional[str] = Query(None, description="留空=全部设备")):
    """手动触发诊断简报任务（全设备或单设备），落 device_diagnosis（联调/补算用）。"""
    try:
        from . import diag_worker
        result = diag_worker.run_diagnosis_job(device_code=device_code)
        return success_response(data=result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"诊断任务失败: {str(e)}", code=500)


# ═══════════════════════════════════════════════════════
# 分阶段漂移报警 · 知识库诊断
# ═══════════════════════════════════════════════════════

def _find_alert(conn, device_code: str, metric: str, stage: Optional[int],
                eval_date: date, baseline_days: int):
    """从报警快照里定位单条报警（供按需诊断重建完整事实）。"""
    alerts = stats_store.read_trend_alerts(conn, device_code, eval_date=eval_date,
                                           baseline_days=baseline_days)
    sk = -1 if stage is None else int(stage)
    for a in alerts:
        a_sk = -1 if a.get("stage") is None else int(a["stage"])
        if a.get("metric") == metric and a_sk == sk:
            return a
    return None


@router.get("/trend-alerts/diagnosis")
def get_alert_diagnosis(
    device_code: str = Query(..., description="设备编号"),
    metric: str = Query(..., description="参数/合成 metric"),
    eval_date: str = Query(..., description="评估日 YYYY-MM-DD"),
    baseline_days: int = Query(..., description="基线天数(窗口)"),
    stage: Optional[int] = Query(None, description="阶段码，整天报警留空"),
):
    """读某条报警已存的知识库诊断（无则 data=null，前端提示去生成）。"""
    try:
        ed = datetime.strptime(eval_date, "%Y-%m-%d").date()
    except ValueError:
        return error_response(msg="评估日格式错误，应为 YYYY-MM-DD", code=400)
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        from . import alert_diagnosis
        data = alert_diagnosis.read_for_alert(db.conn, device_code, metric, stage,
                                              ed, baseline_days)
        return success_response(data=data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"读取报警诊断失败: {str(e)}", code=500)
    finally:
        db.close()


@router.post("/trend-alerts/diagnose")
def diagnose_alert_endpoint(
    device_code: str = Query(..., description="设备编号"),
    metric: str = Query(..., description="参数/合成 metric"),
    eval_date: str = Query(..., description="评估日 YYYY-MM-DD"),
    baseline_days: int = Query(..., description="基线天数(窗口)"),
    stage: Optional[int] = Query(None, description="阶段码，整天报警留空"),
):
    """按需对单条报警结合知识库生成诊断并保存（页面"立即诊断/重新诊断"，较慢）。"""
    try:
        ed = datetime.strptime(eval_date, "%Y-%m-%d").date()
    except ValueError:
        return error_response(msg="评估日格式错误，应为 YYYY-MM-DD", code=400)
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        from . import alert_diagnosis
        alert = _find_alert(db.conn, device_code, metric, stage, ed, baseline_days)
        if not alert:
            return error_response(msg="未找到对应报警快照，请先运行参数趋势汇总", code=404)
        data = alert_diagnosis.diagnose_alert(db, alert)
        return success_response(data=data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"报警诊断失败: {str(e)}", code=500)
    finally:
        db.close()


@router.post("/trend-alerts/diagnose/run-all")
def run_all_alert_diagnosis(
    device_code: Optional[str] = Query(None, description="留空=全部设备"),
    baseline_days: Optional[int] = Query(None, description="仅诊断某窗口(如7)，留空=全部"),
    max_per_device: int = Query(0, description="每设备最多诊断条数，0=不限"),
):
    """手动触发分阶段报警知识库诊断任务（全设备或单设备），落 device_param_alert_diagnosis。"""
    try:
        from . import alert_diag_worker
        result = alert_diag_worker.run_alert_diag_job(device_code=device_code,
                                                      baseline_days=baseline_days,
                                                      max_per_device=max_per_device)
        return success_response(data=result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"报警诊断任务失败: {str(e)}", code=500)


# ═══════════════════════════════════════════════════════
# 异常检测 + 健康指数
# ═══════════════════════════════════════════════════════

class AnomalyDetectRequest(BaseModel):
    device_code: str
    start_time: str
    end_time: str
    contamination: float = 0.05


@router.post("/anomaly/detect")
def detect_anomalies(request: AnomalyDetectRequest):
    """
    无监督异常检测 + 设备健康指数

    方法:
    - IQR 动态阈值（单参数统计过程控制）
    - 孤立森林（多参数联合异常检测）
    - 复合告警规则

    返回:
    - health_timeline: 每个时间点的健康指数(0-100)和异常分数
    - iqr_thresholds: 各参数的 IQR 动态阈值
    - summary: 异常时段汇总
    """
    try:
        st = datetime.strptime(request.start_time, "%Y-%m-%d %H:%M:%S")
        et = datetime.strptime(request.end_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return error_response(msg="时间格式错误", code=400)

    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        device_id = db.get_device_id_by_code(request.device_code)
        if device_id is None:
            return error_response(msg=f"未找到设备: {request.device_code}", code=404)

        # 1. 获取原始参数数据（不聚合）
        rows = db.get_param_data(
            device_code=request.device_code,
            start_time=st, end_time=et, limit=30000,
        )
        if not rows:
            return error_response(msg="该时间段内无参数数据", code=404)

        # 2. 组织数据: {p_name: [(ts, value), ...]}
        param_series: dict = defaultdict(lambda: defaultdict(float))
        all_timestamps: set = set()
        for row in rows:
            ts = row["gather_time"]
            if isinstance(ts, datetime):
                ts_key = ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts_key = str(ts)
            try:
                val = float(row["p_value"])
            except (ValueError, TypeError):
                continue
            param_series[row["p_name"]][ts_key] = val
            all_timestamps.add(ts_key)

        if not param_series:
            return error_response(msg="无有效数值型参数数据", code=404)

        sorted_times = sorted(all_timestamps)

        # 3. 构建特征（滑动窗口统计）
        # 以参数时间线构建 DataFrame
        params_df = pd.DataFrame(index=sorted_times)
        for pname, ts_vals in param_series.items():
            series = pd.Series(ts_vals, name=pname)
            series.index = pd.to_datetime(series.index)
            params_df[pname] = series

        params_df.index = pd.to_datetime(params_df.index)
        params_df = params_df.sort_index()

        # 按 5 分钟重采样
        resampled = params_df.resample("5min").mean().interpolate(limit=3)

        # 滑动窗口特征
        features = pd.DataFrame(index=resampled.index)
        for pname in resampled.columns:
            col = resampled[pname]
            for win in ["5min", "15min", "30min", "60min"]:
                rolled = col.rolling(win, min_periods=1)
                features[f"{pname}__{win}_mean"] = rolled.mean()
                features[f"{pname}__{win}_std"] = rolled.std()
                features[f"{pname}__{win}_max"] = rolled.max()
                features[f"{pname}__{win}_min"] = rolled.min()

        # 4. 区分运行/停机：取 status=1 (运行) 时段数据训练
        alarm_events = db.get_alarm_events(device_id, st, et)

        # 找出运行时段
        running_mask = pd.Series(False, index=resampled.index)
        if alarm_events:
            for ev in alarm_events:
                if ev["status"] == 1:  # 运行
                    s = ev["start_time"]
                    e = ev.get("end_time")
                    if isinstance(s, str):
                        s = pd.Timestamp(s)
                    if e and isinstance(e, str):
                        e = pd.Timestamp(e)
                    elif e is None:
                        e = resampled.index[-1]
                    if s and e:
                        running_mask[(resampled.index >= s) & (resampled.index <= e)] = True

        # 取运行时段数据训练
        train_features = features[running_mask].dropna(axis=1, how="all")
        train_features = train_features.fillna(train_features.mean()).replace([np.inf, -np.inf], 0)

        # 训练参数（仅用运行时段）
        train_params = {}
        for pname, ts_vals in param_series.items():
            vals = []
            for ts_key in sorted_times:
                ts_dt = pd.Timestamp(ts_key)
                if running_mask[resampled.index[
                    resampled.index.get_indexer([ts_dt], method="nearest")[0]
                ]]:
                    v = ts_vals.get(ts_key)
                    if v is not None and not np.isnan(v):
                        vals.append(v)
            if vals:
                train_params[pname] = vals

        # 5. 训练检测器
        detector = AnomalyDetector(contamination=request.contamination)
        detector.fit(train_params if train_params else
                    {p: list(ts_vals.values()) for p, ts_vals in param_series.items()},
                    train_features if len(train_features) > 50 else features)

        # 6. 对全时间线逐点检测
        # 构建 Series 格式
        param_series_fmt = {}
        for pname, ts_vals in param_series.items():
            s = pd.Series(ts_vals)
            s.index = pd.to_datetime(s.index)
            param_series_fmt[pname] = s

        # 解析告警事件时间
        for ev in (alarm_events or []):
            for key in ("start_time", "end_time"):
                if isinstance(ev.get(key), str):
                    try:
                        ev[f"{key}_dt" if "_dt" not in key else key] = pd.Timestamp(ev[key])
                    except ValueError:
                        pass
                elif isinstance(ev.get(key), datetime):
                    ev[f"{key}_dt" if "_dt" not in key else key] = ev[key]

        timeline_df = detector.detect_timeline(
            param_series_fmt, features, alarm_events)

        if timeline_df.empty:
            return error_response(msg="检测失败，无有效数据点", code=500)

        # 7. 构建响应
        health_timeline = []
        for idx, row in timeline_df.iterrows():
            health_timeline.append({
                "timestamp": str(idx),
                "health_index": float(row["health_index"]),
                "if_score": float(row["if_anomaly_score"]),
                "iqr_score": float(row["iqr_score"]),
                "alarm_penalty": float(row["alarm_penalty"]),
                "severity": row["severity"],
                "is_anomaly": bool(row["is_anomaly"]),
                "contributing_params": row.get("contributing_params", []),
            })

        # 异常时段汇总
        anomaly_periods = []
        in_anomaly = False
        period_start = None
        for point in health_timeline:
            if point["is_anomaly"] and not in_anomaly:
                in_anomaly = True
                period_start = point["timestamp"]
            elif not point["is_anomaly"] and in_anomaly:
                in_anomaly = False
                anomaly_periods.append({
                    "start": period_start,
                    "end": point["timestamp"],
                })

        avg_health = float(timeline_df["health_index"].mean())
        min_health = float(timeline_df["health_index"].min())
        anomaly_ratio = float(timeline_df["is_anomaly"].mean())

        return success_response(data={
            "device_code": request.device_code,
            "start_time": st.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": et.strftime("%Y-%m-%d %H:%M:%S"),
            "total_points": len(health_timeline),
            "summary": {
                "avg_health": round(avg_health, 1),
                "min_health": round(min_health, 1),
                "anomaly_ratio": round(anomaly_ratio, 4),
                "anomaly_periods": anomaly_periods,
            },
            "health_timeline": health_timeline,
            "iqr_thresholds": detector.get_thresholds(),
            "model": {
                "if_trained": detector._if_model is not None,
                "iqr_params": len(detector._iqr_thresholds),
                "contamination": request.contamination,
            },
        })

    except Exception as e:
        return error_response(msg=f"异常检测失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/anomaly/thresholds")
def get_anomaly_thresholds(
    device_code: str = Query(..., description="设备编号"),
    hours: int = Query(24, ge=1, le=168, description="训练数据时长"),
):
    """获取设备的 IQR 动态阈值（用于了解基线）"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        et = datetime.now()
        st = et - timedelta(hours=hours)

        rows = db.get_param_data(
            device_code=device_code,
            start_time=st, end_time=et, limit=10000,
        )

        if not rows:
            return error_response(msg="无数据", code=404)

        # 组织数据
        param_vals: dict = defaultdict(list)
        for row in rows:
            try:
                val = float(row["p_value"])
                param_vals[row["p_name"]].append(val)
            except (ValueError, TypeError):
                continue

        # 计算 IQR 阈值
        name_map = db.get_point_names(device_code)
        unit_map = db.get_point_units(device_code)
        thresholds = []
        for pname, vals in sorted(param_vals.items()):
            arr = np.array(vals)
            q1 = float(np.percentile(arr, 25))
            q3 = float(np.percentile(arr, 75))
            iqr = q3 - q1
            thresholds.append({
                "p_name": pname,
                "display_name": name_map.get(pname, pname),
                "unit": unit_map.get(pname, ""),
                "median": float(np.median(arr)),
                "q1": q1, "q3": q3, "iqr": iqr,
                "lower": q1 - 1.5 * iqr,
                "upper": q3 + 1.5 * iqr,
                "sample_count": len(vals),
            })

        return success_response(data={
            "device_code": device_code,
            "hours": hours,
            "thresholds": thresholds,
        })

    except Exception as e:
        return error_response(msg=f"获取阈值失败: {str(e)}", code=500)
    finally:
        db.close()


def _parse_time(ts: str) -> Optional[datetime]:
    """鲁棒时间解析：处理 URL 中的 + (空格编码) 和多种格式"""
    if not ts:
        return None
    # 处理 URL 编码的空格
    ts = ts.replace('+', ' ').replace('%20', ' ')
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"]:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


def _classify_features(df: pd.DataFrame) -> dict:
    """将 DataFrame 的列按特征类别分组"""
    cats = {"raw": [], "rolling": [], "diff": [], "interact": [], "alarm": []}
    for c in df.columns:
        if c.startswith("iact__"):
            cats["interact"].append(c)
        elif "__diff_per_min" in c:
            cats["diff"].append(c)
        elif any(f"__{w}_{s}" in c for w in ["5min", "15min", "30min", "60min"]
                for s in ["mean", "std", "max", "min"]):
            cats["rolling"].append(c)
        elif any(c.startswith(p) for p in
                ("alarm_cnt", "stop_cnt", "current_status", "min_since")):
            cats["alarm"].append(c)
        else:
            cats["raw"].append(c)
    return cats


def _df_to_timeline(df: pd.DataFrame, selected: list) -> list:
    """DataFrame 转 timeline 列表"""
    timeline = []
    for idx, row in df.iterrows():
        point = {"timestamp": str(idx)}
        for c in selected:
            val = row[c]
            if pd.isna(val) or (isinstance(val, float) and np.isinf(val)):
                point[c] = None
            else:
                point[c] = round(float(val), 4)
        timeline.append(point)
    return timeline


def _build_features_on_the_fly(
    device_code: str, st: datetime, et: datetime
) -> pd.DataFrame:
    """
    从数据库实时提取特征

    按天批量查询原始参数 → Pivot → 滑动窗口 → 交互特征 → 告警特征
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))
    from extract_device_features import (
        fetch_one_day, pivot_to_wide, add_rolling_features,
        add_interaction_features, add_alarm_features,
        fetch_status_for_range, get_device_list,
        build_running_intervals, filter_to_running, RUNNING_CODES,
    )

    devices = get_device_list()
    dev = next((d for d in devices if d["device_code"] == device_code), None)
    if not dev:
        return pd.DataFrame()

    db = TimescaleDB()
    if not db.connect():
        return pd.DataFrame()

    try:
        conn = db.conn

        # 运行状态过滤：仅保留运行(code 1)时段的参数行算特征，与离线脚本
        # extract_device_features.py 完全一致。须在 pivot 宽表后、滑窗特征前过滤。
        # 该设备此范围内无 code-1 事件时 build_running_intervals 返回 None，
        # filter_to_running 原样保留（回退保留全部，行为同离线脚本）。
        status_df = fetch_status_for_range(dev["numeric_id"], st, et)
        run_intervals = build_running_intervals(status_df, RUNNING_CODES, et)

        # 按天抽取
        daily_parts = []
        cur_date = st.date()
        end_date = et.date()
        while cur_date <= end_date:
            raw = fetch_one_day(conn, device_code, cur_date)
            if not raw.empty:
                wide = pivot_to_wide(raw)
                if not wide.empty:
                    wide = filter_to_running(wide, run_intervals)
                    if not wide.empty:
                        feats = add_rolling_features(wide)
                        daily_parts.append(feats)
            cur_date += timedelta(days=1)

        if not daily_parts:
            return pd.DataFrame()

        features = pd.concat(daily_parts, axis=0).sort_index()

        # 告警特征（复用上面已取的 status_df）
        features = add_interaction_features(features)
        features = add_alarm_features(features, status_df)

        features = features.dropna(axis=1, how="all")
        features = features.replace([np.inf, -np.inf], np.nan)
        return features
    finally:
        db.close()


@router.get("/features")
def get_device_features(
    device_code: str = Query(..., description="设备编码"),
    category: Optional[str] = Query(None, description="特征类别: raw/rolling/diff/interact/alarm/all"),
    start_time: Optional[str] = Query(None, description="开始时间 (YYYY-MM-DD HH:MM:SS)"),
    end_time: Optional[str] = Query(None, description="结束时间 (YYYY-MM-DD HH:MM:SS)"),
    limit: int = Query(500, ge=50, le=5000, description="最大返回行数"),
):
    """
    获取设备特征数据

    优先从 features_output/*.parquet 读取（快），
    若文件不存在或时间范围不匹配，则从数据库实时计算（≤7天），
    超过7天建议先运行预生成。

    特征类别:
    - raw: 原始参数
    - rolling: 滑动窗口统计
    - diff: 变化率
    - interact: 多参数交互
    - alarm: 告警/状态
    """
    from pathlib import Path

    # 解析时间范围
    st = _parse_time(start_time) if start_time else None
    et = _parse_time(end_time) if end_time else None
    if start_time and st is None:
        return error_response(msg="开始时间格式错误", code=400)
    if end_time and et is None:
        return error_response(msg="结束时间格式错误", code=400)
    # 如果只给了日期，补齐到当天结束
    if et and end_time and ' ' not in end_time.replace('+','').replace('%20','') and 'T' not in end_time:
        et = et + timedelta(days=1, seconds=-1)

    # 策略：≤7 天实时从DB计算（保证时间对齐），>7 天读 parquet
    days_needed = (et - st).days + 1 if (st and et) else 0

    df = None
    source = "realtime"
    time_note = None
    p_start = p_end = None

    if st and et and days_needed <= 7:
        df = _build_features_on_the_fly(device_code, st, et)
        if df is not None and not df.empty:
            source = "realtime"
            p_start, p_end = df.index.min(), df.index.max()
        else:
            df = None

    # >7天或实时计算失败 → 回退 parquet
    if df is None or df.empty:
        parquet_path = Path(__file__).parent.parent.parent.parent / \
            "features_output" / f"features_{device_code}.parquet"
        if parquet_path.exists():
            try:
                df = pd.read_parquet(parquet_path)
                source = "parquet"
                p_start, p_end = df.index.min(), df.index.max()
                if st and et:
                    if et < p_start or st > p_end:
                        time_note = f"预生成特征 ({str(p_start)[:19]} ~ {str(p_end)[:19]})，与请求范围不重叠"
                    else:
                        df = df[(df.index >= max(st, p_start)) & (df.index <= min(et, p_end))]
            except Exception as e:
                import traceback
                traceback.print_exc()
                return error_response(msg=f"特征数据获取失败: {str(e)}", code=500)
        else:
            return error_response(
                msg=f"实时计算失败且特征文件不存在。请缩短时间范围(≤7天)或运行预生成。",
                code=500)

    if df is None or df.empty:
        return error_response(msg="未能获取特征数据", code=500)

    # 4. 分类 + 筛选
    categories = _classify_features(df)
    if category and category != "all":
        selected = categories.get(category, [])
    else:
        selected = list(df.columns)

    if not selected:
        return error_response(msg=f"类别 '{category}' 无特征列", code=400)

    sub = df[selected].tail(limit)

    # 5. 构建元信息
    meta = {}
    for cat_name, cols in categories.items():
        meta[cat_name] = {"count": len(cols), "columns": cols[:10], "total": len(cols)}

    return success_response(data={
        "device_code": device_code,
        "source": source,
        "file": str(parquet_path) if source == "parquet" else None,
        "data_range": {"start": str(p_start)[:19], "end": str(p_end)[:19]},
        "time_note": time_note,
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "returned_rows": len(sub),
        "returned_columns": len(selected),
        "category": category or "all",
        "categories": meta,
        "timeline": _df_to_timeline(sub, selected),
    })


@router.post("/analyze")
async def analyze_params(request: ParamAnalysisRequest):
    """对设备参数数据进行 AI 分析"""
    st: Optional[datetime] = None
    et: Optional[datetime] = None

    if request.start_time:
        try:
            st = datetime.strptime(request.start_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return error_response(msg="开始时间格式错误", code=400)
    if request.end_time:
        try:
            et = datetime.strptime(request.end_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return error_response(msg="结束时间格式错误", code=400)

    if not st and not et:
        et = datetime.now()
        st = et - timedelta(hours=request.hours)

    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)

    try:
        device_id = db.get_device_id_by_code(request.device_code)
        if device_id is None:
            return success_response(data={
                "analysis": "未找到该设备的信息，无法进行分析。",
                "running_periods": [],
                "compressed_data": None,
            })

        status_code = db.get_running_status_code()
        running_periods = []
        if status_code:
            running_periods = db.get_running_periods(device_id, status_code, st, et)

        # 根据参数决定是否过滤运行时段
        if request.analyze_running_only:
            if not running_periods:
                return success_response(data={
                    "analysis": "该设备在指定时间范围内没有运行时段数据，无法进行分析。",
                    "running_periods": [],
                    "compressed_data": None,
                })
            # 只使用运行时段的数据
            compressed = db.get_compressed_param_data(
                device_code=request.device_code,
                p_name=request.p_name,
                start_time=st,
                end_time=et,
                max_hours=72,
                max_points_per_series=288,
                running_periods=running_periods,
            )
        else:
            # 使用所有数据（不过滤运行时段）
            compressed = db.get_compressed_param_data(
                device_code=request.device_code,
                p_name=request.p_name,
                start_time=st,
                end_time=et,
                max_hours=72,
                max_points_per_series=288,
                running_periods=None,
            )

        analysis = await analyze_device_params(
            device_code=request.device_code,
            device_name=request.device_name or request.device_code,
            time_range={"start_time": st.strftime("%Y-%m-%d %H:%M:%S"), "end_time": et.strftime("%Y-%m-%d %H:%M:%S")},
            running_periods=running_periods,
            compressed_data=compressed,
            analyze_running_only=request.analyze_running_only,
        )

        try:
            analysis_log.save(db.conn, request.device_code,
                              request.device_name or request.device_code,
                              st, et, bool(request.analyze_running_only), analysis)
        except Exception as e:
            db.conn.rollback()
            print(f"[AI分析] 留痕写入失败(不影响本次返回): {e}")

        return success_response(data={
            "analysis": analysis,
            "running_periods": running_periods,
            "compressed_data": compressed,
        })
    except Exception as e:
        return error_response(msg=f"分析失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/analysis-log")
def get_analysis_log(
    device_code: str = Query(..., description="设备编号"),
    limit: int = Query(20, ge=1, le=100, description="返回条数上限"),
):
    """读取"AI 分析"按钮的历史记录（供页面查看之前的分析结果）。"""
    db = TimescaleDB()
    if not db.connect():
        return error_response(msg="TimescaleDB 数据库连接失败", code=500)
    try:
        items = analysis_log.list_recent(db.conn, device_code, limit=limit)
        return success_response(data={"device_code": device_code,
                                      "count": len(items), "items": items})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"读取分析历史失败: {str(e)}", code=500)
    finally:
        db.close()
