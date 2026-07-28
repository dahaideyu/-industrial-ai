# cython: annotation_typing=False, infer_types=False, language_level=3
"""
精益早会日报路由
提供精益早会日报的生成、批量触发、工厂级报告等功能
"""
import os
import sys
import time
import uuid
import threading
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# 确保 backend 目录在路径中
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(os.path.dirname(current_dir))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from core.response import success_response, error_response
from core import database as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["lean_morning_daily"])

# 全局作业状态跟踪
JOB_STATUS = {}

# AgentWorker 单例
_worker_instance = None
_worker_lock = threading.Lock()


def _get_worker():
    """获取 AgentWorker 单例"""
    global _worker_instance
    if _worker_instance is None:
        with _worker_lock:
            if _worker_instance is None:
                from backend.modules.lean_morning_daily.worker import AgentWorker
                _worker_instance = AgentWorker()
    return _worker_instance


class AgentTriggerRequest(BaseModel):
    """手动触发作业请求"""
    reportCode: str = "leanMorningDailyReport"
    workshopId: int
    procedureId: int
    reportDate: Optional[str] = None
    templateLimit: Optional[int] = None  # 报告份数限制（1=傍晚版仅基础日报）


class BatchTriggerRequest(BaseModel):
    """批量触发请求"""
    reportCode: str = "leanMorningDailyReport"
    reportDate: Optional[str] = None
    workshopIds: Optional[List[int]] = None
    templateLimit: Optional[int] = None  # 报告份数限制（1=傍晚版仅基础日报）


class FactoryReportRequest(BaseModel):
    """工厂级报告请求"""
    reportDate: str
    reportCode: str = "leanMorningDailyReport"


@router.post("/agent/trigger")
async def agent_trigger(request: AgentTriggerRequest):
    """
    手动触发 Agent 作业（后台异步执行）

    立即返回 jobId，后台线程执行作业
    """
    job_id = str(uuid.uuid4())[:8]

    # 初始化作业状态
    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": request.reportCode,
        "workshopId": request.workshopId,
        "procedureId": request.procedureId,
        "reportDate": request.reportDate,
        "result": None,
        "error": None,
        "startTime": time.time(),
    }

    # 后台线程执行作业
    def _run_job():
        try:
            if request.reportCode == "leanMorningDailyReport":
                result = _get_worker().run_lean_morning_daily_job(
                    workshop_id=request.workshopId,
                    procedure_id=request.procedureId,
                    report_date=request.reportDate,
                    template_limit=request.templateLimit,
                )
            else:
                result = {
                    "success": False,
                    "error": f"不支持的 reportCode: {request.reportCode}",
                    "callbackOk": None,
                    "reports": [],
                }

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

    logger.info(f"[Agent] 作业已触发: jobId={job_id}, reportCode={request.reportCode}, workshopId={request.workshopId}, procedureId={request.procedureId}")

    return success_response(data={"jobId": job_id, "reportCode": request.reportCode})


@router.get("/agent/jobs/{job_id}")
async def agent_job_status(job_id: str):
    """查询作业状态"""
    if job_id not in JOB_STATUS:
        return error_response(msg="作业不存在", code=404, status_code=404)

    status_info = JOB_STATUS[job_id].copy()
    # 计算耗时
    if "endTime" in status_info:
        status_info["elapsedTime"] = round(status_info["endTime"] - status_info["startTime"], 2)
    else:
        status_info["elapsedTime"] = round(time.time() - status_info["startTime"], 2)

    return success_response(data=status_info)


@router.post("/agent/trigger/batch")
async def agent_trigger_batch(request: BatchTriggerRequest):
    """
    批量触发精益早会日报（后台异步执行）

    返回 jobId，可通过 /api/agent/jobs/<job_id> 查询进度
    """
    # 校验 reportCode
    if request.reportCode != "leanMorningDailyReport":
        return error_response(msg="批量模式仅支持 reportCode=leanMorningDailyReport", code=400, status_code=400)

    # 生成作业 ID
    job_id = str(uuid.uuid4())[:8]

    # 初始化批量作业状态
    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": request.reportCode,
        "reportDate": request.reportDate,
        "workshopIds": request.workshopIds,
        "isBatch": True,
        "total": 0,
        "completed": 0,
        "failed": 0,
        "currentWorkshop": None,
        "currentProcedure": None,
        "results": [],
        "error": None,
        "startTime": time.time(),
        "endTime": None,
    }

    # 后台线程执行批量作业
    def _run_batch_job():
        try:
            result = _get_worker().run_batch_lean_morning_daily_job(
                report_date=request.reportDate,
                workshop_ids=request.workshopIds,
                template_limit=request.templateLimit,
            )

            JOB_STATUS[job_id]["status"] = "failed" if result.get("error") else "completed"
            JOB_STATUS[job_id]["total"] = result.get("total", 0)
            JOB_STATUS[job_id]["completed"] = result.get("success", 0)
            JOB_STATUS[job_id]["failed"] = result.get("failed", 0)
            JOB_STATUS[job_id]["result"] = result
            JOB_STATUS[job_id]["currentWorkshop"] = None
            JOB_STATUS[job_id]["currentProcedure"] = None

        except Exception as e:
            import traceback
            traceback.print_exc()
            JOB_STATUS[job_id]["status"] = "failed"
            JOB_STATUS[job_id]["error"] = str(e)

        finally:
            JOB_STATUS[job_id]["endTime"] = time.time()

    thread = threading.Thread(target=_run_batch_job, daemon=True)
    thread.start()

    workshop_desc = "全部车间" if request.workshopIds is None else f"指定车间 {request.workshopIds}"
    logger.info(f"[Agent] 批量作业已触发: jobId={job_id}, reportCode={request.reportCode}, {workshop_desc}")

    return success_response(data={"jobId": job_id, "reportCode": request.reportCode, "workshopIds": request.workshopIds})


