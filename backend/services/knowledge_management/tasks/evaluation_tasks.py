# cython: annotation_typing=False, infer_types=False, language_level=3
"""评估任务：收集项综合评估 + 计划进度更新"""
import logging

from backend.services.knowledge_management.tasks.celery_app import kb_celery
from backend.core.knowledge_management.database import SessionLocal

logger = logging.getLogger(__name__)


@kb_celery.task(bind=True, queue="kb_eval")
def evaluate_plan_item_task(self, item_id: str):
    """收集项综合评估任务。

    调用 evaluation_svc.evaluate_plan_item 汇总已审批文档的评分，
    调用 DeepSeek 生成综合评估，并自动更新计划进度。

    Args:
        item_id: 收集项 ID。
    """
    db = SessionLocal()
    try:
        from backend.services.knowledge_management.evaluation_svc import evaluation_svc

        evaluation_svc.evaluate_plan_item(db, item_id)
        logger.info("收集项评估完成: item_id=%s", item_id)

    except Exception as exc:
        logger.exception("收集项评估失败: item_id=%s", item_id)
        raise self.retry(exc=exc)
    finally:
        db.close()


@kb_celery.task(bind=True, queue="kb_eval")
def update_plan_progress_task(self, plan_id: str):
    """计划进度更新任务。

    调用 evaluation_svc.update_plan_progress 统计各收集项状态，
    计算整体进度百分比，生成整体分析说明。

    Args:
        plan_id: 计划 ID。
    """
    db = SessionLocal()
    try:
        from backend.services.knowledge_management.evaluation_svc import evaluation_svc

        evaluation_svc.update_plan_progress(db, plan_id)
        logger.info("计划进度更新完成: plan_id=%s", plan_id)

    except Exception as exc:
        logger.exception("计划进度更新失败: plan_id=%s", plan_id)
        raise self.retry(exc=exc)
    finally:
        db.close()
