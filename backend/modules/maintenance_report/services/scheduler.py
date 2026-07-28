# cython: annotation_typing=False, infer_types=False, language_level=3
"""
报告调度服务 - 定时生成日报/周报/月报
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from modules.device_warning.ai_analysis.postgres_loader import PostgresDB
from .report_generator import MaintenanceReportGenerator
from .data_aggregator import DataAggregator

logger = logging.getLogger(__name__)


class ReportScheduler:
    """报告调度器"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.report_generator = MaintenanceReportGenerator()
        self.data_aggregator = DataAggregator()
        self.db = PostgresDB()
        self._running = False

    def start(self):
        """启动调度器"""
        if self._running:
            logger.warning("调度器已在运行")
            return

        # 每日凌晨 1:00 生成日报
        self.scheduler.add_job(
            self._run_daily_reports,
            CronTrigger(hour=1, minute=0),
            id='daily_maintenance_reports',
            name='每日设备维护报告',
            replace_existing=True
        )

        # 每周一凌晨 2:00 生成周报
        self.scheduler.add_job(
            self._run_weekly_reports,
            CronTrigger(day_of_week='mon', hour=2, minute=0),
            id='weekly_maintenance_reports',
            name='每周设备维护报告',
            replace_existing=True
        )

        # 每月 1 日凌晨 3:00 生成月报
        self.scheduler.add_job(
            self._run_monthly_reports,
            CronTrigger(day=1, hour=3, minute=0),
            id='monthly_maintenance_reports',
            name='每月设备维护报告',
            replace_existing=True
        )

        self.scheduler.start()
        self._running = True
        logger.info("报告调度器已启动")
        logger.info("  - 日报: 每天 01:00")
        logger.info("  - 周报: 每周一 02:00")
        logger.info("  - 月报: 每月1日 03:00")

    def stop(self):
        """停止调度器"""
        if self._running:
            self.scheduler.shutdown()
            self._running = False
            logger.info("报告调度器已停止")

    async def _run_daily_reports(self, report_date: datetime = None):
        """运行日报生成"""
        await self.run_reports('daily', report_date)

    async def _run_weekly_reports(self, report_date: datetime = None):
        """运行周报生成"""
        await self.run_reports('weekly', report_date)

    async def _run_monthly_reports(self, report_date: datetime = None):
        """运行月报生成"""
        await self.run_reports('monthly', report_date)

    async def run_reports(
        self,
        report_type: str,
        report_date: datetime = None,
        trigger_type: str = 'scheduled',
        triggered_by: str = None
    ) -> dict:
        """
        运行报告生成

        Args:
            report_type: 报告类型 (daily/weekly/monthly)
            report_date: 报告日期
            trigger_type: 触发类型 (scheduled/manual)
            triggered_by: 触发者

        Returns:
            执行结果
        """
        if report_date is None:
            report_date = datetime.now()

        # 任务名称映射
        job_name_map = {
            'daily': '预测性维护日报',
            'weekly': '预测性维护周报',
            'monthly': '预测性维护月报'
        }
        job_name = job_name_map.get(report_type, f'预测性维护{report_type}报告')

        logger.info(f"开始生成 {report_type} 报告，日期: {report_date.date()}")

        # 计算时间范围
        period_start, period_end = self.data_aggregator.get_period(report_type, report_date)

        # 创建任务记录
        if not self.db.connect():
            logger.error("数据库连接失败")
            return {"status": "failed", "error": "数据库连接失败"}

        # 在 analysis_job_run 表中记录任务（用于前端 Jobs 页面显示）
        analysis_job_run_id = self.db.start_job(job_name)

        job_id = self.db.create_report_job(
            job_type=report_type,
            report_date=report_date.strftime("%Y-%m-%d"),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            trigger_type=trigger_type,
            triggered_by=triggered_by
        )

        if not job_id:
            logger.error("创建任务记录失败")
            # 标记 analysis_job_run 失败
            if analysis_job_run_id:
                self.db.end_job(analysis_job_run_id, status='failed', error_message='创建任务记录失败')
            self.db.close()
            return {"status": "failed", "error": "创建任务记录失败"}

        # 获取设备列表
        devices = self.data_aggregator.get_all_devices()
        total = len(devices)

        self.db.update_report_job_progress(job_id, total_devices=total)
        self.db.close()

        logger.info(f"任务 {job_id} 开始，共 {total} 台设备")

        # 生成报告
        processed = 0
        failed = 0
        failed_devices = []

        for device in devices:
            try:
                await self.report_generator.generate_device_report(
                    device_id=device['id'],
                    report_type=report_type,
                    report_date=report_date
                )
                processed += 1
            except Exception as e:
                logger.error(f"设备 {device['id']} ({device.get('name', '')}) 报告生成失败: {e}")
                failed += 1
                failed_devices.append({
                    "device_id": device['id'],
                    "error": str(e)
                })

            # 更新进度
            if self.db.connect():
                self.db.update_report_job_progress(
                    job_id,
                    processed_devices=processed,
                    failed_devices=failed
                )
                self.db.close()

        # 生成车间汇总
        try:
            await self._generate_workshop_summaries(report_type, report_date)
        except Exception as e:
            logger.error(f"生成车间汇总失败: {e}")

        # 完成任务
        status = 'completed' if failed == 0 else 'completed_with_errors'
        error_details = {"failed_devices": failed_devices} if failed_devices else None

        if self.db.connect():
            self.db.complete_report_job(
                job_id,
                status=status,
                error_details=error_details
            )

            # 更新 analysis_job_run 表（用于前端 Jobs 页面显示）
            if analysis_job_run_id:
                job_status = 'completed' if failed == 0 else 'failed'
                result_summary = {
                    "total": total,
                    "success": processed,
                    "failed": failed,
                    "report_type": report_type,
                    "report_date": report_date.strftime("%Y-%m-%d")
                }
                error_msg = f"失败设备数: {failed}" if failed > 0 else None
                self.db.end_job(analysis_job_run_id, status=job_status, result_summary=result_summary, error_message=error_msg)

            self.db.close()

        result = {
            "status": status,
            "job_id": job_id,
            "total": total,
            "success": processed,
            "failed": failed
        }

        logger.info(f"任务 {job_id} 完成: {processed}/{total} 成功, {failed} 失败")

        return result

    async def _generate_workshop_summaries(
        self,
        report_type: str,
        report_date: datetime
    ):
        """生成车间汇总报告"""
        if not self.db.connect():
            return

        # 获取所有车间
        devices = self.data_aggregator.get_all_devices()
        workshops = {}
        for device in devices:
            ws_id = device.get("workshop_id")
            if ws_id and ws_id not in workshops:
                workshops[ws_id] = {
                    "id": ws_id,
                    "name": device.get("workshop_name")
                }

        for ws_id, workshop in workshops.items():
            try:
                # 查询该车间的设备报告
                reports = self.db.get_device_reports(
                    report_type=report_type,
                    start_date=report_date.strftime("%Y-%m-%d"),
                    end_date=report_date.strftime("%Y-%m-%d"),
                    limit=500
                )

                if reports.empty:
                    continue

                # 过滤当前车间
                ws_reports = reports[reports['workshop_id'] == ws_id] if 'workshop_id' in reports.columns else reports

                if ws_reports.empty:
                    continue

                # 计算汇总统计
                total_devices = len(ws_reports)
                avg_health = ws_reports['health_score'].mean() if 'health_score' in ws_reports.columns else None
                min_health = ws_reports['health_score'].min() if 'health_score' in ws_reports.columns else None
                max_health = ws_reports['health_score'].max() if 'health_score' in ws_reports.columns else None
                total_alarms = ws_reports['alarm_count'].sum() if 'alarm_count' in ws_reports.columns else 0

                # 健康分布
                devices_critical = 0
                devices_warning = 0
                devices_fair = 0
                devices_good = 0
                devices_excellent = 0

                if 'health_score' in ws_reports.columns:
                    for score in ws_reports['health_score'].dropna():
                        if score < 40:
                            devices_critical += 1
                        elif score < 60:
                            devices_warning += 1
                        elif score < 75:
                            devices_fair += 1
                        elif score < 90:
                            devices_good += 1
                        else:
                            devices_excellent += 1

                # Top 报警设备
                top_alarm_devices = []
                if 'alarm_count' in ws_reports.columns and 'device_name' in ws_reports.columns:
                    top_devices = ws_reports.nlargest(5, 'alarm_count')[['device_name', 'alarm_count']]
                    top_alarm_devices = top_devices.to_dict('records')

                # 保存汇总
                self.db.save_workshop_summary(
                    report_type=report_type,
                    report_date=report_date.strftime("%Y-%m-%d"),
                    summary_level='workshop',
                    workshop_id=ws_id,
                    workshop_name=workshop['name'],
                    total_devices=total_devices,
                    devices_reported=total_devices,
                    avg_health_score=float(avg_health) if avg_health else None,
                    min_health_score=float(min_health) if min_health else None,
                    max_health_score=float(max_health) if max_health else None,
                    devices_critical=devices_critical,
                    devices_warning=devices_warning,
                    devices_fair=devices_fair,
                    devices_good=devices_good,
                    devices_excellent=devices_excellent,
                    total_alarms=int(total_alarms),
                    top_alarm_devices=top_alarm_devices
                )

            except Exception as e:
                logger.error(f"生成车间 {ws_id} 汇总失败: {e}")
                continue

        self.db.close()

    def get_scheduled_jobs(self) -> List[dict]:
        """获取已调度的任务列表"""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger)
            })
        return jobs

    def pause_job(self, job_id: str):
        """暂停任务"""
        self.scheduler.pause_job(job_id)
        logger.info(f"任务 {job_id} 已暂停")

    def resume_job(self, job_id: str):
        """恢复任务"""
        self.scheduler.resume_job(job_id)
        logger.info(f"任务 {job_id} 已恢复")


# 全局调度器实例
_scheduler_instance = None


def get_scheduler() -> ReportScheduler:
    """获取调度器单例"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = ReportScheduler()
    return _scheduler_instance
