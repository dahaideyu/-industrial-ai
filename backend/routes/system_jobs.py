# cython: annotation_typing=False, infer_types=False, language_level=3
"""系统管理 · 统一 Job 管理 API。

把分散在 core/scheduler.py 的所有定时任务(精益早会/质量/设备效率/参数趋势汇总/AI诊断简报)
集中成一张可视、可编辑、可手动触发的清单：cron 计划 + 调度器下次运行 + 最近运行结果/异常 + 立即运行。

cron/enabled 存 system_job_config(UI 可改，改后即时重排)；每次运行经 system_job_store.run_and_record
落 analysis_job_run(结果/异常入库)。运行历史见 GET /jobs/{id}/runs。
"""
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from core.response import success_response, error_response

router = APIRouter(prefix="/api/system", tags=["system-jobs"])


# 可管理的定时任务目录（id 与 core/scheduler.py add_job 的 id 一致）
JOB_CATALOG: List[Dict[str, str]] = [
    {"id": "lean_morning_daily_report", "name": "精益早会日报", "group": "报告",
     "cron_env": "LEAN_MORNING_DAILY_CRON"},
    {"id": "lean_morning_daily_report_evening", "name": "精益早会日报（傍晚版）", "group": "报告",
     "cron_env": "LEAN_MORNING_DAILY_EVENING_CRON"},
    {"id": "quality_daily_report", "name": "质量概览日报", "group": "报告",
     "cron_env": "QUALITY_DAILY_CRON"},
    {"id": "quality_weekly_report", "name": "质量概览周报", "group": "报告",
     "cron_env": "QUALITY_WEEKLY_CRON"},
    {"id": "quality_monthly_report", "name": "质量概览月报", "group": "报告",
     "cron_env": "QUALITY_MONTHLY_CRON"},
    {"id": "device_efficiency_daily_report", "name": "设备效率日报", "group": "报告",
     "cron_env": "DEVICE_EFFICIENCY_DAILY_CRON"},
    {"id": "device_efficiency_weekly_report", "name": "设备效率周报", "group": "报告",
     "cron_env": "DEVICE_EFFICIENCY_WEEKLY_CRON"},
    {"id": "device_efficiency_monthly_report", "name": "设备效率月报", "group": "报告",
     "cron_env": "DEVICE_EFFICIENCY_MONTHLY_CRON"},
    {"id": "device_param_rollup", "name": "设备参数趋势漂移汇总", "group": "设备参数",
     "cron_env": "DEVICE_PARAM_ROLLUP_CRON"},
    {"id": "device_param_diagnosis", "name": "设备AI自主诊断简报", "group": "设备参数",
     "cron_env": "DEVICE_DIAG_CRON"},
    {"id": "device_param_profile_suggest", "name": "参数画像夜间预生成", "group": "设备参数",
     "cron_env": "DEVICE_PROFILE_CRON"},
    {"id": "device_param_alert_diag", "name": "分阶段报警知识库诊断", "group": "设备参数",
     "cron_env": "DEVICE_PARAM_ALERT_DIAG_CRON"},
]


def _manual_rollup():
    from modules.device_param.rollup_worker import run_rollup_job
    return run_rollup_job()


def _manual_diag():
    from modules.device_param.diag_worker import run_diagnosis_job
    return run_diagnosis_job()


def _manual_profile():
    from modules.device_param.profile_worker import run_profile_suggest_job
    return run_profile_suggest_job()


def _manual_alert_diag():
    from modules.device_param.alert_diag_worker import run_alert_diag_job
    return run_alert_diag_job()


def _manual_lean_morning_daily():
    from modules.lean_morning_daily.worker import AgentWorker
    worker = AgentWorker()
    batch_enabled = os.getenv("LEAN_MORNING_DAILY_BATCH_ENABLED", "false").lower() == "true"
    if batch_enabled:
        batch_workshop_ids_str = os.getenv("LEAN_MORNING_DAILY_WORKSHOP_IDS", "")
        batch_workshop_ids = None
        if batch_workshop_ids_str:
            try:
                batch_workshop_ids = [int(wid.strip()) for wid in batch_workshop_ids_str.split(",") if wid.strip()]
            except (ValueError, TypeError):
                pass
        return worker.run_batch_lean_morning_daily_job(report_date=None, workshop_ids=batch_workshop_ids)
    else:
        workshop_id = int(os.getenv("LEAN_MORNING_DAILY_WORKSHOP_ID", "1"))
        procedure_id = int(os.getenv("LEAN_MORNING_DAILY_PROCEDURE_ID", "1"))
        return worker.run_lean_morning_daily_job(workshop_id=workshop_id, procedure_id=procedure_id)


