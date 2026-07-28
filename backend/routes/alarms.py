# cython: annotation_typing=False, infer_types=False, language_level=3
"""
报警记录 API 路由
"""

import json
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from core.response import success_response, error_response
from modules.device_warning.ai_analysis.postgres_loader import PostgresDB
from modules.device_warning.ai_analysis.point_config import ALARM_POINT_NAMES, PROCESS_POINT_DISPLAY_NAMES

router = APIRouter(prefix="/api/alarms", tags=["alarms"])


def get_alarm_display_name(device_id: str, point_id: str) -> str:
    """获取报警/工艺参数的中文显示名称"""
    # 先查报警名称
    if device_id in ALARM_POINT_NAMES:
        name = ALARM_POINT_NAMES[device_id].get(point_id)
        if name:
            return name
    # 再查工艺参数显示名
    if device_id in PROCESS_POINT_DISPLAY_NAMES:
        name = PROCESS_POINT_DISPLAY_NAMES[device_id].get(point_id)
        if name:
            return name
    return point_id


@router.get("")
def list_alarms(
    device_id: Optional[str] = Query(None, description="设备ID"),
    keyword: Optional[str] = Query(None, description="搜索关键词（报警名称）"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    only_active: bool = Query(False, description="只显示活跃报警"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页数量")
):
    """
    分页查询报警记录

    支持多种过滤条件：
    - device_id: 按设备筛选
    - keyword: 按报警名称搜索
    - start_date/end_date: 时间范围
    - only_active: 只显示触发的报警
    """
    db = PostgresDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        start_time = None
        end_time = None

        if start_date:
            start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
        if end_date:
            end_time = datetime.combine(end_date, datetime.max.time()).isoformat()

        result = db.get_alarm_records(
            device_id=device_id,
            alarm_name=keyword,
            start_time=start_time,
            end_time=end_time,
            only_active=only_active,
            page=page,
            page_size=page_size
        )

        # 添加中文报警名称
        for item in result.get("items", []):
            item["alarm_name"] = get_alarm_display_name(
                item.get("device_id", ""),
                item.get("point_id", "")
            )
            # 报警状态描述
            item["status"] = "触发" if item.get("point_value") == 1 else "恢复"

        return success_response(data=result)
    except Exception as e:
        return error_response(msg=f"查询失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/statistics")
def alarm_statistics(
    device_id: Optional[str] = Query(None, description="设备ID"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期")
):
    """
    获取报警统计信息

    返回：
    - 总报警数、活跃报警数
    - 按设备统计 Top 10
    - 按类型统计 Top 10
    - 小时趋势分布
    """
    db = PostgresDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        start_time = None
        end_time = None

        if start_date:
            start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
        if end_date:
            end_time = datetime.combine(end_date, datetime.max.time()).isoformat()

        result = db.get_alarm_statistics(
            device_id=device_id,
            start_time=start_time,
            end_time=end_time
        )

        # 添加中文报警/工艺参数名称
        for item in result.get("by_type", []):
            point_id = item.get("point_id", "")
            alarm_name = point_id
            # 先查报警名称，再查工艺参数名称
            for dev_id, names in ALARM_POINT_NAMES.items():
                if point_id in names:
                    alarm_name = names[point_id]
                    break
            else:
                for dev_id, names in PROCESS_POINT_DISPLAY_NAMES.items():
                    if point_id in names:
                        alarm_name = names[point_id]
                        break
            item["alarm_name"] = alarm_name

        return success_response(data=result)
    except Exception as e:
        return error_response(msg=f"查询失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/devices")
def list_alarm_devices():
    """
    获取有报警记录的设备列表

    返回每个设备的报警总数、活跃报警数、最后报警时间
    """
    db = PostgresDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        devices = db.get_device_list_with_alarms()
        return success_response(data=devices)
    except Exception as e:
        return error_response(msg=f"查询失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/types")
def list_alarm_types(
    device_id: Optional[str] = Query(None, description="设备ID")
):
    """
    获取报警类型列表

    返回指定设备（或所有设备）的报警类型定义
    """
    result = []

    if device_id and device_id in ALARM_POINT_NAMES:
        # 返回指定设备的报警类型
        for point_id, name in ALARM_POINT_NAMES[device_id].items():
            result.append({
                "device_id": device_id,
                "point_id": point_id,
                "alarm_name": name
            })
    else:
        # 返回所有设备的报警类型
        for dev_id, alarms in ALARM_POINT_NAMES.items():
            for point_id, name in alarms.items():
                result.append({
                    "device_id": dev_id,
                    "point_id": point_id,
                    "alarm_name": name
                })

    return success_response(data=result)


# ==================== 报警分析 API ====================

class AlarmAnalysisRequest(BaseModel):
    device_id: str | None = Field(default=None, description="设备ID（留空使用默认）")
    start_date: str | None = Field(default=None, description="开始日期 (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="结束日期 (YYYY-MM-DD)")
    report_type: str = Field(default="daily", description="报告类型: daily/weekly/monthly")


@router.post("/analysis")
def alarm_analysis(data: AlarmAnalysisRequest):
    """
    执行报警分析

    合并 SQL 统计 + AI 异常检测结果，支持时间段选择。
    结果存入对应类型的表（daily/weekly/monthly），同日期重复执行覆盖。
    """
    from modules.device_warning.ai_analysis.main import FactoryAIAnalyzer

    if data.report_type not in ('daily', 'weekly', 'monthly'):
        return error_response(msg="report_type 必须是 daily/weekly/monthly", code=400)

    # 1. 计算时间范围
    device_id = data.device_id
    start_time = None
    end_time = None
    hours = 24

    if data.start_date:
        try:
            sd = datetime.strptime(data.start_date, "%Y-%m-%d")
            start_time = sd.isoformat()
        except ValueError:
            return error_response(msg="开始日期格式错误，请使用 YYYY-MM-DD", code=400)

    if data.end_date:
        try:
            ed = datetime.strptime(data.end_date, "%Y-%m-%d")
            end_time = datetime.combine(ed.date(), datetime.max.time()).isoformat()
        except ValueError:
            return error_response(msg="结束日期格式错误，请使用 YYYY-MM-DD", code=400)

    if start_time and end_time:
        delta = datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)
        hours = max(1, int(delta.total_seconds() / 3600))
    elif start_time:
        hours = 24

    # 2. 获取 SQL 统计
    db = PostgresDB()
    if not db.connect_with_fallback():
        return error_response(msg="数据库连接失败", code=500)

    try:
        stats = db.get_alarm_statistics(
            device_id=device_id,
            start_time=start_time,
            end_time=end_time
        )

        for item in stats.get("by_type", []):
            point_id = item.get("point_id", "")
            alarm_name = point_id
            for dev_id, names in ALARM_POINT_NAMES.items():
                if point_id in names:
                    alarm_name = names[point_id]
                    break
            else:
                for dev_id, names in PROCESS_POINT_DISPLAY_NAMES.items():
                    if point_id in names:
                        alarm_name = names[point_id]
                        break
            item["alarm_name"] = alarm_name
    finally:
        db.close()

    # 3. 执行 AI 异常检测
    try:
        analyzer = FactoryAIAnalyzer()

        if start_time:
            analyzer.alarm_definitions = analyzer.loader.load_alarm_definitions()
            analyzer.history_data = analyzer.loader.load_history_data(
                device_id=device_id,
                start_time=start_time,
                use_logic_names=True
            )
        else:
            analyzer.alarm_definitions = analyzer.loader.load_alarm_definitions()
            analyzer.history_data = analyzer.loader.load_history_data(
                device_id=device_id,
                hours=hours,
                use_logic_names=True
            )

        anomaly_result = analyzer.run_anomaly_detection()
        serialized = json.loads(json.dumps(anomaly_result, default=str))
    except Exception as e:
        print(f"[报警分析] AI 分析失败: {e}")
        serialized = {"error": str(e), "total_anomalies": 0}

    # 4. 存入数据库（覆盖同日期同设备）
    report_date = data.start_date or datetime.now().strftime("%Y-%m-%d")
    query_params = {
        "device_id": device_id,
        "start_date": data.start_date,
        "end_date": data.end_date,
        "hours": hours
    }

    db2 = PostgresDB()
    if db2.connect_with_fallback():
        try:
            db2.create_alarm_analysis_tables()
            record_id = db2.save_alarm_analysis(
                report_type=data.report_type,
                report_date=report_date,
                device_id=device_id,
                statistics=stats,
                analysis=serialized,
                query_params=query_params
            )
            print(f"[报警分析] 已保存到 {data.report_type} 表, id={record_id}")
        finally:
            db2.close()

    # 5. 返回结果
    return success_response(data={
        "statistics": stats,
        "analysis": serialized,
        "query": query_params,
        "report_type": data.report_type,
        "report_date": report_date,
        "saved": True
    }, msg="报警分析完成")


@router.get("/analysis/history")
def alarm_analysis_history(
    report_type: str = Query("daily", description="报告类型: daily/weekly/monthly"),
    limit: int = Query(50, ge=1, le=200, description="返回条数")
):
    """查询报警分析历史报告"""
    db = PostgresDB()
    if not db.connect_with_fallback():
        return error_response(msg="数据库连接失败", code=500)

    try:
        db.create_alarm_analysis_tables()
        records = db.list_alarm_analyses(report_type=report_type, limit=limit)
        return success_response(data=records)
    finally:
        db.close()


@router.get("/analysis/detail")
def alarm_analysis_detail(
    report_type: str = Query("daily", description="报告类型: daily/weekly/monthly"),
    report_date: str = Query(..., description="报告日期 (YYYY-MM-DD)"),
    device_id: str | None = Query(None, description="设备ID")
):
    """获取指定日期的报警分析详情"""
    db = PostgresDB()
    if not db.connect_with_fallback():
        return error_response(msg="数据库连接失败", code=500)

    try:
        db.create_alarm_analysis_tables()
        record = db.get_alarm_analysis(
            report_type=report_type,
            report_date=report_date,
            device_id=device_id
        )
        if not record:
            return error_response(msg="未找到该日期的分析报告", code=404)
        return success_response(data=record)
    finally:
        db.close()
