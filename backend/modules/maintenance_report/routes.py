# cython: annotation_typing=False, infer_types=False, language_level=3
"""
预测性维护报告 API 路由
"""

import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.response import success_response, error_response
from modules.device_warning.ai_analysis.postgres_loader import PostgresDB

from .models.schemas import (
    GenerateReportRequest,
    BatchGenerateRequest,
    TriggerScheduledRequest
)
from .services.report_generator import MaintenanceReportGenerator
from .services.scheduler import get_scheduler
from .services.data_aggregator import DataAggregator
from .services.fault_predictor import (
    FaultPredictor, get_predictor, build_fault_explanation_prompt
)

router = APIRouter(prefix="/api/maintenance-reports", tags=["maintenance-reports"])


# ==================== 报告生成 API ====================

@router.post("/generate")
async def generate_report(request: GenerateReportRequest):
    """
    生成单台设备的预测性维护报告

    - **device_id**: 设备 ID
    - **report_type**: 报告类型 (daily/weekly/monthly)
    - **report_date**: 报告日期 (默认今天)
    """
    generator = MaintenanceReportGenerator()

    report_date = datetime.combine(
        request.report_date or date.today(),
        datetime.min.time()
    )

    try:
        result = await generator.generate_device_report(
            device_id=request.device_id,
            report_type=request.report_type,
            report_date=report_date
        )
        return success_response(data=result, msg="报告生成成功")
    except Exception as e:
        return error_response(msg=f"报告生成失败: {str(e)}", code=500)


