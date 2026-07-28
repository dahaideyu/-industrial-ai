# cython: annotation_typing=False, infer_types=False, language_level=3
"""图纸解析任务：解析 PLC/电气原理图等 PDF 图纸，生成分析报告文档

注意：仅支持 PDF 格式的图纸，不支持 .awl/.scl/.stl 等源码文件。
"""
import logging
import os
import tempfile
import uuid
import io

from backend.services.knowledge_management.tasks.celery_app import kb_celery
from backend.core.knowledge_management.database import SessionLocal
from backend.core.knowledge_management.models import Document, DocumentVersion
from backend.clients.knowledge_management.minio_client import minio_client

logger = logging.getLogger(__name__)


def _update_progress(db, version_id, status, progress, step, detail=None):
    """更新图纸解析进度。"""
    try:
        version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
        if version:
            version.drawing_parse_status = status
            version.drawing_parse_progress = progress
            version.drawing_parse_step = step
            if detail:
                version.drawing_parse_detail = detail
            db.commit()
            logger.info("图纸解析进度更新: version_id=%s, %s %d%% - %s", version_id, status, progress, step)
    except Exception as e:
        logger.warning("更新进度失败: %s", e)


@kb_celery.task(bind=True, queue="kb_plc", max_retries=3, default_retry_delay=60)
def parse_plc_task(self, version_id: str):
    """解析图纸 PDF，生成说明文档并上传到 MinIO。

    仅支持 PDF 格式的图纸（PLC梯形图、电气原理图、流程图等），
    不支持 .awl/.scl/.stl 等源码文件。

    流程：
    1. 从 MinIO 下载图纸 PDF 文件
    2. 调用 plc_parser_svc.parse_drawing_file 生成 Markdown 报告
    3. 将报告直接上传到 MinIO（不保存本地）
    4. 在同一收集项下创建新的 Document + DocumentVersion（auto_generated=True）

    Args:
        version_id: 图纸文档版本 ID。
    """
    db = SessionLocal()
    try:
        version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
        if not version:
            logger.warning("parse_plc_task: 版本不存在, version_id=%s", version_id)
            return

        # 检查是否已有说明文档（避免重复生成）
        existing_report = db.query(DocumentVersion).filter(
            DocumentVersion.parent_document_id == version.document_id,
            DocumentVersion.auto_generated == True,
        ).first()
        if existing_report:
            logger.info("parse_plc_task: 已有说明文档，跳过生成: version_id=%s, report_id=%s",
                       version_id, existing_report.id)
            return

        # 初始化进度
        _update_progress(db, version_id, "processing", 0, "准备开始解析...")

        # 下载图纸文件到临时目录
        _update_progress(db, version_id, "processing", 5, "下载图纸文件...")
        tmp_dir = tempfile.mkdtemp(prefix="knb_plc_")
        local_path = os.path.join(tmp_dir, version.original_filename)
        minio_client.download_file(version.storage_path, local_path)

        # 调用图纸解析服务（带进度回调）
        _update_progress(db, version_id, "processing", 10, "PDF预处理中...")
        from backend.services.knowledge_management.plc_parser_svc import plc_parser_svc

        def micro_progress_callback(current, total):
            """微观解析进度回调。"""
            # 微观解析占总进度的 20%-60%
            progress = 20 + int(40 * current / total) if total > 0 else 20
            _update_progress(db, version_id, "processing", progress,
                           f"逐页微观解析: 第{current}/{total}页")

        report_md = plc_parser_svc.parse_drawing_file(local_path, micro_progress_callback)
        _update_progress(db, version_id, "processing", 70, "宏观架构梳理中...")
        _update_progress(db, version_id, "processing", 80, "生成报告中...")

        # 上传报告到 MinIO（直接上传，不保存本地文件）
        _update_progress(db, version_id, "processing", 95, "上传报告...")
        report_filename = version.original_filename.rsplit(".", 1)[0] + "_说明文档.md"
        report_storage_path = f"documents/{uuid.uuid4().hex}/{report_filename}"

        # 将 Markdown 内容转为字节流上传
        report_bytes = report_md.encode("utf-8")
        minio_client.upload_fileobj(
            report_storage_path,
            io.BytesIO(report_bytes),
            len(report_bytes),
        )

        # 创建关联文档（在同一收集项下）
        doc = version.document
        plan_item_id = doc.plan_item_id

        new_doc = Document(
            plan_item_id=plan_item_id,
            display_name=report_filename,
        )
        db.add(new_doc)
        db.flush()

        new_version = DocumentVersion(
            document_id=new_doc.id,
            version_label="V1.0",
            original_filename=report_filename,
            storage_path=report_storage_path,
            file_size=len(report_bytes),
            status="pending",
            file_type="general",
            chunk_method="naive",
            extracted_text=report_md,
            is_current=True,
            auto_generated=True,
            parent_document_id=doc.id,
        )
        db.add(new_version)

        # 更新进度为完成
        _update_progress(db, version_id, "done", 100, "解析完成")
        db.commit()

        logger.info(
            "图纸解析完成: version_id=%s, new_doc_id=%s, report=%s",
            version_id, new_doc.id, report_filename,
        )

    except Exception as exc:
        logger.exception("图纸解析失败: version_id=%s", version_id)
        # 更新失败状态
        _update_progress(db, version_id, "failed", 0, f"解析失败: {str(exc)[:100]}")
        # 最后一次重试失败时，记录失败状态但不抛出异常
        if self.request.retries >= self.max_retries - 1:
            logger.error("图纸解析最终失败，已达到最大重试次数: version_id=%s", version_id)
            return
        raise self.retry(exc=exc)
    finally:
        db.close()


@kb_celery.task(bind=True, queue="kb_plc")
def update_child_documents(self, parent_version_id: str):
    """当父文档（图纸）更新时，重新生成说明文档。

    Args:
        parent_version_id: 父文档版本 ID。
    """
    db = SessionLocal()
    try:
        parent_version = db.query(DocumentVersion).filter(DocumentVersion.id == parent_version_id).first()
        if not parent_version:
            logger.warning("update_child_documents: 父版本不存在, version_id=%s", parent_version_id)
            return

        # 删除旧的自动生成的说明文档
        old_reports = db.query(DocumentVersion).filter(
            DocumentVersion.parent_document_id == parent_version.document_id,
            DocumentVersion.auto_generated == True,
        ).all()

        for old_report in old_reports:
            # 删除 MinIO 文件
            if old_report.storage_path:
                try:
                    minio_client.delete_file(old_report.storage_path)
                except Exception:
                    pass
            # 删除文档记录
            old_doc = old_report.document
            db.delete(old_report)
            if old_doc and not old_doc.versions:
                db.delete(old_doc)

        # 重置父文档的解析进度
        parent_version.drawing_parse_status = None
        parent_version.drawing_parse_progress = None
        parent_version.drawing_parse_step = None
        parent_version.drawing_parse_detail = None
        db.commit()

        # 重新触发解析任务
        parse_plc_task.delay(parent_version_id)
        logger.info("已触发说明文档重新生成: parent_version_id=%s", parent_version_id)

    except Exception as exc:
        logger.exception("更新说明文档失败: parent_version_id=%s", parent_version_id)
        raise
    finally:
        db.close()
