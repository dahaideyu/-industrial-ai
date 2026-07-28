# cython: annotation_typing=False, infer_types=False, language_level=3
"""收集对象服务"""
from sqlalchemy.orm import Session

from backend.core.knowledge_management.exceptions import (
    NotFoundError,
    ValidationError,
)
from backend.core.knowledge_management.models import CollectionTarget, PlanItem


class TargetService:
    """收集对象 CRUD，删除前检查是否被收集项引用。"""

    def create(self, db: Session, kb_id: str, data: dict) -> CollectionTarget:
        """创建收集对象。

        Args:
            db: 数据库会话。
            kb_id: 所属知识库 ID。
            data: 包含 name, target_type, attributes 字段。

        Returns:
            新创建的 CollectionTarget 实例。
        """
        target = CollectionTarget(knowledge_base_id=kb_id, **data)
        db.add(target)
        db.commit()
        db.refresh(target)
        return target

    def list(self, db: Session, kb_id: str) -> list[CollectionTarget]:
        """列出指定知识库下的所有收集对象，按创建时间降序。"""
        return (
            db.query(CollectionTarget)
            .filter(CollectionTarget.knowledge_base_id == kb_id)
            .order_by(CollectionTarget.created_at.desc())
            .all()
        )

    def update(self, db: Session, target_id: str, data: dict) -> CollectionTarget:
        """更新收集对象字段。

        Args:
            db: 数据库会话。
            target_id: 收集对象 ID。
            data: 需要更新的字段字典。

        Returns:
            更新后的 CollectionTarget 实例。
        """
        target = db.get(CollectionTarget, target_id)
        if target is None:
            raise NotFoundError(f"收集对象不存在: {target_id}")
        for key, value in data.items():
            if hasattr(target, key):
                setattr(target, key, value)
        db.commit()
        db.refresh(target)
        return target

    def delete(self, db: Session, target_id: str):
        """删除收集对象，检查是否被收集项引用。

        Raises:
            NotFoundError: 收集对象不存在。
            ValidationError: 收集对象已被收集项引用。
        """
        target = db.get(CollectionTarget, target_id)
        if target is None:
            raise NotFoundError(f"收集对象不存在: {target_id}")

        # 检查是否被 plan_item 引用
        ref_count = (
            db.query(PlanItem)
            .filter(PlanItem.target_id == target_id)
            .count()
        )
        if ref_count > 0:
            raise ValidationError(
                f"收集对象 '{target.name}' 已被 {ref_count} 个收集项引用，无法删除"
            )

        db.delete(target)
        db.commit()


# 模块级单例
target_svc = TargetService()