@router.post("/generate/stream")
async def generate_report_stream(request: GenerateReportRequest):
    """
    流式生成单台设备的预测性维护报告 (SSE)

    返回 Server-Sent Events 格式的流式数据
    """
    generator = MaintenanceReportGenerator()

    report_date = datetime.combine(
        request.report_date or date.today(),
        datetime.min.time()
    )

    return StreamingResponse(
        generator.generate_device_report_stream(
            device_id=request.device_id,
            report_type=request.report_type,
            report_date=report_date
        ),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@router.post("/generate/batch")
async def generate_batch_reports(
    request: BatchGenerateRequest,
    background_tasks: BackgroundTasks
):
    """
    批量生成报告 (后台任务)

    可指定设备列表或车间，不指定则生成所有设备报告
    """
    generator = MaintenanceReportGenerator()

    report_date = datetime.combine(
        request.report_date or date.today(),
        datetime.min.time()
    )

    # 后台执行
    background_tasks.add_task(
        generator.generate_batch_reports,
        report_type=request.report_type,
        report_date=report_date,
        device_ids=request.device_ids,
        workshop_id=request.workshop_id
    )

    return success_response(
        msg="批量报告生成任务已提交",
        data={
            "status": "submitted",
            "report_type": request.report_type,
            "report_date": str(request.report_date or date.today())
        }
    )


# ==================== 报告查询 API ====================

@router.get("/list")
async def list_reports(
    report_type: Optional[str] = Query(None, description="报告类型 (daily/weekly/monthly)"),
    device_id: Optional[str] = Query(None, description="设备ID"),
    workshop_id: Optional[str] = Query(None, description="车间ID"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    health_score_max: Optional[float] = Query(None, description="健康分上限（筛选问题设备）"),
    risk_level: Optional[str] = Query(None, description="风险等级"),
    limit: int = Query(100, le=500, description="返回数量限制"),
    offset: int = Query(0, description="偏移量")
):
    """
    查询报告列表

    支持多种过滤条件：
    - report_type: 报告类型
    - device_id: 设备ID
    - start_date/end_date: 日期范围
    - health_score_max: 健康分上限（用于筛选问题设备）
    - risk_level: 风险等级
    """
    db = PostgresDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        reports = db.get_device_reports(
            report_type=report_type,
            device_id=device_id,
            start_date=start_date.isoformat() if start_date else None,
            end_date=end_date.isoformat() if end_date else None,
            limit=limit + offset
        )

        # 应用额外过滤
        if not reports.empty:
            if workshop_id and 'workshop_id' in reports.columns:
                reports = reports[reports['workshop_id'] == workshop_id]
            if health_score_max and 'health_score' in reports.columns:
                reports = reports[reports['health_score'] <= health_score_max]
            if risk_level and 'risk_level' in reports.columns:
                reports = reports[reports['risk_level'] == risk_level]

        # 应用偏移和限制
        reports = reports.iloc[offset:offset + limit]

        # 转换为字典列表，处理 NaN 值
        result = []
        for _, row in reports.iterrows():
            item = {}
            for col in reports.columns:
                val = row[col]
                # 处理 NaN 和 NaT
                if hasattr(val, 'isoformat'):
                    item[col] = val.isoformat()
                elif val != val:  # NaN check
                    item[col] = None
                else:
                    item[col] = val
            result.append(item)

        return success_response(data={
            "total": len(result),
            "items": result
        })
    except Exception as e:
        return error_response(msg=f"查询失败: {str(e)}", code=500)
    finally:
        db.close()


@router.get("/detail/{report_id}")
async def get_report_detail(report_id: int):
    """获取报告详情"""
    db = PostgresDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        result = db.get_device_report_by_id(report_id)

        if not result:
            return error_response(msg="报告不存在", code=404)

        # 处理日期时间序列化
        for key, val in result.items():
            if hasattr(val, 'isoformat'):
                result[key] = val.isoformat()
            elif val != val:  # NaN check
                result[key] = None

        return success_response(data=result)
    except Exception as e:
        return error_response(msg=f"查询失败: {str(e)}", code=500)
    finally:
        db.close()


@router.delete("/delete/{report_id}")
async def delete_report(report_id: int):
    """删除报告"""
    db = PostgresDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        success = db.delete_device_report(report_id)
        if success:
            return success_response(msg="报告已删除")
        else:
            return error_response(msg="删除失败", code=500)
    finally:
        db.close()


@router.get("/summary/{report_type}/{report_date}")
async def get_report_summary(
    report_type: str,
    report_date: date
):
    """获取指定日期的报告汇总统计"""
    db = PostgresDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        summary = db.get_report_summary(report_type, report_date.isoformat())
        return success_response(data=summary)
    finally:
        db.close()


# ==================== 车间汇总 API ====================

@router.get("/workshop-summary")
async def get_workshop_summaries(
    report_type: str = Query(..., description="报告类型"),
    report_date: date = Query(..., description="报告日期"),
    workshop_id: Optional[str] = Query(None, description="车间ID"),
    limit: int = Query(50, description="返回数量限制")
):
    """获取车间汇总报告"""
    db = PostgresDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        summaries = db.get_workshop_summaries(
            report_type=report_type,
            report_date=report_date.isoformat(),
            workshop_id=workshop_id,
            limit=limit
        )

        result = []
        for _, row in summaries.iterrows():
            item = {}
            for col in summaries.columns:
                val = row[col]
                if hasattr(val, 'isoformat'):
                    item[col] = val.isoformat()
                elif val != val:
                    item[col] = None
                else:
                    item[col] = val
            result.append(item)

        return success_response(data={
            "total": len(result),
            "items": result
        })
    finally:
        db.close()


# ==================== 设备列表 API ====================

@router.get("/devices")
async def list_devices(
    workshop_id: Optional[str] = Query(None, description="车间ID")
):
    """获取设备列表"""
    aggregator = DataAggregator()

    if workshop_id:
        devices = aggregator.get_devices_by_workshop(workshop_id)
    else:
        devices = aggregator.get_all_devices()

    return success_response(data={
        "total": len(devices),
        "items": devices
    })


# ==================== 调度管理 API ====================

@router.post("/schedule/trigger")
async def trigger_scheduled_report(
    request: TriggerScheduledRequest,
    background_tasks: BackgroundTasks
):
    """
    手动触发定时报告生成

    会为所有设备生成指定类型的报告
    """
    scheduler = get_scheduler()

    report_date = datetime.combine(
        request.report_date or date.today(),
        datetime.min.time()
    )

    # 后台执行
    background_tasks.add_task(
        scheduler.run_reports,
        report_type=request.report_type,
        report_date=report_date,
        trigger_type='manual',
        triggered_by='api'
    )

    return success_response(
        msg=f"{request.report_type} 报告生成任务已触发",
        data={
            "status": "triggered",
            "report_type": request.report_type,
            "report_date": str(request.report_date or date.today())
        }
    )


@router.get("/jobs")
async def list_report_jobs(
    job_type: Optional[str] = Query(None, description="任务类型"),
    status: Optional[str] = Query(None, description="任务状态"),
    limit: int = Query(50, description="返回数量限制")
):
    """查询报告生成任务列表"""
    db = PostgresDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        jobs = db.get_report_jobs(
            job_type=job_type,
            job_status=status,
            limit=limit
        )

        result = []
        for _, row in jobs.iterrows():
            item = {}
            for col in jobs.columns:
                val = row[col]
                if hasattr(val, 'isoformat'):
                    item[col] = val.isoformat()
                elif val != val:
                    item[col] = None
                else:
                    item[col] = val
            result.append(item)

        return success_response(data={
            "total": len(result),
            "items": result
        })
    finally:
        db.close()


@router.get("/jobs/{job_id}")
async def get_job_detail(job_id: int):
    """获取任务详情"""
    db = PostgresDB()
    if not db.connect():
        return error_response(msg="数据库连接失败", code=500)

    try:
        result = db.get_report_job_by_id(job_id)

        if not result:
            return error_response(msg="任务不存在", code=404)

        for key, val in result.items():
            if hasattr(val, 'isoformat'):
                result[key] = val.isoformat()
            elif val != val:
                result[key] = None

        return success_response(data=result)
    finally:
        db.close()


@router.get("/schedule/status")
async def get_schedule_status():
    """获取调度器状态和已调度的任务"""
    scheduler = get_scheduler()
    jobs = scheduler.get_scheduled_jobs()

    return success_response(data={
        "running": scheduler._running,
        "scheduled_jobs": jobs
    })


# ==================== 模板管理 API ====================

@router.get("/templates")
async def list_templates():
    """列出可用的报告模板"""
    from .prompts import list_available_templates
    templates = list_available_templates()

    return success_response(data={
        "templates": [
            {"type": k, "file": v}
            for k, v in templates.items()
        ]
    })


# ==================== 故障预测 API ====================

class PredictRequest(BaseModel):
    device_code: str = Field(..., description="设备编码 (如 102000000996)")
    hours: int = Field(default=24, description="分析最近N小时数据", ge=1, le=168)
    explain_with_llm: bool = Field(default=False, description="是否用LLM解释预测结果")


class PredictResponse(BaseModel):
    device_code: str
    device_name: str
    model_type: str
    model_auc: Optional[float]
    latest_prediction: Optional[dict]
    risk_timeline: List[dict]
    llm_explanation: Optional[str]


@router.post("/predict", response_model=None)
async def predict_fault(request: PredictRequest):
    """
    设备故障预测

    基于 XGBoost 模型（10台和膏机合并训练, AUC 0.999）:
    1. 从数据库获取最近N小时原始参数
    2. 执行特征工程 Pipeline
    3. 模型预测故障概率
    4. 可选 LLM 解释预测结果
    """
    from modules.device_param.services import get_db_connection
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools"))
    from extract_device_features import (
        get_device_list, get_device_params, fetch_one_day,
        pivot_to_wide, add_rolling_features,
        add_interaction_features, add_alarm_features,
        fetch_status_for_range,
    )

    # 获取设备信息
    devices = get_device_list()
    dev = next((d for d in devices if d["device_code"] == request.device_code), None)
    if not dev:
        return error_response(
            msg=f"未找到设备: {request.device_code}",
            code=404)

    # 获取预测器
    predictor = get_predictor()
    if not predictor.is_ready:
        return error_response(
            msg="模型未加载。请确保 features_output/models/combined/fault_predictor_best.pkl 存在",
            code=500)

    # 加载最近N小时原始数据并执行特征工程
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(hours=request.hours)

    try:
        # 按天批量抽取
        conn = get_db_connection()
        if not conn:
            conn = __import__('psycopg2').connect(
                host=os.getenv("PG_HOST", "127.0.0.1"),
                port=int(os.getenv("PG_PORT", "5432")),
                user=os.getenv("PG_USER", "postgres"),
                password=os.getenv("PG_PASSWORD", ""),
                connect_timeout=20,
            )

        daily_parts = []
        cur_date = start_dt.date()
        end_date = end_dt.date()
        try:
            while cur_date <= end_date:
                raw = fetch_one_day(conn, request.device_code, cur_date)
                if not raw.empty:
                    wide = pivot_to_wide(raw)
                    if not wide.empty:
                        feats = add_rolling_features(wide)
                        daily_parts.append(feats)
                cur_date += timedelta(days=1)
        finally:
            conn.close()

        if not daily_parts:
            return error_response(
                msg=f"设备 {request.device_code} 在最近{request.hours}小时内无数据",
                code=404)

        features = pd.concat(daily_parts, axis=0).sort_index()

        # 获取告警上下文
        status_df = fetch_status_for_range(
            dev["numeric_id"], start_dt, end_dt)

        features = add_interaction_features(features)
        features = add_alarm_features(features, status_df)

        # 预测
        prediction = predictor.predict_latest(features)

        # 构建风险时间线（先用向量化布尔筛选，再只对命中的行 zip 取值，
        # 避免 iterrows() 逐行重建 Series 的开销）
        full_predictions = predictor.predict(features)
        risky = full_predictions[full_predictions["fault_probability"] > 0.1]
        risk_timeline = [
            {
                "time": str(ts),
                "fault_probability": round(float(prob), 4),
                "is_risk": bool(is_risk),
            }
            for ts, prob, is_risk in zip(risky.index, risky["fault_probability"], risky["is_risk"])
        ]

        # 告警上下文
        alarm_context = ""
        if not status_df.empty:
            recent_alarms = status_df[status_df["start_time"] >= start_dt]
            alarm_count = len(recent_alarms[recent_alarms["status"] == 2])
            if alarm_count > 0:
                alarm_context = f"最近{request.hours}小时内发生 {alarm_count} 次报警"

        response_data = {
            "device_code": request.device_code,
            "device_name": dev["device_name"],
            "model_type": predictor._model_type,
            "model_auc": predictor.metrics.get("auc_roc"),
            "latest_prediction": prediction,
            "risk_timeline": risk_timeline[-20:],  # 最近20个风险点
        }

        # LLM 解释
        if request.explain_with_llm and prediction and prediction.get("is_risk"):
            try:
                prompt = build_fault_explanation_prompt(
                    request.device_code, dev["device_name"],
                    prediction, alarm_context)

                from langchain_openai import ChatOpenAI
                from core.config import CONFIG
                llm = ChatOpenAI(
                    base_url=CONFIG.get_llm_base_url(),
                    api_key=CONFIG.get_llm_api_key(),
                    model=CONFIG.get_llm_model(),
                    temperature=0.3,
                )
                explanation = llm.invoke(prompt)
                response_data["llm_explanation"] = explanation.content
                response_data["llm_prompt"] = prompt
            except Exception as e:
                response_data["llm_explanation"] = f"LLM 解释生成失败: {str(e)}"

        return success_response(data=response_data)

    except Exception as e:
        return error_response(msg=f"预测失败: {str(e)}", code=500)


@router.get("/predict/model-info")
async def get_model_info():
    """获取故障预测模型信息"""
    predictor = get_predictor()

    if not predictor.is_ready:
        return success_response(data={
            "status": "model_not_loaded",
            "message": "模型文件未找到，请先训练模型"
        })

    return success_response(data={
        "status": "ready",
        "model_type": predictor._model_type,
        "metrics": predictor.metrics,
        "feature_count": len(predictor._feature_names),
    })


class ExplainRequest(BaseModel):
    device_code: str = Field(..., description="设备编码")
    hours: int = Field(default=24, ge=1, le=72, description="分析最近N小时数据")


@router.post("/predict/explain")
def explain_prediction(request: ExplainRequest):
    """
    SHAP 模型解释

    对最新时间点的故障预测进行 SHAP 分解：
    - top_push_fault: 推动故障概率升高的 Top-5 特征
    - top_push_normal: 抑制故障概率的 Top-5 特征
    - waterfall: 瀑布图数据（特征贡献排序）
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "tools"))
    from extract_device_features import (
        get_device_list, fetch_one_day,
        pivot_to_wide, add_rolling_features,
        add_interaction_features, add_alarm_features,
        fetch_status_for_range,
    )

    devices = get_device_list()
    dev = next((d for d in devices if d["device_code"] == request.device_code), None)
    if not dev:
        return error_response(msg=f"未找到设备: {request.device_code}", code=404)

    predictor = get_predictor()
    if not predictor.is_ready:
        return error_response(msg="模型未加载", code=500)

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(hours=request.hours)

    try:
        conn = __import__('psycopg2').connect(
            host=os.getenv("PG_HOST", "127.0.0.1"),
            port=int(os.getenv("PG_PORT", "5432")),
            user=os.getenv("PG_USER", "postgres"),
            password=os.getenv("PG_PASSWORD", ""),
            connect_timeout=20,
        )

        daily_parts = []
        cur_date = start_dt.date()
        end_date = end_dt.date()
        try:
            while cur_date <= end_date:
                raw = fetch_one_day(conn, request.device_code, cur_date)
                if not raw.empty:
                    wide = pivot_to_wide(raw)
                    if not wide.empty:
                        feats = add_rolling_features(wide)
                        daily_parts.append(feats)
                cur_date += timedelta(days=1)
        finally:
            conn.close()

        if not daily_parts:
            return error_response(msg="无数据", code=404)

        features = pd.concat(daily_parts, axis=0).sort_index()

        status_df = fetch_status_for_range(dev["numeric_id"], start_dt, end_dt)
        features = add_interaction_features(features)
        features = add_alarm_features(features, status_df)

        # SHAP 解释
        explanation = predictor.explain_with_shap(features)

        # 清洗特征名（去掉 __ 后缀便于阅读）
        for key in ["top_push_fault", "top_push_normal", "waterfall", "all_contributions"]:
            if key in explanation:
                for item in explanation[key]:
                    item["feature_clean"] = _clean_feature_name(item["feature"])

        # 附加预测结果
        latest = predictor.predict_latest(features)

        return success_response(data={
            "device_code": request.device_code,
            "device_name": dev["device_name"],
            "hours": request.hours,
            "prediction": latest,
            "explanation": explanation,
        })

    except Exception as e:
        return error_response(msg=f"解释失败: {str(e)}", code=500)


def _clean_feature_name(name: str) -> str:
    """清洗特征名便于人类阅读"""
    import re
    # 去掉 __5min_mean, __15min_std 等后缀
    name = re.sub(r'__(5min|15min|30min|60min)_(mean|std|max|min)', r'[\1 \2]', name)
    name = re.sub(r'__diff_per_min', '[变化率/分]', name)
    name = re.sub(r'^iact__', '[交互] ', name)
    name = re.sub(r'_div_', ' ÷ ', name)
    name = re.sub(r'_sub_', ' − ', name)
    name = re.sub(r'^alarm_cnt_(\d+)min', r'告警计数[\1分]', name)
    name = re.sub(r'^stop_cnt_(\d+)min', r'停机计数[\1分]', name)
    name = re.sub(r'^current_status', '当前状态', name)
    name = re.sub(r'^min_since_last_alarm', '距上次告警(分)', name)
    return name