def _manual_lean_morning_daily_evening():
    """傍晚版精益早会日报（T+0，当天白班数据，只生成基础日报）"""
    from modules.lean_morning_daily.worker import AgentWorker
    worker = AgentWorker()
    today_str = datetime.now().strftime("%Y-%m-%d")
    batch_enabled = os.getenv("LEAN_MORNING_DAILY_BATCH_ENABLED", "false").lower() == "true"
    if batch_enabled:
        batch_workshop_ids_str = os.getenv("LEAN_MORNING_DAILY_WORKSHOP_IDS", "")
        batch_workshop_ids = None
        if batch_workshop_ids_str:
            try:
                batch_workshop_ids = [int(wid.strip()) for wid in batch_workshop_ids_str.split(",") if wid.strip()]
            except (ValueError, TypeError):
                pass
        return worker.run_batch_lean_morning_daily_job(
            report_date=today_str, workshop_ids=batch_workshop_ids, template_limit=1,
        )
    else:
        workshop_id = int(os.getenv("LEAN_MORNING_DAILY_WORKSHOP_ID", "1"))
        procedure_id = int(os.getenv("LEAN_MORNING_DAILY_PROCEDURE_ID", "1"))
        return worker.run_lean_morning_daily_job(
            workshop_id=workshop_id, procedure_id=procedure_id,
            report_date=today_str, template_limit=1,
        )


def _run_quality_batch(report_type: str):
    from modules.quality_overview.worker import QualityOverviewWorker
    from core.singletons import get_upstream_client
    worker = QualityOverviewWorker()
    workshop_ids = []
    try:
        upstream = get_upstream_client()
        all_workshops = upstream.get_workshop_tree()
        workshop_ids = [w["id"] for w in all_workshops]
    except Exception:
        pass
    result = getattr(worker, f"run_quality_{report_type}_job")()
    for wid in workshop_ids:
        try:
            getattr(worker, f"run_quality_{report_type}_job")(workshop_id=wid)
        except Exception:
            pass
    return result


def _manual_quality_daily():
    return _run_quality_batch("daily")


def _manual_quality_weekly():
    return _run_quality_batch("weekly")


def _manual_quality_monthly():
    return _run_quality_batch("monthly")


def _run_device_efficiency_batch(period_type: str):
    from modules.device_efficiency.worker import DeviceEfficiencyWorker
    from core.singletons import get_upstream_client
    worker = DeviceEfficiencyWorker()
    ids_str = os.getenv("DEVICE_EFFICIENCY_WORKSHOP_IDS", "")
    workshop_ids = []
    if ids_str:
        try:
            workshop_ids = [int(wid.strip()) for wid in ids_str.split(",") if wid.strip()]
        except (ValueError, TypeError):
            pass
    if not workshop_ids:
        single = os.getenv("DEVICE_EFFICIENCY_WORKSHOP_ID", "").strip()
        if single:
            try:
                workshop_ids = [int(single)]
            except (ValueError, TypeError):
                pass
    if not workshop_ids:
        try:
            upstream = get_upstream_client()
            all_workshops = upstream.get_workshop_tree()
            workshop_ids = [w["id"] for w in all_workshops]
        except Exception:
            pass
    result = worker.run_device_efficiency_job(period_type=period_type)
    for wid in workshop_ids:
        try:
            worker.run_device_efficiency_job(workshop_id=wid, period_type=period_type)
        except Exception:
            pass
    return result


def _manual_device_efficiency_daily():
    return _run_device_efficiency_batch("day")


def _manual_device_efficiency_weekly():
    return _run_device_efficiency_batch("week")


def _manual_device_efficiency_monthly():
    return _run_device_efficiency_batch("month")


# 即使调度器未开启也能手动触发的任务
MANUAL_RUNNERS = {
    "device_param_rollup": _manual_rollup,
    "device_param_diagnosis": _manual_diag,
    "device_param_profile_suggest": _manual_profile,
    "device_param_alert_diag": _manual_alert_diag,
    "lean_morning_daily_report": _manual_lean_morning_daily,
    "lean_morning_daily_report_evening": _manual_lean_morning_daily_evening,
    "quality_daily_report": _manual_quality_daily,
    "quality_weekly_report": _manual_quality_weekly,
    "quality_monthly_report": _manual_quality_monthly,
    "device_efficiency_daily_report": _manual_device_efficiency_daily,
    "device_efficiency_weekly_report": _manual_device_efficiency_weekly,
    "device_efficiency_monthly_report": _manual_device_efficiency_monthly,
}


def _scheduler_jobs_by_id() -> Dict[str, Any]:
    """取调度器中已注册的 job（按 id）。调度器未启用/未起则空。"""
    try:
        from core.scheduler import _scheduler_instance
        if _scheduler_instance is None:
            return {}
        return {j.id: j for j in _scheduler_instance.get_jobs()}
    except Exception:
        return {}


