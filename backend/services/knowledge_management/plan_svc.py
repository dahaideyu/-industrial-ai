# cython: annotation_typing=False, infer_types=False, language_level=3
"""收集计划服务"""
import logging

from sqlalchemy.orm import Session, joinedload

from backend.core.knowledge_management.exceptions import (
    NotFoundError,
    ValidationError,
)
from backend.core.knowledge_management.models import (
    CollectionPlan,
    Document,
    DocumentVersion,
    PlanItem,
    RAGDocumentMap,
)

logger = logging.getLogger(__name__)


class PlanService:
    """收集计划管理：计划 CRUD、收集项 CRUD、笛卡尔积生成。"""

    # ------------------------------------------------------------------
    #  计划 CRUD
    # ------------------------------------------------------------------

    def create(self, db: Session, data: dict) -> CollectionPlan:
        """创建收集计划，自动生成笛卡尔积收集项。

        Args:
            db: 数据库会话。
            data: 包含 knowledge_base_id, name, description, category_ids, target_ids。

        Returns:
            新创建的 CollectionPlan 实例（含 plan_items）。

        Raises:
            ValidationError: category_ids 或 target_ids 为空，或存在跨知识库引用。
        """
        category_ids: list[str] = data.pop("category_ids", [])
        target_ids: list[str] = data.pop("target_ids", [])
        plan_type = data.get("plan_type", "device_doc")
        is_custom = data.get("is_custom", False)

        # 自定义计划允许不选择类别和对象
        if plan_type != "custom" and not is_custom:
            if not category_ids:
                raise ValidationError("至少选择一个文档类别")
            if not target_ids:
                raise ValidationError("至少选择一个收集对象")
        # 如果 is_custom 为 True，自动设置 plan_type 为 custom
        if is_custom and plan_type == "device_doc":
            data["plan_type"] = "custom"

        # 校验 category 和 target 归属同一知识库（仅在有选择时校验）
        kb_id = data["knowledge_base_id"]
        from backend.core.knowledge_management.models import (
            DocumentCategory,
            CollectionTarget,
        )

        if category_ids:
            valid_cat_ids = {
                c.id
                for c in db.query(DocumentCategory)
                .filter(
                    DocumentCategory.knowledge_base_id == kb_id,
                    DocumentCategory.id.in_(category_ids),
                )
                .all()
            }
            if valid_cat_ids != set(category_ids):
                raise ValidationError("部分文档类别不属于该知识库")

        if target_ids:
            valid_target_ids = {
                t.id
                for t in db.query(CollectionTarget)
                .filter(
                    CollectionTarget.knowledge_base_id == kb_id,
                    CollectionTarget.id.in_(target_ids),
                )
                .all()
            }
            if valid_target_ids != set(target_ids):
                raise ValidationError("部分收集对象不属于该知识库")

        plan = CollectionPlan(**data)
        db.add(plan)
        db.flush()

        # 生成笛卡尔积 plan_items
        item_count = 0
        for cat_id in category_ids:
            for target_id in target_ids:
                item = PlanItem(
                    plan_id=plan.id,
                    category_id=cat_id,
                    target_id=target_id,
                )
                db.add(item)
                item_count += 1

        # 初始化计划级统计（所有收集项默认为 missing）
        plan.overall_progress = 0
        plan.overall_stats = {
            "completed": 0,
            "improving": 0,
            "missing": item_count,
            "overdue": 0,
        }

        db.commit()
        db.refresh(plan)
        return plan

    def list(self, db: Session, kb_id: str) -> list[CollectionPlan]:
        """列出指定知识库下的所有收集计划，按创建时间降序。"""
        return (
            db.query(CollectionPlan)
            .options(
                joinedload(CollectionPlan.plan_items).joinedload(PlanItem.category),
                joinedload(CollectionPlan.plan_items).joinedload(PlanItem.target),
            )
            .filter(CollectionPlan.knowledge_base_id == kb_id)
            .order_by(CollectionPlan.created_at.desc())
            .all()
        )

    def get(self, db: Session, plan_id: str) -> CollectionPlan:
        """获取收集计划详情（含 plan_items 及其 category/target 关联）。

        Raises:
            NotFoundError: 计划不存在。
        """
        plan = (
            db.query(CollectionPlan)
            .options(
                joinedload(CollectionPlan.plan_items)
                .joinedload(PlanItem.category),
                joinedload(CollectionPlan.plan_items)
                .joinedload(PlanItem.target),
                joinedload(CollectionPlan.plan_items)
                .joinedload(PlanItem.documents)
                .joinedload(Document.versions)
                .joinedload(DocumentVersion.rag_mapping),
            )
            .filter(CollectionPlan.id == plan_id)
            .first()
        )
        if plan is None:
            raise NotFoundError(f"收集计划不存在: {plan_id}")
        return plan

    def update(self, db: Session, plan_id: str, data: dict) -> CollectionPlan:
        """更新收集计划字段。

        Args:
            db: 数据库会话。
            plan_id: 计划 ID。
            data: 需要更新的字段字典。

        Returns:
            更新后的 CollectionPlan 实例。
        """
        plan = db.get(CollectionPlan, plan_id)
        if plan is None:
            raise NotFoundError(f"收集计划不存在: {plan_id}")
        for key, value in data.items():
            if hasattr(plan, key):
                setattr(plan, key, value)
        db.commit()
        db.refresh(plan)
        return plan

    def delete(self, db: Session, plan_id: str):
        """删除收集计划，CASCADE 删除所有收集项和关联文档。

        删除前清理 MinIO 文件和 RAGFlow 映射。

        Raises:
            ValidationError: 自动生成的收集计划不允许删除。
        """
        plan = db.get(CollectionPlan, plan_id)
        if plan is None:
            raise NotFoundError(f"收集计划不存在: {plan_id}")

        if plan.sync_type == 'auto':
            raise ValidationError(
                f"自动生成的收集计划「{plan.name}」不允许删除（由设备类型同步自动创建）"
            )

        # 级联清理：收集项 → 文档 → 版本 → MinIO + RAGFlow 映射
        from backend.clients.knowledge_management.minio_client import MinIOClient
        minio = MinIOClient()

        for item in plan.plan_items:
            for doc in item.documents:
                for version in doc.versions:
                    self._cleanup_version_files(version, minio)

        db.delete(plan)
        db.commit()

    # ------------------------------------------------------------------
    #  收集项管理
    # ------------------------------------------------------------------

    def create_plan_item(self, db: Session, data: dict) -> PlanItem:
        """新增单个收集项。

        校验 category 和 target 归属于同一知识库（通过 plan 查找），
        并检查唯一约束（同一 plan 下 category + target 不可重复）。
        """
        plan_id = data.pop("plan_id", None)
        if not plan_id:
            raise ValidationError("缺少 plan_id")

        plan = db.get(CollectionPlan, plan_id)
        if plan is None:
            raise NotFoundError(f"收集计划不存在: {plan_id}")

        category_id = data.get("category_id")
        target_id = data.get("target_id")

        # 自定义计划项允许无 category/target，但必须有 name
        is_custom = data.get("is_custom", False) or data.get("plan_type") == "custom"
        plan_is_custom = plan.plan_type == "custom" if hasattr(plan, 'plan_type') else False

        if is_custom or plan_is_custom:
            # 自定义收集项：允许只传 name 和 plan_id
            if not data.get("name"):
                raise ValidationError("自定义收集项必须提供 name")
        else:
            if not category_id or not target_id:
                raise ValidationError("category_id 和 target_id 为必填")

        # 校验 category / target 属于该知识库（仅非自定义时需要）
        if not is_custom and not plan_is_custom:
            from backend.core.knowledge_management.models import (
                DocumentCategory,
                CollectionTarget,
            )
            cat = db.get(DocumentCategory, category_id)
            if cat is None or cat.knowledge_base_id != plan.knowledge_base_id:
                raise ValidationError("文档类别不属于该知识库")
            tgt = db.get(CollectionTarget, target_id)
            if tgt is None or tgt.knowledge_base_id != plan.knowledge_base_id:
                raise ValidationError("收集对象不属于该知识库")

            # 唯一约束检查
            existing = (
                db.query(PlanItem)
                .filter(
                    PlanItem.plan_id == plan_id,
                    PlanItem.category_id == category_id,
                    PlanItem.target_id == target_id,
                )
                .first()
            )
            if existing:
                raise ValidationError("该类别×对象组合已存在")

        item = PlanItem(plan_id=plan_id, **data)
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def update_plan_item(
        self, db: Session, item_id: str, data: dict
    ) -> PlanItem:
        """更新收集项的可编辑字段。

        Args:
            db: 数据库会话。
            item_id: 收集项 ID。
            data: 包含 requirement_override, priority, due_date 等字段。

        Returns:
            更新后的 PlanItem 实例。
        """
        item = db.get(PlanItem, item_id)
        if item is None:
            raise NotFoundError(f"收集项不存在: {item_id}")

        allowed_fields = {"requirement_override", "priority", "due_date"}
        for key, value in data.items():
            if key in allowed_fields and hasattr(item, key):
                setattr(item, key, value)

        db.commit()
        db.refresh(item)
        return item

    def delete_plan_item(self, db: Session, item_id: str):
        """删除收集项，级联删除关联文档和 MinIO 文件。"""
        item = db.get(PlanItem, item_id)
        if item is None:
            raise NotFoundError(f"收集项不存在: {item_id}")

        # 清理关联文档的外部资源
        from backend.clients.knowledge_management.minio_client import MinIOClient
        minio = MinIOClient()

        for doc in item.documents:
            for version in doc.versions:
                self._cleanup_version_files(version, minio)

        db.delete(item)
        db.commit()

    # ------------------------------------------------------------------
    #  内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_version_files(
        version: DocumentVersion, minio: "MinIOClient"
    ):
        """清理单个版本的 MinIO 文件。

        RAGFlow 文档删除在 ragflow_sync_svc 中处理，此处仅清理本地资源。

        Args:
            version: 文档版本实例。
            minio: MinIO 客户端实例（复用，避免重复创建）。
        """
        # 删除 MinIO 文件
        if version.storage_path:
            try:
                minio.delete_file(version.storage_path)
            except Exception:
                logger.warning("删除 MinIO 文件失败: %s", version.storage_path)

        if version.pdf_preview_path:
            try:
                minio.delete_file(version.pdf_preview_path)
            except Exception:
                logger.warning("删除 MinIO 预览文件失败: %s", version.pdf_preview_path)


# 模块级单例
plan_svc = PlanService()
