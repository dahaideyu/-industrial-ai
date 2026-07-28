# cython: annotation_typing=False, infer_types=False, language_level=3
"""RAGFlow 同步任务：将审批通过的文档发布到 RAGFlow"""
import logging

from backend.services.knowledge_management.tasks.celery_app import kb_celery
from backend.core.knowledge_management.database import SessionLocal

logger = logging.getLogger(__name__)


@kb_celery.task(bind=True, queue="kb_sync")
def publish_to_ragflow_task(self, version_id: str):
    """将审批通过的文档发布到 RAGFlow。

    调用 ragflow_sync_svc.publish_to_ragflow 完成：
    1. 清理旧的 RAGFlow 文档
    2. 从 MinIO 下载文件上传到 RAGFlow
    3. 记录映射关系
    4. 更新 chunk_method + parser_config + meta_fields
    5. 更新 publish_status 为 published

    Args:
        version_id: 文档版本 ID。
    """
    db = SessionLocal()
    try:
        from backend.services.knowledge_management.ragflow_sync_svc import ragflow_sync_svc

        ragflow_sync_svc.publish_to_ragflow(db, version_id)
        logger.info("RAGFlow 同步完成: version_id=%s", version_id)

    except Exception as exc:
        logger.exception("RAGFlow 同步失败: version_id=%s", version_id)
        raise self.retry(exc=exc)
    finally:
        db.close()
