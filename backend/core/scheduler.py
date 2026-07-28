# cython: annotation_typing=False, infer_types=False, language_level=3
"""
调度器模块
提供 APScheduler 定时任务调度功能

目录任务(JOB_CATALOG)统一走"表驱动"注册：cron/enabled 存 system_job_config（UI 可改，
首次以 env `*_CRON` 播种），runner 复用 routes.system_jobs.MANUAL_RUNNERS，每次运行经
system_job_store.run_and_record 落 analysis_job_run（结果/异常入库）。
设备运维报告(device_maintenance)不在目录内，仍保留 env 驱动。
"""
import os
import sys
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

# 全局调度器实例
_scheduler_instance = None
_scheduler_lock = threading.Lock()


def get_scheduler():
    """获取调度器单例"""
    global _scheduler_instance
    if _scheduler_instance is None:
        with _scheduler_lock:
            if _scheduler_instance is None:
                from apscheduler.schedulers.background import BackgroundScheduler
                _scheduler_instance = BackgroundScheduler(timezone="Asia/Shanghai")
    return _scheduler_instance


def init_scheduler():
    """
    初始化调度器

    仅在 ENABLE_REPORT_SCHEDULER=true 时启动
    """
    scheduler_enabled = os.getenv("ENABLE_REPORT_SCHEDULER", "false").lower() == "true"
    if not scheduler_enabled:
        logger.info("[调度器] ENABLE_REPORT_SCHEDULER 未开启，跳过调度器初始化")
        return

    # 单例模式，防止重复初始化
    if _scheduler_instance is not None:
        logger.info("[调度器] 调度器已初始化，跳过")
        return

    try:
        scheduler = get_scheduler()

        # 表驱动统一注册目录任务（cron 存 system_job_config，首次以 env 播种）
        _register_catalog_jobs(scheduler)

        # 设备运维报告（非目录任务，仍 env 驱动）
        _register_device_maintenance_jobs(scheduler)

        # 启动调度器
        scheduler.start()
        logger.info("[调度器] 已启动")

        # 输出已调度的任务
        jobs = scheduler.get_jobs()
        logger.info(f"[调度器] 当前已调度任务数: {len(jobs)}")
        for job in jobs:
            logger.info(f"  - {job.id}: {job.name}")

    except Exception as e:
        logger.error(f"[调度器] 初始化失败: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════
# 表驱动统一注册（cron 存 system_job_config，runner 复用 MANUAL_RUNNERS）
# ═══════════════════════════════════════════════════════

def _make_catalog_job(job_id: str, name: str):
    """构造一个"记录运行"的定时任务闭包：跑 MANUAL_RUNNERS[job_id] 并落 analysis_job_run。"""
    def _job():
        logger.info(f"[调度器] 定时触发 {job_id}({name})")
        try:
            from routes.system_jobs import MANUAL_RUNNERS
            from core import system_job_store as store
            runner = MANUAL_RUNNERS.get(job_id)
            if runner is None:
                logger.warning(f"[调度器] {job_id} 无 runner，跳过")
                return
            result = store.run_and_record(job_id, runner)
            logger.info(f"[调度器] {job_id} 完成: {result}")
        except Exception as e:
            logger.error(f"[调度器] {job_id} 失败: {e}", exc_info=True)
    return _job


def _register_catalog_jobs(scheduler):
    """遍历 JOB_CATALOG，从 system_job_config 读 cron/enabled 注册（首次以 env 播种）。"""
    from routes.system_jobs import JOB_CATALOG
    from core import system_job_store as store
    from apscheduler.triggers.cron import CronTrigger

    try:
        store.ensure(JOB_CATALOG)          # 建表 + 首次以 env cron 播种
        configs = store.get_configs()
    except Exception as e:
        logger.error(f"[调度器] 读取 system_job_config 失败，回退 env: {e}", exc_info=True)
        configs = {}

    n = 0
    for c in JOB_CATALOG:
        jid = c["id"]
        cfg = configs.get(jid)
        cron = ((cfg.get("cron") if cfg else None) or os.getenv(c["cron_env"], "")).strip()
        enabled = cfg.get("enabled", True) if cfg else bool(cron)
        if not enabled or not cron:
            logger.info(f"[调度器] {jid} 未启用或无 cron，跳过")
            continue
        if len(cron.split()) != 5:
            logger.warning(f"[调度器] {jid} cron 格式错误: {cron}，跳过")
            continue
        try:
            scheduler.add_job(
                _make_catalog_job(jid, c["name"]),
                CronTrigger.from_crontab(cron, timezone="Asia/Shanghai"),
                id=jid, name=c["name"], replace_existing=True,
            )
            n += 1
            logger.info(f"[调度器] 已注册 {jid}: {cron}")
        except Exception as e:
            logger.error(f"[调度器] 注册 {jid} 失败({cron}): {e}", exc_info=True)
    logger.info(f"[调度器] 目录任务注册完成，共 {n} 个")


def apply_job_schedule(job_id: str) -> str:
    """UI 改 cron/启停后即时重排（仅当调度器已在运行）。

    返回：scheduled/removed/disabled/scheduler_not_running/unknown_job/no_runner/error。
    调度器未运行时只落表（下次启动生效）。
    """
    scheduler = _scheduler_instance
    if scheduler is None or not getattr(scheduler, "running", False):
        return "scheduler_not_running"
    try:
        from routes.system_jobs import JOB_CATALOG, MANUAL_RUNNERS
        from core import system_job_store as store
        from apscheduler.triggers.cron import CronTrigger
    except Exception as e:
        logger.error(f"[调度器] apply_job_schedule 导入失败: {e}")
        return "error"

    c = {x["id"]: x for x in JOB_CATALOG}.get(job_id)
    if not c:
        return "unknown_job"
    cfg = store.get_config(job_id) or {}
    cron = (cfg.get("cron") or "").strip()
    enabled = cfg.get("enabled", False)
    exists = scheduler.get_job(job_id) is not None

    if not enabled or not cron or len(cron.split()) != 5:
        if exists:
            scheduler.remove_job(job_id)
            return "removed"
        return "disabled"
    if MANUAL_RUNNERS.get(job_id) is None:
        return "no_runner"
    scheduler.add_job(
        _make_catalog_job(job_id, c["name"]),
        CronTrigger.from_crontab(cron, timezone="Asia/Shanghai"),
        id=job_id, name=c["name"], replace_existing=True,
    )
    return "scheduled"


# ═══════════════════════════════════════════════════════
# 设备运维报告（非目录任务，仍 env 驱动）
# ═══════════════════════════════════════════════════════

def _register_device_maintenance_jobs(scheduler):
    """注册设备运维报告定时任务"""

    # 周报
    weekly_cron = os.getenv("DEVICE_MAINTENANCE_WEEKLY_CRON", "")
    if weekly_cron:
        parts = weekly_cron.split()
        if len(parts) == 5:
            def _device_maintenance_weekly_job():
                logger.info("[调度器] 定时触发设备运维周报")
                try:
                    from backend.modules.device_maintenance.worker import DeviceMaintenanceWorker
                    worker = DeviceMaintenanceWorker()
                    result = worker.run_device_maintenance_job(period_type="week")
                    logger.info(f"[调度器] 设备运维周报完成: {result}")
                except Exception as e:
                    logger.error(f"[调度器] 设备运维周报失败: {e}", exc_info=True)

            scheduler.add_job(
                _device_maintenance_weekly_job,
                'cron',
                id='device_maintenance_weekly_report',
                name='设备运维周报',
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
                replace_existing=True
            )
            logger.info(f"[调度器] 已注册设备运维周报定时任务: {weekly_cron}")

    # 月报
    monthly_cron = os.getenv("DEVICE_MAINTENANCE_MONTHLY_CRON", "")
    if monthly_cron:
        parts = monthly_cron.split()
        if len(parts) == 5:
            def _device_maintenance_monthly_job():
                logger.info("[调度器] 定时触发设备运维月报")
                try:
                    from backend.modules.device_maintenance.worker import DeviceMaintenanceWorker
                    worker = DeviceMaintenanceWorker()
                    result = worker.run_device_maintenance_job(period_type="month")
                    logger.info(f"[调度器] 设备运维月报完成: {result}")
                except Exception as e:
                    logger.error(f"[调度器] 设备运维月报失败: {e}", exc_info=True)

            scheduler.add_job(
                _device_maintenance_monthly_job,
                'cron',
                id='device_maintenance_monthly_report',
                name='设备运维月报',
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
                replace_existing=True
            )
            logger.info(f"[调度器] 已注册设备运维月报定时任务: {monthly_cron}")