@router.post("/factory-report/generate")
async def factory_report_generate(request: FactoryReportRequest):
    """
    同步生成工厂级报告（从数据库读取当天已生成的车间报告）
    """
    try:
        # 1. 从数据库查询当天所有车间报告
        workshop_reports = db.query_workshop_reports_by_date(
            report_date=request.reportDate,
        )

        if not workshop_reports:
            return error_response(msg=f"未找到日期为 {request.reportDate} 的车间报告，请先生成车间级报告", code=404, status_code=404)

        logger.info(f"[工厂级报告] 从数据库读取到 {len(workshop_reports)} 份车间报告")

        # 2. 生成工厂级报告
        worker = _get_worker()
        result = worker._generate_factory_level_reports(
            all_workshop_reports=workshop_reports,
            report_date=request.reportDate,
        )

        if result.get("success"):
            logger.info(f"[工厂级报告] 生成成功，报告 ID: {result.get('reportId')}")
            return success_response(data={
                "reportDate": request.reportDate,
                "reportId": result.get("reportId"),
                "workshopReportCount": len(workshop_reports),
                "reports": result.get("reports", []),
                "logFile": result.get("logFile"),
            })
        else:
            error_msg = result.get("error", "未知错误")
            logger.error(f"[工厂级报告] 生成失败: {error_msg}")
            return error_response(msg=f"工厂级报告生成失败: {error_msg}", code=500, status_code=500)

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"[工厂级报告] 异常: {e}")
        return error_response(msg=f"工厂级报告生成异常: {str(e)}", code=500, status_code=500)


@router.post("/factory-report/trigger")
async def factory_report_trigger(request: FactoryReportRequest):
    """
    异步触发生成工厂级报告（后台线程执行）

    返回 jobId，可通过 /api/agent/jobs/<job_id> 查询进度
    """
    # 生成作业 ID
    job_id = str(uuid.uuid4())[:8]

    # 初始化作业状态
    JOB_STATUS[job_id] = {
        "jobId": job_id,
        "status": "running",
        "reportCode": request.reportCode,
        "reportDate": request.reportDate,
        "isBatch": False,
        "isFactoryReport": True,
        "total": 1,
        "completed": 0,
        "failed": 0,
        "workshopReportCount": 0,
        "result": None,
        "error": None,
        "startTime": time.time(),
        "endTime": None,
    }

    # 后台线程执行工厂级报告生成
    def _run_factory_report_job():
        try:
            # 1. 从数据库查询当天所有车间报告
            workshop_reports = db.query_workshop_reports_by_date(
                report_date=request.reportDate,
            )

            JOB_STATUS[job_id]["workshopReportCount"] = len(workshop_reports)

            if not workshop_reports:
                JOB_STATUS[job_id]["status"] = "failed"
                JOB_STATUS[job_id]["error"] = f"未找到日期为 {request.reportDate} 的车间报告"
                return

            # 2. 生成工厂级报告
            worker = _get_worker()
            result = worker._generate_factory_level_reports(
                all_workshop_reports=workshop_reports,
                report_date=request.reportDate,
            )

            if result.get("success"):
                JOB_STATUS[job_id]["status"] = "completed"
                JOB_STATUS[job_id]["completed"] = 1
                JOB_STATUS[job_id]["result"] = result
            else:
                JOB_STATUS[job_id]["status"] = "failed"
                JOB_STATUS[job_id]["failed"] = 1
                JOB_STATUS[job_id]["error"] = result.get("error", "未知错误")

        except Exception as e:
            import traceback
            traceback.print_exc()
            JOB_STATUS[job_id]["status"] = "failed"
            JOB_STATUS[job_id]["error"] = str(e)

        finally:
            JOB_STATUS[job_id]["endTime"] = time.time()

    thread = threading.Thread(target=_run_factory_report_job, daemon=True)
    thread.start()

    logger.info(f"[工厂级报告] 异步作业已触发: jobId={job_id}, reportDate={request.reportDate}")

    return success_response(data={"jobId": job_id, "reportDate": request.reportDate})