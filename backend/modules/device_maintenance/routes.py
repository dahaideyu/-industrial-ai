# cython: annotation_typing=False, infer_types=False, language_level=3
"""
设备运维报告路由
提供设备运维周报/月报的触发功能
"""
import os
import sys
import time
import uuid
import threading
import logging
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

# 确保 backend 目录在路径中
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(os.path.dirname(current_dir))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from core.response import success_response, error_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["device_maintenance"])

# 全局作业状态跟踪
JOB_STATUS = {}

# DeviceMaintenanceWorker 单例
_worker_instance = None
_worker_lock = threading.Lock()


def _get_worker():
    """获取 DeviceMaintenanceWorker 单例"""
    global _worker_instance
    if _worker_instance is None:
        with _worker_lock:
            if _worker_instance is None:
                from backend.modules.device_maintenance.worker import DeviceMaintenanceWorker
                _worker_instance = DeviceMaintenanceWorker()
    return _worker_instance


class DeviceMaintenanceRequest(BaseModel):
    """设备运维报告请求"""
    reportDate: Optional[str] = None
    periodType: str = "week"


@router.post("/device-maintenance/weekly")
async def device_maintenance_weekly(request: DeviceMaintenanceRequest):
    """
    触发设备运维周报
    """
    job_id = str(uuid.uuid4())[:8]

    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": "deviceMaintenanceReport",
        "reportDate": request.reportDate,
        "periodType": "week",
        "result": None,
        "error": None,
        "startTime": time.time(),
        "endTime": None,
    }

    def _run_job():
        try:
            result = _get_worker().run_device_maintenance_job(
                report_date=request.reportDate,
                period_type="week",
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

    logger.info(f"[设备运维周报] 作业已触发: jobId={job_id}, reportDate={request.reportDate}")

    return success_response(data={"jobId": job_id, "reportCode": "deviceMaintenanceReport", "periodType": "week"})


@router.post("/device-maintenance/monthly")
async def device_maintenance_monthly(request: DeviceMaintenanceRequest):
    """
    触发设备运维月报
    """
    job_id = str(uuid.uuid4())[:8]

    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": "deviceMaintenanceReport",
        "reportDate": request.reportDate,
        "periodType": "month",
        "result": None,
        "error": None,
        "startTime": time.time(),
        "endTime": None,
    }

    def _run_job():
        try:
            result = _get_worker().run_device_maintenance_job(
                report_date=request.reportDate,
                period_type="month",
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

    logger.info(f"[设备运维月报] 作业已触发: jobId={job_id}, reportDate={request.reportDate}")

    return success_response(data={"jobId": job_id, "reportCode": "deviceMaintenanceReport", "periodType": "month"})


@router.get("/device-maintenance/jobs/{job_id}")
async def get_device_maintenance_job_status(job_id: str):
    """
    查询设备运维报告作业状态

    Args:
        job_id: 作业ID

    Returns:
        作业状态信息
    """
    if job_id not in JOB_STATUS:
        return error_response(msg="作业不存在", code=404)

    status_info = JOB_STATUS[job_id].copy()

    # 计算耗时
    if status_info.get("endTime"):
        status_info["duration"] = round(status_info["endTime"] - status_info["startTime"], 2)
    elif status_info.get("startTime"):
        status_info["duration"] = round(time.time() - status_info["startTime"], 2)

    return success_response(data=status_info)
