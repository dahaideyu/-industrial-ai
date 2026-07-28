# cython: annotation_typing=False, infer_types=False, language_level=3
"""
设备效率报告路由
提供设备效率日/周/月报告的生成、触发等功能
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

router = APIRouter(prefix="/api", tags=["device_efficiency"])

# 全局作业状态跟踪
JOB_STATUS = {}

# DeviceEfficiencyWorker 单例
_worker_instance = None
_worker_lock = threading.Lock()


def _get_worker():
    """获取 DeviceEfficiencyWorker 单例"""
    global _worker_instance
    if _worker_instance is None:
        with _worker_lock:
            if _worker_instance is None:
                from backend.modules.device_efficiency.worker import DeviceEfficiencyWorker
                _worker_instance = DeviceEfficiencyWorker()
    return _worker_instance


class DeviceEfficiencyRequest(BaseModel):
    """设备效率报告请求"""
    reportDate: Optional[str] = None
    workshopId: Optional[int] = None
    periodType: str = "day"


@router.post("/device-efficiency/daily")
async def device_efficiency_daily(request: DeviceEfficiencyRequest):
    """
    触发设备效率日报

    生成单份设备效率日报
    """
    # 生成作业 ID
    job_id = str(uuid.uuid4())[:8]

    # 初始化作业状态
    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": "deviceEfficiencyReport",
        "reportDate": request.reportDate,
        "periodType": "day",
        "result": None,
        "error": None,
        "startTime": time.time(),
        "endTime": None,
    }

    # 后台线程执行作业
    def _run_job():
        try:
            result = _get_worker().run_device_efficiency_job(
                report_date=request.reportDate,
                workshop_id=request.workshopId,
                period_type="day"
            )

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

    logger.info(f"[设备效率日报] 作业已触发: jobId={job_id}, reportDate={request.reportDate}")

    return success_response(data={"jobId": job_id, "reportCode": "deviceEfficiencyReport", "periodType": "day"})


@router.post("/device-efficiency/weekly")
async def device_efficiency_weekly(request: DeviceEfficiencyRequest):
    """
    触发设备效率周报

    生成单份设备效率周报
    """
    # 生成作业 ID
    job_id = str(uuid.uuid4())[:8]

    # 初始化作业状态
    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": "deviceEfficiencyReport",
        "reportDate": request.reportDate,
        "periodType": "week",
        "result": None,
        "error": None,
        "startTime": time.time(),
        "endTime": None,
    }

    # 后台线程执行作业
    def _run_job():
        try:
            result = _get_worker().run_device_efficiency_job(
                report_date=request.reportDate,
                workshop_id=request.workshopId,
                period_type="week"
            )

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

    logger.info(f"[设备效率周报] 作业已触发: jobId={job_id}, reportDate={request.reportDate}")

    return success_response(data={"jobId": job_id, "reportCode": "deviceEfficiencyReport", "periodType": "week"})


@router.post("/device-efficiency/monthly")
async def device_efficiency_monthly(request: DeviceEfficiencyRequest):
    """
    触发设备效率月报

    生成单份设备效率月报
    """
    # 生成作业 ID
    job_id = str(uuid.uuid4())[:8]

    # 初始化作业状态
    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": "deviceEfficiencyReport",
        "reportDate": request.reportDate,
        "periodType": "month",
        "result": None,
        "error": None,
        "startTime": time.time(),
        "endTime": None,
    }

    # 后台线程执行作业
    def _run_job():
        try:
            result = _get_worker().run_device_efficiency_job(
                report_date=request.reportDate,
                workshop_id=request.workshopId,
                period_type="month"
            )

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

    logger.info(f"[设备效率月报] 作业已触发: jobId={job_id}, reportDate={request.reportDate}")

    return success_response(data={"jobId": job_id, "reportCode": "deviceEfficiencyReport", "periodType": "month"})
