# cython: annotation_typing=False, infer_types=False, language_level=3
"""文档服务：文件上传、版本管理、文件类型设置"""
import hashlib
import logging
import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from backend.clients.knowledge_management.minio_client import MinIOClient
from backend.core.knowledge_management.exceptions import NotFoundError, ValidationError
from backend.core.knowledge_management.models import Document, DocumentVersion, PlanItem
from services.knowledge_management.operation_log_svc import oplog_svc

logger = logging.getLogger(__name__)

# 文件类型 → chunk_method 映射
FILE_TYPE_CHUNK_MAP = {
    "general": "naive",
    "table": "table",
    "image": "picture",
    "manual": "manual",
    "plc": "naive",
}

# 扩展名 → 默认文件类型映射
_EXT_FILE_TYPE_MAP = {
    # 文档类 → general
    ".pdf": "general",
    ".doc": "general",
    ".docx": "general",
    ".txt": "general",
    ".rtf": "general",
    # 表格类 → table
    ".xls": "table",
    ".xlsx": "table",
    ".csv": "table",
    # 图片类 → image
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".bmp": "image",
    ".tiff": "image",
}

# 不支持的 PLC 源码文件格式（上传时自动跳过）
_UNSUPPORTED_PLC_EXTENSIONS = {
    ".awl",   # 西门子 AWL（语句表）
    ".stl",   # 西门子 STL（语句表）
    ".scl",   # 西门子 SCL（结构化控制语言）
    ".db",    # 数据块文件
    ".gxw",   # 三菱
    ".gpp",   # 三菱
    ".cxp",   # 欧姆龙
    ".cx5",   # 欧姆龙
}


