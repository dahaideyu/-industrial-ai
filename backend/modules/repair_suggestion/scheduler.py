# cython: annotation_typing=False, infer_types=False, language_level=3
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import Config
from services.ragflow_service import RAGFlowService

logger = logging.getLogger(__name__)


async def cleanup_sessions():
    """清理RAGFlow所有会话"""
    logger.info("开始执行定时任务：清理RAGFlow会话...")
    ragflow_service = RAGFlowService()

    # 清理历史维修工单助手的会话
    success, err = await ragflow_service.delete_all_sessions(Config.RAGFLOW_HISTORY_ASSISTANT_ID)
    if success:
        logger.info("历史维修工单助手会话清理成功")
    else:
        logger.error(f"历史维修工单助手会话清理失败: {err}")

    # 清理设备文档助手的会话
    success, err = await ragflow_service.delete_all_sessions(Config.RAGFLOW_DOC_ASSISTANT_ID)
    if success:
        logger.info("设备文档助手会话清理成功")
    else:
        logger.error(f"设备文档助手会话清理失败: {err}")

    logger.info("定时任务执行完成")


def setup_scheduler() -> AsyncIOScheduler:
    """设置并启动定时任务调度器"""
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    # 每天凌晨2点执行
    scheduler.add_job(
        cleanup_sessions,
        trigger=CronTrigger(hour=2, minute=0, second=0),
        id="cleanup_ragflow_sessions",
        name="清理RAGFlow会话",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("定时任务调度器已启动，每天凌晨2点清理RAGFlow会话")
    return scheduler
