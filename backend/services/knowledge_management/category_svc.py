# cython: annotation_typing=False, infer_types=False, language_level=3
"""文档类别服务"""
from sqlalchemy.orm import Session

from backend.core.knowledge_management.exceptions import (
    NotFoundError,
    ValidationError,
)
from backend.core.knowledge_management.models import DocumentCategory, PlanItem


class CategoryService:
    """文档类别 CRUD，删除前检查是否被收集项引用。"""

    def create(self, db: Session, kb_id: str, data: dict) -> DocumentCategory:
        """创建文档类别。

        Args:
            db: 数据库会话。
            kb_id: 所属知识库 ID。
            data: 包含 name, requirement_desc 字段。

        Returns:
            新创建的 DocumentCategory 实例。
        """
        cat = DocumentCategory(
            knowledge_base_id=kb_id,
            is_custom=True,  # 用户手动创建的类别标记为自定义
            **data,
        )
        db.add(cat)
        db.commit()
        db.refresh(cat)
        return cat

    def list(self, db: Session, kb_id: str) -> list[DocumentCategory]:
        """列出指定知识库下的所有文档类别，按创建时间降序。"""
        return (
            db.query(DocumentCategory)
            .filter(DocumentCategory.knowledge_base_id == kb_id)
            .order_by(DocumentCategory.created_at.desc())
            .all()
        )

    def update(self, db: Session, cat_id: str, data: dict) -> DocumentCategory:
        """更新文档类别字段。

        Args:
            db: 数据库会话。
            cat_id: 类别 ID。
            data: 需要更新的字段字典。

        Returns:
            更新后的 DocumentCategory 实例。
        """
        cat = db.get(DocumentCategory, cat_id)
        if cat is None:
            raise NotFoundError(f"文档类别不存在: {cat_id}")
        for key, value in data.items():
            if hasattr(cat, key):
                setattr(cat, key, value)
        db.commit()
        db.refresh(cat)
        return cat

    def delete(self, db: Session, cat_id: str):
        """删除文档类别，检查是否被收集项引用。

        Raises:
            NotFoundError: 类别不存在。
            ValidationError: 类别已被收集项引用。
        """
        cat = db.get(DocumentCategory, cat_id)
        if cat is None:
            raise NotFoundError(f"文档类别不存在: {cat_id}")

        # 检查是否被 plan_item 引用
        ref_count = (
            db.query(PlanItem)
            .filter(PlanItem.category_id == cat_id)
            .count()
        )
        if ref_count > 0:
            raise ValidationError(
                f"文档类别 '{cat.name}' 已被 {ref_count} 个收集项引用，无法删除"
            )

        db.delete(cat)
        db.commit()


# 模块级单例
category_svc = CategoryService()
