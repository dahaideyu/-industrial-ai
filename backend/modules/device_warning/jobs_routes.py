# cython: annotation_typing=False, infer_types=False, language_level=3
from typing import Optional

from fastapi import APIRouter, Query

from modules.device_warning.services.job_manager import get_jobs, get_summary, get_job_history
from core.response import success_response, error_response

router = APIRouter(prefix="/api", tags=["jobs"])


def get_scheduled_maintenance_jobs():
    """获取预测性维护调度任务"""
    try:
        from modules.maintenance_report.services.scheduler import get_scheduler
        scheduler = get_scheduler()
        jobs = scheduler.get_scheduled_jobs()
        if not scheduler._running:
            # 如果任务已配置但调度器未运行，也返回任务列表（方便前端展示）
            # 同时附加 running 状态让前端知晓
            for job in jobs:
                job["scheduler_running"] = False
        return jobs
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"获取预测性维护调度任务失败: {e}", exc_info=True)
        return []


@router.get("/jobs")
def list_jobs(
    job_name: Optional[str] = Query(None, description="按任务名称筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    limit: int = Query(100, ge=1, le=1000, description="返回条数上限")
):
    """获取所有 Job 状态列表"""
    print(f"\n{'='*60}")
    print(f"[API] GET /api/jobs")
    print(f"{'='*60}")

    try:
        jobs = get_jobs(job_name=job_name, status=status, limit=limit)
        return success_response(data=jobs)
    except Exception as e:
        error_msg = f"获取 Job 状态失败: {str(e)}"
        print(f"[错误] {error_msg}")
        return error_response(msg=error_msg)


@router.get("/jobs/summary")
def jobs_summary():
    """获取 Job 状态统计摘要"""
    print(f"\n{'='*60}")
    print(f"[API] GET /api/jobs/summary")
    print(f"{'='*60}")

    try:
        summary = get_summary()
        return success_response(data=summary)
    except Exception as e:
        error_msg = f"获取 Job 摘要失败: {str(e)}"
        print(f"[错误] {error_msg}")
        return error_response(msg=error_msg)


@router.get("/jobs/scheduled")
def scheduled_jobs():
    """获取已调度的定时任务列表"""
    print(f"\n{'='*60}")
    print(f"[API] GET /api/jobs/scheduled")
    print(f"{'='*60}")

    try:
        scheduled = get_scheduled_maintenance_jobs()
        return success_response(data=scheduled)
    except Exception as e:
        error_msg = f"获取调度任务失败: {str(e)}"
        print(f"[错误] {error_msg}")
        return error_response(msg=error_msg)


@router.get("/jobs/{job_name}")
def job_by_name(job_name: str, limit: int = Query(50, ge=1, le=500)):
    """获取指定 Job 的历史记录"""
    print(f"\n{'='*60}")
    print(f"[API] GET /api/jobs/{job_name}")
    print(f"{'='*60}")

    try:
        jobs = get_job_history(job_name, limit=limit)
        return success_response(data=jobs)
    except Exception as e:
        error_msg = f"获取 Job 历史失败: {str(e)}"
        print(f"[错误] {error_msg}")
        return error_response(msg=error_msg)
