# cython: annotation_typing=False, infer_types=False, language_level=3
"""文本提取任务：MarkItDown（含 OCR 扫描件支持）"""
import logging
import os
import tempfile

from backend.services.knowledge_management.tasks.celery_app import kb_celery
from backend.core.knowledge_management.database import SessionLocal
from backend.core.knowledge_management.models import DocumentVersion
from backend.clients.knowledge_management.minio_client import minio_client

logger = logging.getLogger(__name__)

# 大文件阈值：10MB
_LARGE_FILE_THRESHOLD = 10 * 1024 * 1024
# 大文件截取字符数
_LARGE_FILE_MAX_CHARS = 30000


@kb_celery.task(bind=True, queue="kb_extract")
def extract_text(self, version_id: str, force_ocr: bool = False):
    """从文档中提取纯文本内容（MarkItDown + 自动 OCR）。

    流程：
    1. 更新 extract_status 为 processing
    2. 从 MinIO 下载原文件到临时目录
    3. 调用 MarkItDown 提取文本（低文本量/乱码时自动触发 OCR）
    4. 写入 extracted_text 字段，更新 extract_status 为 done

    Args:
        version_id: 文档版本 ID。
        force_ocr: 强制启用 OCR（用于扫描件）。
    """
    db = SessionLocal()
    try:
        version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
        if not version:
            logger.warning("extract_text: 版本不存在, version_id=%s", version_id)
            return

        version.extract_status = "processing"
        db.commit()

        # 下载原文件到临时目录
        tmp_dir = tempfile.mkdtemp(prefix="knb_extract_")
        local_path = os.path.join(tmp_dir, version.original_filename)
        minio_client.download_file(version.storage_path, local_path)

        # 文本提取：MarkItDown（含自动 OCR）
        from backend.clients.knowledge_management.markitdown_client import markitdown_client
        text = markitdown_client.convert_with_ocr(local_path, force_ocr=force_ocr)
        logger.info("MarkItDown 提取完成: version_id=%s, len=%d", version_id, len(text))

        # 大文件截断
        if version.file_size and version.file_size > _LARGE_FILE_THRESHOLD:
            text = text[:_LARGE_FILE_MAX_CHARS]
            logger.info("大文件截断: version_id=%s, size=%d", version_id, version.file_size)

        version.extracted_text = text
        version.extract_status = "done"
        db.commit()

        logger.info("文本提取完成: version_id=%s, text_len=%d", version_id, len(text) if text else 0)

    except Exception as exc:
        logger.exception("文本提取失败: version_id=%s", version_id)
        try:
            version.extract_status = "failed"
            db.commit()
        except Exception:
            db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()