@router.get("/jobs")
def list_system_jobs():
    """统一定时任务清单：cron/enabled(存表) + 调度器下次运行 + 最近运行结果/异常 + 手动触发。"""
    scheduler_enabled = os.getenv("ENABLE_REPORT_SCHEDULER", "false").lower() == "true"
    sched = _scheduler_jobs_by_id()

    from core import system_job_store as store
    try:
        store.ensure(JOB_CATALOG)          # 建表 + 首次以 env 播种（幂等）
    except Exception:
        pass
    configs = store.get_configs()
    latest = store.latest_runs()

    items = []
    seen = set()
    for c in JOB_CATALOG:
        jid = c["id"]
        seen.add(jid)
        cfg = configs.get(jid, {})
        cron = (cfg.get("cron") or os.getenv(c["cron_env"], "")).strip()
        cfg_enabled = cfg.get("enabled", bool(cron))
        job = sched.get(jid)
        nxt = (job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
               if job is not None and getattr(job, "next_run_time", None) else None)
        if not cfg_enabled:
            status = "已停用"
        elif not cron:
            status = "未配置"
        elif not scheduler_enabled:
            status = "调度器未开启"
        elif job is None:
            status = "已配置(未注册)"
        else:
            status = "运行中"
        items.append({
            "id": jid, "name": c["name"], "group": c["group"],
            "cron_env": c["cron_env"], "cron": cron or None, "enabled": bool(cfg_enabled),
            "next_run_time": nxt, "status": status,
            "manual": jid in MANUAL_RUNNERS or job is not None,
            "last_run": latest.get(jid),
        })

    # 兜底：调度器里有、但不在目录里的任务也列出（避免遗漏）
    for jid, job in sched.items():
        if jid in seen:
            continue
        nxt = (job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
               if getattr(job, "next_run_time", None) else None)
        items.append({"id": jid, "name": getattr(job, "name", jid), "group": "其他",
                      "cron_env": None, "cron": str(getattr(job, "trigger", "")),
                      "enabled": True, "next_run_time": nxt, "status": "运行中",
                      "manual": True, "last_run": latest.get(jid)})

    return success_response(data={"scheduler_enabled": scheduler_enabled,
                                  "count": len(items), "jobs": items})


class RunJobRequest(BaseModel):
    job_id: str


@router.post("/jobs/run")
def run_system_job(req: RunJobRequest):
    """手动触发一个任务（后台线程异步执行，立即返回）。结果见对应任务日志/历史。"""
    job_id = req.job_id
    runner: Optional[Any] = MANUAL_RUNNERS.get(job_id)

    if runner is None:
        # 回退：调度器里有该 job 则调用其注册的函数
        job = _scheduler_jobs_by_id().get(job_id)
        if job is not None and callable(getattr(job, "func", None)):
            runner = job.func
    if runner is None:
        return error_response(
            msg=f"任务 {job_id} 不支持手动触发（需开启调度器或为内置可触发任务）", code=400)

    def _bg():
        try:
            from core import system_job_store as store
            store.run_and_record(job_id, runner)   # 结果/异常入库 analysis_job_run
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"手动触发任务 {job_id} 失败: {e}", exc_info=True)

    threading.Thread(target=_bg, name=f"manual-job-{job_id}", daemon=True).start()
    return success_response(data={"job_id": job_id, "triggered": True,
                                  "msg": "已在后台触发，请稍后在运行历史查看结果。"})


class JobConfigRequest(BaseModel):
    job_id: str
    cron: Optional[str] = None
    enabled: bool = True
    updated_by: Optional[str] = None


@router.post("/jobs/config")
def save_job_config(req: JobConfigRequest):
    """改某任务的 cron/启停（存 system_job_config）；调度器在跑则即时重排。"""
    if req.job_id not in {c["id"] for c in JOB_CATALOG}:
        return error_response(msg=f"未知任务 {req.job_id}", code=400)
    cron = (req.cron or "").strip()
    if req.enabled and cron and len(cron.split()) != 5:
        return error_response(msg="cron 表达式须为 5 段(分 时 日 月 周)", code=400)

    from core import system_job_store as store
    if not store.upsert_config(req.job_id, cron or None, req.enabled, req.updated_by):
        return error_response(msg="保存失败（数据库不可用？）", code=500)

    applied = "not_applied"
    try:
        from core.scheduler import apply_job_schedule
        applied = apply_job_schedule(req.job_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"重排 {req.job_id} 失败: {e}", exc_info=True)
    return success_response(data={"job_id": req.job_id, "cron": cron or None,
                                  "enabled": req.enabled, "applied": applied})


@router.get("/jobs/{job_id}/runs")
def get_job_runs(job_id: str, limit: int = 20):
    """某任务最近运行历史（analysis_job_run）。"""
    from core import system_job_store as store
    runs = store.job_runs(job_id, limit=limit)
    return success_response(data={"job_id": job_id, "count": len(runs), "runs": runs})
