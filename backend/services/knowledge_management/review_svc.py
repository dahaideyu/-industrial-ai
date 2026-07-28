# cython: annotation_typing=False, infer_types=False, language_level=3
"""AI 审核 + 人工审批服务"""
import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.knowledge_management.exceptions import NotFoundError, ValidationError
from backend.core.knowledge_management.models import (
    CollectionPlan,
    Document,
    DocumentVersion,
    KnowledgeBase,
    PlanItem,
)
from services.knowledge_management.operation_log_svc import oplog_svc

logger = logging.getLogger(__name__)


class ReviewService:
    """文档审核与审批：AI 审核触发、人工通过/驳回。"""

    def trigger_ai_review(self, db: Session, version_id: str):
        """触发 AI 审核：更新状态为 ai_processing，触发 Celery 任务。

        Args:
            db: 数据库会话。
            version_id: 版本 ID。

        Raises:
            NotFoundError: 版本不存在。
            ValidationError: 版本状态不允许触发 AI 审核。
        """
        from sqlalchemy.orm import joinedload

        version = (
            db.query(DocumentVersion)
            .options(
                joinedload(DocumentVersion.document)
                .joinedload(Document.plan_item)
                .joinedload(PlanItem.plan)
                .joinedload(CollectionPlan.knowledge_base),
            )
            .filter(DocumentVersion.id == version_id)
            .first()
        )
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        if version.status != "pending":
            raise ValidationError(
                f"当前状态 '{version.status}' 不允许触发 AI 审核，需要 'pending' 状态"
            )

        # 检查文本提取是否完成
        if not version.extracted_text:
            if version.extract_status == "processing":
                raise ValidationError("文本提取进行中，请稍后再试")
            if version.extract_status == "failed":
                raise ValidationError("文本提取失败，请重新上传")
            raise ValidationError("文本尚未提取完成，请等待后台处理完成后再试")

        # 合规性文档：必须填写有效期才能进行 AI 审核
        kb = None
        doc = version.document
        if doc and doc.plan_item and doc.plan_item.plan:
            kb = doc.plan_item.plan.knowledge_base
        if kb and kb.kb_type == 'compliance' and not version.valid_until:
            raise ValidationError(
                "合规性文档必须先填写有效期（valid_until）才能进行 AI 审核。"
                "请先在文档管理页面上传文档后手动设置有效期。"
            )

        version.status = "ai_processing"
        oplog_svc.log(db, username="system", operation="ai_review",
                      target_type="version", target_id=version_id,
                      target_name=version.version_label or "")
        db.commit()

        # 触发 Celery 异步任务（延迟导入避免循环依赖）
        try:
            from backend.services.knowledge_management.tasks.review_tasks import (
                ai_review_task,
            )

            ai_review_task.delay(version_id)
            logger.info("已触发 AI 审核任务: version_id=%s", version_id)
        except ImportError:
            logger.warning(
                "Celery 任务模块未就绪，AI 审核任务未触发: version_id=%s",
                version_id,
            )

    def approve(
        self, db: Session, version_id: str, username: str = ""
    ) -> DocumentVersion:
        """人工审批通过：生成版本号，更新状态为 approved。

        版本号规则：
        - 如果是该文档的第一个 approved 版本，生成 V1.0
        - 否则在最大版本号基础上递增（V1.0 → V1.1 → V1.2 ...）

        Args:
            db: 数据库会话。
            version_id: 版本 ID。
            username: 审批人用户名。

        Returns:
            更新后的 DocumentVersion 实例。
        """
        # 审批通过：生成版本号，更新状态为 approved。
        from sqlalchemy.orm import joinedload

        version = (
            db.query(DocumentVersion)
            .options(joinedload(DocumentVersion.document))
            .filter(DocumentVersion.id == version_id)
            .first()
        )
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        if version.status not in (
            "ai_completed_manual_pending",
            "rejected",
        ):
            raise ValidationError(
                f"当前状态 '{version.status}' 不允许审批，需要 "
                "'ai_completed_manual_pending' 或 'rejected' 状态"
            )

        version.status = "approved"
        # 版本号在上传时已生成（V1.0），审批不改变版本号
        version.is_current = True
        version.rejected_reason = None
        oplog_svc.log(db, username=username or "system", operation="approve",
                      target_type="version", target_id=version_id,
                      target_name=version.version_label or "")
        db.commit()
        db.refresh(version)

        # 自动触发收集项评估
        self._trigger_evaluation(version.document.plan_item_id)

        return version

    def reject(
        self, db: Session, version_id: str, reason: str
    ) -> DocumentVersion:
        """人工审批驳回：更新状态为 rejected，记录驳回原因。

        驳回后重新上传会创建新版本，走完整流程。

        Args:
            db: 数据库会话。
            version_id: 版本 ID。
            reason: 驳回原因。

        Returns:
            更新后的 DocumentVersion 实例。
        """
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise NotFoundError(f"文档版本不存在: {version_id}")

        if version.status != "ai_completed_manual_pending":
            raise ValidationError(
                f"当前状态 '{version.status}' 不允许驳回，需要 "
                "'ai_completed_manual_pending' 状态"
            )

        version.status = "rejected"
        version.rejected_reason = reason
        version.is_current = False
        oplog_svc.log(db, username="system", operation="reject",
                      target_type="version", target_id=version_id,
                      target_name=version.version_label or "",
                      remark=reason)
        db.commit()
        db.refresh(version)
        return version

    # ------------------------------------------------------------------
    #  内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _trigger_evaluation(plan_item_id: str):
        """审批通过后异步触发收集项综合评估。"""
        try:
            from backend.services.knowledge_management.tasks.evaluation_tasks import (
                evaluate_plan_item_task,
            )
            evaluate_plan_item_task.delay(plan_item_id)
        except Exception:
            logger.warning("调度评估任务失败（Celery 可能未启动）: plan_item_id=%s", plan_item_id, exc_info=True)

    @staticmethod
    def _next_version_label(db: Session, document_id: str) -> str:
        """生成下一个版本号。

        查找该文档已有的最大版本号，在此基础上递增。
        首个版本为 V1.0。
        """
        max_label = (
            db.query(func.max(DocumentVersion.version_label))
            .filter(
                DocumentVersion.document_id == document_id,
                DocumentVersion.version_label.isnot(None),
            )
            .scalar()
        )

        if max_label is None:
            return "V1.0"

        # 解析 "V1.2" → (1, 2)，递增小版本
        try:
            parts = max_label.lstrip("V").split(".")
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            return f"V{major}.{minor + 1}"
        except (ValueError, IndexError):
            # 版本号格式异常时回退到 V1.0
            return "V1.0"


# 模块级单例
review_svc = ReviewService()
