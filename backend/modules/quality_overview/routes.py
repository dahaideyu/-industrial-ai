# cython: annotation_typing=False, infer_types=False, language_level=3
"""
质量概览报告路由
提供质量日/周/月报告的生成、触发等功能
"""
import os
import sys
import time
import uuid
import threading
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# 确保 backend 目录在路径中
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(os.path.dirname(current_dir))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from core.response import success_response, error_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["quality_overview"])

# 全局作业状态跟踪
JOB_STATUS = {}

# QualityOverviewWorker 单例
_worker_instance = None
_worker_lock = threading.Lock()


def _get_worker():
    """获取 QualityOverviewWorker 单例"""
    global _worker_instance
    if _worker_instance is None:
        with _worker_lock:
            if _worker_instance is None:
                from backend.modules.quality_overview.worker import QualityOverviewWorker
                _worker_instance = QualityOverviewWorker()
    return _worker_instance


class QualityOverviewRequest(BaseModel):
    """质量概览报告请求"""
    reportDate: Optional[str] = None
    workshopId: Optional[int] = None


@router.post("/quality_overview")
async def quality_overview(request: QualityOverviewRequest):
    """
    触发质量概览日周月报告（串行执行）

    依次生成日报、周报、月报
    """
    # 生成作业 ID
    job_id = str(uuid.uuid4())[:8]

    # 初始化作业状态
    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": "qualityOverviewReport",
        "reportDate": request.reportDate,
        "isBatch": True,
        "total": 3,
        "completed": 0,
        "failed": 0,
        "results": [],
        "error": None,
        "startTime": time.time(),
        "endTime": None,
    }

    # 后台线程执行作业
    def _run_job():
        try:
            result = _get_worker().run_quality_overview_job(report_date=request.reportDate, workshop_id=request.workshopId)

            JOB_STATUS[job_id]["status"] = "completed" if result.get("success") else "failed"
            JOB_STATUS[job_id]["completed"] = result.get("success_count", 0)
            JOB_STATUS[job_id]["failed"] = result.get("failed_count", 0)
            JOB_STATUS[job_id]["result"] = result

        except Exception as e:
            import traceback
            traceback.print_exc()
            JOB_STATUS[job_id]["status"] = "failed"
            JOB_STATUS[job_id]["error"] = str(e)

        finally:
            JOB_STATUS[job_id]["endTime"] = time.time()

    thread = threading.Thread(target=_run_job, daemon=True)
    thread.start()

    logger.info(f"[质量概览] 作业已触发: jobId={job_id}, reportDate={request.reportDate}")

    return success_response(data={"jobId": job_id, "reportCode": "qualityOverviewReport"})


@router.post("/quality_overview/daily")
async def quality_overview_daily(request: QualityOverviewRequest):
    """
    触发质量概览日报

    生成单份质量日报
    """
    # 生成作业 ID
    job_id = str(uuid.uuid4())[:8]

    # 初始化作业状态
    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": "qualityDailyReport",
        "reportDate": request.reportDate,
        "result": None,
        "error": None,
        "startTime": time.time(),
        "endTime": None,
    }

    # 后台线程执行作业
    def _run_job():
        try:
            result = _get_worker().run_quality_daily_job(report_date=request.reportDate, workshop_id=request.workshopId)

            JOB_STATUS[job_id]["status"] = "completed" if result.get("success") else "failed"
            JOB_STATUS[job_id]["result"] = result

        except Exception as e:
            import traceback
            traceback.print_exc()
            JOB_STATUS[job_id]["status"] = "failed"
            JOB_STATUS[job_id]["error"] = str(e)

        finally:
            JOB_STATUS[job_id]["endTime"] = time.time()

    thread = threading.Thread(target=_run_job, daemon=True)
    thread.start()

    logger.info(f"[质量日报] 作业已触发: jobId={job_id}, reportDate={request.reportDate}, workshopId={request.workshopId}")

    return success_response(data={"jobId": job_id, "reportCode": "qualityDailyReport"})


@router.post("/quality_overview/weekly")
async def quality_overview_weekly(request: QualityOverviewRequest):
    """
    触发质量概览周报

    生成单份质量周报
    """
    # 生成作业 ID
    job_id = str(uuid.uuid4())[:8]

    # 初始化作业状态
    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": "qualityWeeklyReport",
        "reportDate": request.reportDate,
        "result": None,
        "error": None,
        "startTime": time.time(),
        "endTime": None,
    }

    # 后台线程执行作业
    def _run_job():
        try:
            result = _get_worker().run_quality_weekly_job(report_date=request.reportDate, workshop_id=request.workshopId)

            JOB_STATUS[job_id]["status"] = "completed" if result.get("success") else "failed"
            JOB_STATUS[job_id]["result"] = result

        except Exception as e:
            import traceback
            traceback.print_exc()
            JOB_STATUS[job_id]["status"] = "failed"
            JOB_STATUS[job_id]["error"] = str(e)

        finally:
            JOB_STATUS[job_id]["endTime"] = time.time()

    thread = threading.Thread(target=_run_job, daemon=True)
    thread.start()

    logger.info(f"[质量周报] 作业已触发: jobId={job_id}, reportDate={request.reportDate}, workshopId={request.workshopId}")

    return success_response(data={"jobId": job_id, "reportCode": "qualityWeeklyReport"})


@router.post("/quality_overview/monthly")
async def quality_overview_monthly(request: QualityOverviewRequest):
    """
    触发质量概览月报

    生成单份质量月报
    """
    # 生成作业 ID
    job_id = str(uuid.uuid4())[:8]

    # 初始化作业状态
    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": "qualityMonthlyReport",
        "reportDate": request.reportDate,
        "result": None,
        "error": None,
        "startTime": time.time(),
        "endTime": None,
    }

    # 后台线程执行作业
    def _run_job():
        try:
            result = _get_worker().run_quality_monthly_job(report_date=request.reportDate, workshop_id=request.workshopId)

            JOB_STATUS[job_id]["status"] = "completed" if result.get("success") else "failed"
            JOB_STATUS[job_id]["result"] = result

        except Exception as e:
            import traceback
            traceback.print_exc()
            JOB_STATUS[job_id]["status"] = "failed"
            JOB_STATUS[job_id]["error"] = str(e)

        finally:
            JOB_STATUS[job_id]["endTime"] = time.time()

    thread = threading.Thread(target=_run_job, daemon=True)
    thread.start()

    logger.info(f"[质量月报] 作业已触发: jobId={job_id}, reportDate={request.reportDate}, workshopId={request.workshopId}")

    return success_response(data={"jobId": job_id, "reportCode": "qualityMonthlyReport"})