# cython: annotation_typing=False, infer_types=False, language_level=3
"""RAGFlow 同步服务：发布文档到 RAGFlow、构建元数据、清理映射"""
import logging
import os
import tempfile

from sqlalchemy.orm import Session

from backend.clients.knowledge_management.minio_client import MinIOClient
from backend.clients.knowledge_management.ragflow_client import KnowledgeRAGFlowClient
from backend.core.knowledge_management.exceptions import (
    NotFoundError,
    RAGFlowError,
    ValidationError,
)
from backend.core.knowledge_management.models import (
    CollectionPlan,
    CollectionTarget,
    DocumentCategory,
    DocumentVersion,
    PlanItem,
    RAGDocumentMap,
)

logger = logging.getLogger(__name__)


class RAGFlowSyncService:
    """RAGFlow 文档同步：上传、更新配置、删除。"""

    def __init__(self):
        self._ragflow = KnowledgeRAGFlowClient()
        self._minio = MinIOClient()

    def publish_to_ragflow(self, db: Session, version_id: str):
        """将审批通过的文档发布到 RAGFlow。

        流程：
        0. 查找旧版本：同一 Document 下 publish_status='published' 且 is_current=True
        1. 删旧映射：查 rag_document_map，调 RAGFlow delete（清理当前版本已有的旧映射）
        2. 上传：从 MinIO 下载文件 → 调 RAGFlow upload → 获取 rag_document_id
        3. 记录映射：写入 knb_rag_document_map
        4. 更新配置：调 RAGFlow update_document
        5. 触发解析：调 RAGFlow run_parse，设置 parse_status='running'
        6. 下线旧版本：删除旧 RAGFlow 文档 + 更新数据库
        7. 新版本切换为 current + 完成发布
        8. 触发收集项评估

        Args:
            db: 数据库会话。
            version_id: 版本 ID。

        Raises:
            NotFoundError: 版本或关联资源不存在。
            ValidationError: 知识库未关联 RAGFlow 数据集。
            RAGFlowError: RAGFlow 操作失败。
        """
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        # 设置发布中状态
        version.publish_status = "publishing"
        db.commit()

        doc = version.document
        plan_item = doc.plan_item
        category = plan_item.category
        target = plan_item.target
        plan = plan_item.plan
        kb = plan.knowledge_base

        if not kb.rag_dataset_id:
            raise ValidationError("知识库未关联 RAGFlow 数据集")

        dataset_id = kb.rag_dataset_id
        temp_path = None

        # 0. 查找需要被替换的旧版本（同一 Document 下已发布的当前版本）
        old_version = (
            db.query(DocumentVersion)
            .filter(
                DocumentVersion.document_id == doc.id,
                DocumentVersion.publish_status == "published",
                DocumentVersion.is_current.is_(True),
                DocumentVersion.id != version_id,
            )
            .first()
        )

        try:
            # 1. 删旧：清理当前版本已有的 RAGFlow 映射
            existing_map = (
                db.query(RAGDocumentMap)
                .filter(RAGDocumentMap.version_id == version_id)
                .first()
            )
            if existing_map:
                rag_deleted = False
                try:
                    self._ragflow.delete_document(
                        dataset_id, existing_map.rag_document_id
                    )
                    rag_deleted = True
                except RAGFlowError:
                    logger.warning(
                        "删除旧 RAGFlow 文档失败，保留本地映射以便重试: rag_doc_id=%s",
                        existing_map.rag_document_id,
                    )
                if rag_deleted:
                    db.delete(existing_map)
                    db.flush()

            # 2. 上传：从 MinIO 下载 → 上传 RAGFlow
            temp_dir = tempfile.mkdtemp(prefix="knb_sync_")
            # 文件名带版本号，避免 RAGFlow 重名冲突
            if "." in (version.original_filename or ""):
                name_part, ext_part = version.original_filename.rsplit(".", 1)
                upload_filename = f"{name_part}_{version.version_label}.{ext_part}"
            else:
                upload_filename = f"{version.original_filename}_{version.version_label}"
            temp_path = os.path.join(temp_dir, upload_filename)
            self._minio.download_file(version.storage_path, temp_path)

            rag_document_id = self._ragflow.upload_document(
                dataset_id=dataset_id,
                file_path=temp_path,
                file_name=upload_filename,
            )

            # 3. 记录映射
            rag_map = RAGDocumentMap(
                version_id=version_id,
                rag_document_id=rag_document_id,
                rag_dataset_id=dataset_id,
                is_current=True,
            )
            db.add(rag_map)
            db.flush()

            # 4. 更新配置（失败不影响发布结果）
            try:
                requirement_desc = plan_item.requirement_override or category.requirement_desc
                meta_fields = self.build_meta_fields(
                    target=target, category=category, plan=plan,
                    plan_item=plan_item, requirement_desc=requirement_desc, version=version,
                )
                self._ragflow.update_document(
                    dataset_id=dataset_id, doc_id=rag_document_id,
                    name=upload_filename,
                    chunk_method=version.chunk_method or "naive",
                    meta_fields=meta_fields,
                )
            except Exception:
                logger.warning("RAGFlow 文档配置更新失败（文档已上传，不影响发布）", exc_info=True)

            # 5. 触发解析
            try:
                self._ragflow.run_parse(dataset_id=dataset_id, doc_ids=[rag_document_id])
                version.parse_status = "running"
                logger.info(
                    "已触发 RAGFlow 文档解析: version_id=%s, rag_doc_id=%s",
                    version_id, rag_document_id,
                )
            except Exception:
                logger.warning("RAGFlow 文档解析触发失败", exc_info=True)
                version.parse_status = "unstart"

            # 6. 上传成功 → 下线旧版本（删除 RAGFlow 文档 + 更新数据库）
            if old_version:
                if old_version.rag_mapping:
                    old_rag_deleted = False
                    try:
                        self._ragflow.delete_document(
                            dataset_id, old_version.rag_mapping.rag_document_id
                        )
                        old_rag_deleted = True
                        logger.info(
                            "已删除旧版本 RAGFlow 文档: old_version_id=%s, rag_doc_id=%s",
                            old_version.id, old_version.rag_mapping.rag_document_id,
                        )
                    except RAGFlowError:
                        logger.warning(
                            "删除旧版本 RAGFlow 文档失败，保留映射: old_version_id=%s", old_version.id
                        )
                    if old_rag_deleted:
                        db.delete(old_version.rag_mapping)
                old_version.publish_status = "replaced"
                old_version.is_current = False

            # 7. 新版本切换为 current + 完成发布
            version.is_current = True
            version.publish_status = "published"
            db.commit()

            # 8. 触发收集项评估
            try:
                from backend.services.knowledge_management.evaluation_svc import evaluation_svc
                evaluation_svc.check_auto_evaluate(db, plan_item.id)
            except Exception:
                logger.warning("发布后评估触发失败: plan_item_id=%s", plan_item.id, exc_info=True)

            logger.info(
                "文档已发布到 RAGFlow: version_id=%s, rag_doc_id=%s, replaced_old=%s",
                version_id, rag_document_id, old_version.id if old_version else None,
            )

        except Exception:
            db.rollback()
            version.publish_status = "failed"
            version.parse_status = None  # 重置解析状态，避免 running+failed 矛盾
            db.commit()
            raise
        finally:
            if temp_path and os.path.exists(temp_path):
                import shutil
                shutil.rmtree(os.path.dirname(temp_path), ignore_errors=True)

    @staticmethod
    def build_meta_fields(
        target: CollectionTarget,
        category: DocumentCategory,
        plan: CollectionPlan,
        plan_item: PlanItem,
        requirement_desc: str,
        version: DocumentVersion,
    ) -> dict:
        """构建 RAGFlow 元数据字段，泛化支持任意收集对象类型。

        元数据结构：
        - target.target_type: target.name（如 "设备": "冲网线"）
        - 每条属性拆成独立字段（如 "设备厂家": "东顺"）
        - 通用字段：文档类别、收集要求、收集计划、优先级、版本

        Args:
            target: 收集对象。
            category: 文档类别。
            plan: 收集计划。
            plan_item: 收集项。
            requirement_desc: 收集要求描述。
            version: 文档版本。

        Returns:
            元数据字段字典。
        """
        meta_fields: dict = {}

        # 对象类型标签：对象名称（泛化）
        meta_fields[target.target_type] = target.name

        # 每条属性拆成独立字段
        if target.attributes:
            for attr in target.attributes:
                if isinstance(attr, dict) and "label" in attr and "value" in attr:
                    meta_fields[attr["label"]] = attr["value"]

        # 通用字段
        meta_fields["文档类别"] = category.name
        meta_fields["收集要求"] = requirement_desc
        meta_fields["收集计划"] = plan.name
        meta_fields["优先级"] = plan_item.priority
        meta_fields["版本"] = version.version_label

        return meta_fields

    def delete_from_ragflow(self, db: Session, version_id: str):
        """清理 RAGFlow 文档和映射表记录。

        Args:
            db: 数据库会话。
            version_id: 版本 ID。
        """
        rag_map = (
            db.query(RAGDocumentMap)
            .filter(RAGDocumentMap.version_id == version_id)
            .first()
        )
        if rag_map is None:
            return

        # 获取 dataset_id 用于 RAGFlow 删除
        version = db.get(DocumentVersion, version_id)
        if version and version.document:
            plan_item = version.document.plan_item
            if plan_item and plan_item.plan:
                kb = plan_item.plan.knowledge_base
                if kb and kb.rag_dataset_id:
                    try:
                        self._ragflow.delete_document(
                            kb.rag_dataset_id, rag_map.rag_document_id
                        )
                    except RAGFlowError:
                        logger.warning(
                            "删除 RAGFlow 文档失败: rag_doc_id=%s",
                            rag_map.rag_document_id,
                        )

        # 更新发布状态
        if version:
            version.publish_status = None

        db.delete(rag_map)
        db.commit()


# 模块级单例
ragflow_sync_svc = RAGFlowSyncService()