class DocumentService:
    """文档上传与版本管理。"""

    def __init__(self):
        self._minio = MinIOClient()

    def upload_files(
        self,
        db: Session,
        plan_item_id: str,
        files: list,
        uploaded_by: str = "",
        document_id: str = None,
        force_ocr: bool = False,
        file_type: str = None,
    ) -> list[Document]:
        """上传文件到收集项，创建 Document + DocumentVersion。

        如果提供 document_id，则在已有文档下创建新版本（更新场景），
        否则创建新文档（首次上传场景）。

        更新场景下：
        - 新版本 is_current=False，保留旧版本 is_current 不变
        - 如果旧版本已发布，其 publish_status 保持不变，新版本走审核流程

        Args:
            db: 数据库会话。
            plan_item_id: 收集项 ID。
            files: 文件列表。
            uploaded_by: 上传人用户名。
            document_id: 可选，已有文档 ID（更新场景）。
            force_ocr: 是否强制 OCR。
            file_type: 可选，前端指定的文件类型（general/table/image/manual/plc）。

        Returns:
            新创建的 Document 列表（含 versions 关系）。
        """
        plan_item = db.get(PlanItem, plan_item_id)
        if plan_item is None:
            raise NotFoundError(f"收集项不存在: {plan_item_id}")

        # 更新场景：查找已有文档
        existing_doc = None
        if document_id:
            existing_doc = db.get(Document, document_id)
            if existing_doc is None or existing_doc.plan_item_id != plan_item_id:
                raise ValidationError("文档不存在或不属于该收集项")

        temp_dir = tempfile.mkdtemp(prefix="knb_upload_")
        created_docs: list[Document] = []
        skipped_files: list[str] = []

        try:
            for file_obj in files:
                filename = getattr(file_obj, "filename", None) or getattr(
                    file_obj, "name", "unknown"
                )

                # 检查是否为不支持的 PLC 源码格式
                ext = Path(filename).suffix.lower()
                if ext in _UNSUPPORTED_PLC_EXTENSIONS:
                    skipped_files.append(filename)
                    logger.info("跳过不支持的 PLC 源码文件: %s", filename)
                    continue

                # 1. 写入临时文件
                temp_path = os.path.join(temp_dir, filename)
                with open(temp_path, "wb") as f:
                    content = (
                        file_obj.file.read()
                        if hasattr(file_obj, "file")
                        else file_obj.read()
                    )
                    f.write(content)

                # 2. 计算哈希
                file_hash = self._compute_hash(temp_path)
                file_size = os.path.getsize(temp_path)

                # 3. 推断文件类型（优先使用前端指定的类型）
                if file_type and file_type in FILE_TYPE_CHUNK_MAP:
                    # 前端指定了有效的文件类型
                    current_file_type = file_type
                else:
                    # 根据扩展名推断
                    current_file_type = _EXT_FILE_TYPE_MAP.get(ext, "general")
                chunk_method = FILE_TYPE_CHUNK_MAP.get(current_file_type, "naive")

                # 4. 上传 MinIO
                storage_path = f"documents/{uuid.uuid4().hex}/{filename}"
                self._minio.upload_file(storage_path, temp_path)

                # 5. 创建数据库记录
                if existing_doc:
                    # 更新场景：在已有文档下创建新版本
                    doc = existing_doc
                    version_label = self._next_version_label(db, doc.id)
                    is_current = False  # 更新不抢占当前版本，发布后才切换
                else:
                    # 新建场景：创建文档+首版
                    doc = Document(
                        plan_item_id=plan_item_id,
                        display_name=filename,
                    )
                    db.add(doc)
                    db.flush()
                    version_label = "V1.0"
                    is_current = True

                version = DocumentVersion(
                    document_id=doc.id,
                    version_label=version_label,
                    original_filename=filename,
                    storage_path=storage_path,
                    file_size=file_size,
                    file_hash=file_hash,
                    status="pending",
                    file_type=current_file_type,
                    chunk_method=chunk_method,
                    is_current=is_current,
                    uploaded_by=uploaded_by,
                )
                db.add(version)
                db.flush()

                created_docs.append((doc, version, current_file_type))
        finally:
            # 清理临时文件
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)

        # 如果所有文件都被跳过，抛出异常
        if not created_docs and skipped_files:
            raise ValidationError(
                f"不支持的文件格式: {', '.join(skipped_files)}。"
                f"PLC 源码文件（.awl/.scl/.stl/.gxw 等）不支持上传，请上传 PLC 图纸 PDF 文件。"
            )

        # 记录操作日志
        for doc, version, _ in created_docs:
            kb_id = plan_item.plan.knowledge_base_id if plan_item.plan else None
            oplog_svc.log(db, username=uploaded_by or "system", operation="doc_upload",
                          target_type="document", target_id=doc.id,
                          target_name=version.original_filename, kb_id=kb_id)
        db.commit()

        # 重新加载以获取完整关系，并触发后台任务
        result = []
        for doc, version, doc_file_type in created_docs:
            db.refresh(doc)
            result.append(doc)
            # 异步触发 LibreOffice 转 PDF、文本提取（+ PLC 解析）
            self._dispatch_background_tasks(version.id, doc_file_type, force_ocr=force_ocr)

        # 记录跳过的文件
        if skipped_files:
            logger.warning("跳过不支持的文件: %s", skipped_files)

        # 合规性知识库：异步触发视觉检测（公章、签名、有效期）
        self._trigger_compliance_vision_if_needed(db, result)

        return result

    @staticmethod
    def _trigger_compliance_vision_if_needed(db, created_docs):
        """如果属于合规性知识库，触发视觉检测。"""
        for doc in created_docs:
            try:
                plan_item = doc.plan_item
                if not plan_item or not plan_item.plan:
                    continue
                kb = plan_item.plan.knowledge_base
                if kb and kb.kb_type == 'compliance':
                    # 获取最新版本
                    versions = sorted(doc.versions, key=lambda v: v.created_at or '', reverse=True)
                    if versions:
                        from backend.services.knowledge_management.tasks.compliance_vision_tasks import (
                            compliance_vision_detect,
                        )
                        compliance_vision_detect.delay(versions[0].id)
                        logger.info("已调度合规性视觉检测: version_id=%s", versions[0].id)
            except Exception as e:
                logger.warning("调度合规性视觉检测失败: %s", e)

    @staticmethod
    def _dispatch_background_tasks(version_id: str, file_type: str = "general", force_ocr: bool = False):
        """异步调度后台任务：文本提取（+ 非 PDF 转 PDF + PLC 解析）。"""
        try:
            from backend.services.knowledge_management.tasks.extract_tasks import (
                extract_text,
            )

            extract_text.delay(version_id, force_ocr=force_ocr)

            # 获取文件扩展名
            from backend.core.knowledge_management.database import SessionLocal
            from backend.core.knowledge_management.models import DocumentVersion
            db = SessionLocal()
            try:
                version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
                ext = ""
                if version and version.original_filename:
                    ext = version.original_filename.rsplit(".", 1)[-1].lower() if "." in version.original_filename else ""

                # Excel/Word/PPT/Markdown 分别转为 HTML 或 PDF，其他直接复用原文件
                excel_exts = {"xls", "xlsx", "xlsm"}
                word_ppt_exts = {"doc", "docx", "ppt", "pptx"}
                md_exts = {"md", "markdown"}
                if ext in excel_exts:
                    from backend.services.knowledge_management.tasks.convert_tasks import convert_excel_to_html
                    convert_excel_to_html.delay(version_id)
                elif ext in word_ppt_exts:
                    from backend.services.knowledge_management.tasks.convert_tasks import convert_to_pdf
                    convert_to_pdf.delay(version_id)
                elif ext in md_exts:
                    from backend.services.knowledge_management.tasks.convert_tasks import convert_md_to_html
                    convert_md_to_html.delay(version_id)
                else:
                    version.pdf_preview_path = version.storage_path
                    db.commit()
                    logger.info("跳过转换: version_id=%s, ext=%s", version_id, ext)

                # PLC 图纸文件（仅 PDF 格式）额外触发解析任务
                # 注意：仅支持 PDF 格式的 PLC 图纸，不支持 .awl/.scl/.stl 等源码文件
                if file_type == "plc" and ext == "pdf":
                    from backend.services.knowledge_management.tasks.plc_tasks import (
                        parse_plc_task,
                    )
                    parse_plc_task.delay(version_id)
                    logger.info("已调度 PLC 图纸解析任务: version_id=%s", version_id)
                elif file_type == "plc":
                    logger.info("PLC 文件非 PDF 格式，跳过 PLC 解析: version_id=%s, ext=%s", version_id, ext)

            finally:
                db.close()

            logger.info("已调度后台任务: version_id=%s, type=%s", version_id, file_type)
        except Exception as e:
            logger.warning("调度后台任务失败（Celery 可能未启动）: %s", e)

    def set_file_type(
        self, db: Session, version_id: str, file_type: str
    ) -> DocumentVersion:
        """更新文件类型及对应的 chunk_method。

        Args:
            db: 数据库会话。
            version_id: 版本 ID。
            file_type: 文件类型（general/table/image/manual/plc）。

        Returns:
            更新后的 DocumentVersion 实例。
        """
        if file_type not in FILE_TYPE_CHUNK_MAP:
            raise ValidationError(
                f"不支持的文件类型: {file_type}，可选: {list(FILE_TYPE_CHUNK_MAP.keys())}"
            )

        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        version.file_type = file_type
        version.chunk_method = FILE_TYPE_CHUNK_MAP[file_type]
        db.commit()
        db.refresh(version)
        return version

    def get_versions(self, db: Session, document_id: str) -> list[DocumentVersion]:
        """获取文档的所有版本，按创建时间降序。

        Args:
            db: 数据库会话。
            document_id: 文档 ID。

        Returns:
            DocumentVersion 列表。

        Raises:
            NotFoundError: 文档不存在。
        """
        doc = db.get(Document, document_id)
        if doc is None:
            raise NotFoundError(f"文档不存在: {document_id}")

        return (
            db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.created_at.desc())
            .all()
        )

    def delete_version(self, db: Session, version_id: str):
        """删除单个文档版本。

        - 已发布版本：清理 RAGFlow → 回滚到上一个版本（设为 current）
        - 未发布版本：直接删除（文档至少保留一个版本）
        - 如果文档没有其他版本，删除整个文档
        """
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        doc = version.document
        all_versions = sorted(doc.versions, key=lambda v: v.created_at or "", reverse=True)
        other_versions = [v for v in all_versions if v.id != version_id]

        # 已发布版本：清理 RAGFlow + MinIO，回滚到上一个版本
        if version.publish_status == "published":
            # 清理 RAGFlow（直接调 API + 删映射，避免嵌套 commit）
            if version.rag_mapping:
                try:
                    from backend.clients.knowledge_management.ragflow_client import (
                        KnowledgeRAGFlowClient,
                    )
                    ragflow = KnowledgeRAGFlowClient()
                    # 查知识库的 dataset_id
                    kb = doc.plan_item.plan.knowledge_base if doc.plan_item and doc.plan_item.plan else None
                    if kb and kb.rag_dataset_id:
                        ragflow.delete_document(kb.rag_dataset_id, version.rag_mapping.rag_document_id)
                except Exception:
                    logger.warning("清理 RAGFlow 文档失败: version_id=%s", version_id)
                db.delete(version.rag_mapping)

            # 清理 MinIO
            if version.storage_path:
                try:
                    self._minio.delete_file(version.storage_path)
                except Exception:
                    logger.warning("删除 MinIO 文件失败: %s", version.storage_path)
            if version.pdf_preview_path and version.pdf_preview_path != version.storage_path:
                try:
                    self._minio.delete_file(version.pdf_preview_path)
                except Exception:
                    logger.warning("删除 MinIO 预览失败: %s", version.pdf_preview_path)

            # 回滚：设置上一个版本为当前版本
            if other_versions:
                prev = other_versions[0]  # 最新版本（按时间降序）
                prev.is_current = True
                prev.publish_status = "published"  # 恢复发布状态
                logger.info("回滚到版本: version_id=%s → prev=%s", version_id, prev.id)

            db.delete(version)

            # 如果没有其他版本，也删除文档
            if not other_versions:
                db.delete(doc)

            db.commit()
            return

        # 未发布版本：如果只有一个版本，删除整个文档
        if len(all_versions) <= 1:
            # 清理 MinIO
            if version.storage_path:
                try:
                    self._minio.delete_file(version.storage_path)
                except Exception:
                    logger.warning("删除 MinIO 文件失败: %s", version.storage_path)
            if version.pdf_preview_path and version.pdf_preview_path != version.storage_path:
                try:
                    self._minio.delete_file(version.pdf_preview_path)
                except Exception:
                    logger.warning("删除 MinIO 预览失败: %s", version.pdf_preview_path)
            db.delete(version)
            db.delete(doc)
            db.commit()
            return

        # 清理 MinIO
        if version.storage_path:
            try:
                self._minio.delete_file(version.storage_path)
            except Exception:
                logger.warning("删除 MinIO 文件失败: %s", version.storage_path)
        if version.pdf_preview_path and version.pdf_preview_path != version.storage_path:
            try:
                self._minio.delete_file(version.pdf_preview_path)
            except Exception:
                logger.warning("删除 MinIO 预览失败: %s", version.pdf_preview_path)

        db.delete(version)
        db.commit()

    def get_version_progress(self, db: Session, version_id: str) -> dict:
        """获取版本的后台任务进度。

        Args:
            db: 数据库会话。
            version_id: 版本 ID。

        Returns:
            包含 convert_status, extract_status, status 的字典。
        """
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        return {
            "convert_status": version.convert_status,
            "extract_status": version.extract_status,
            "status": version.status,
        }

    def delete_document(self, db: Session, document_id: str):
        """删除文档，清理外部资源后一并提交。

        删除顺序：
        1. 清理 RAGFlow 远程文档（仅调 API，不 commit）
        2. 清理 MinIO 文件
        3. 删除数据库记录（CASCADE 处理版本和映射）
        4. 统一 commit
        """
        doc = db.get(Document, document_id)
        if doc is None:
            raise NotFoundError(f"文档不存在: {document_id}")

        # 收集需要清理的 RAGFlow 映射（先收集，再统一处理，避免嵌套 commit）
        published_mappings = []
        for version in doc.versions:
            if version.publish_status == "published" and version.rag_mapping:
                published_mappings.append((version, version.rag_mapping))

        # 清理 RAGFlow 远程文档（仅调 API + 删映射记录，内部不 commit）
        for version, rag_map in published_mappings:
            try:
                from backend.clients.knowledge_management.ragflow_client import (
                    KnowledgeRAGFlowClient,
                )
                ragflow = KnowledgeRAGFlowClient()
                kb = doc.plan_item.plan.knowledge_base if doc.plan_item and doc.plan_item.plan else None
                if kb and kb.rag_dataset_id:
                    try:
                        ragflow.delete_document(kb.rag_dataset_id, rag_map.rag_document_id)
                    except Exception:
                        logger.warning("清理 RAGFlow 文档失败: rag_doc_id=%s", rag_map.rag_document_id)
            except Exception:
                logger.warning("清理 RAGFlow 映射失败: version_id=%s", version.id)

        # 清理 MinIO 文件
        for version in doc.versions:
            if version.storage_path:
                try:
                    self._minio.delete_file(version.storage_path)
                except Exception:
                    logger.warning("删除 MinIO 文件失败: %s", version.storage_path)
            if version.pdf_preview_path and version.pdf_preview_path != version.storage_path:
                try:
                    self._minio.delete_file(version.pdf_preview_path)
                except Exception:
                    logger.warning("删除 MinIO 预览失败: %s", version.pdf_preview_path)

        # 统一删除（CASCADE 自动处理版本和映射）
        db.delete(doc)
        db.commit()

    # ------------------------------------------------------------------
    #  内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _next_version_label(db: Session, document_id: str) -> str:
        """生成下一版本号。"""
        versions = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == document_id)
            .all()
        )
        if not versions:
            return "V1.0"
        nums = []
        for v in versions:
            if v.version_label and v.version_label.startswith("V"):
                try:
                    nums.append(int(v.version_label[1:].split(".")[0]))
                except ValueError:
                    pass
        return f"V{max(nums) + 1}.0" if nums else f"V{len(versions) + 1}.0"

    @staticmethod
    def _compute_hash(file_path: str) -> str:
        """计算文件 SHA256 哈希。"""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()


# 模块级单例
document_svc = DocumentService()
