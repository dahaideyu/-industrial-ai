# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库管理模块 ORM 模型（7 张核心表 + 1 张映射表）

所有表使用 knb_ 前缀，UUID 主键存储为字符串。
"""
import uuid
from datetime import datetime, date, timezone
from typing import Optional, List

from sqlalchemy import (
    String, Text, Integer, BigInteger, Boolean, DateTime, Date,
    ForeignKey, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from backend.core.knowledge_management.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────
# 1. knb_knowledge_bases — 知识库
# ──────────────────────────────────────────────────────────────
class KnowledgeBase(Base):
    __tablename__ = "knb_knowledge_bases"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    rag_dataset_id: Mapped[Optional[str]] = mapped_column(String(100))
    vector_model: Mapped[Optional[str]] = mapped_column(String(100))
    chunk_method: Mapped[Optional[str]] = mapped_column(String(50))
    parser_config: Mapped[Optional[dict]] = mapped_column(JSONB)
    device_type: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")
    tags: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    sync_type: Mapped[str] = mapped_column(String(20), default="manual")
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    kb_type: Mapped[str] = mapped_column(String(20), default="device_doc")
    overall_progress: Mapped[Optional[int]] = mapped_column(Integer)
    overall_score: Mapped[Optional[int]] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    # relationships
    categories: Mapped[List["DocumentCategory"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    targets: Mapped[List["CollectionTarget"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    plans: Mapped[List["CollectionPlan"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )


# ──────────────────────────────────────────────────────────────
# 2. knb_document_categories — 文档类别
# ──────────────────────────────────────────────────────────────
class DocumentCategory(Base):
    __tablename__ = "knb_document_categories"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knb_knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    requirement_desc: Mapped[str] = mapped_column(Text, nullable=False)
    preset_category_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False))
    parent_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    # relationships
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        back_populates="categories"
    )
    plan_items: Mapped[List["PlanItem"]] = relationship(
        back_populates="category"
    )


# ──────────────────────────────────────────────────────────────
# 3. knb_collection_targets — 收集对象
# ──────────────────────────────────────────────────────────────
class CollectionTarget(Base):
    __tablename__ = "knb_collection_targets"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knb_knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    attributes: Mapped[Optional[list]] = mapped_column(JSONB)
    # attributes 格式: [{"label": "设备厂家", "value": "东顺"}, ...]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    # relationships
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        back_populates="targets"
    )
    plan_items: Mapped[List["PlanItem"]] = relationship(
        back_populates="target"
    )


# ──────────────────────────────────────────────────────────────
# 4. knb_collection_plans — 收集计划
# ──────────────────────────────────────────────────────────────
class CollectionPlan(Base):
    __tablename__ = "knb_collection_plans"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knb_knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    due_date: Mapped[Optional[str]] = mapped_column(String(20))
    # 计划级评估
    overall_progress: Mapped[Optional[int]] = mapped_column(Integer)
    overall_score: Mapped[Optional[int]] = mapped_column(Integer)
    overall_analysis: Mapped[Optional[str]] = mapped_column(Text)
    overall_stats: Mapped[Optional[dict]] = mapped_column(JSONB)
    # overall_stats 格式: {"completed": 8, "improving": 3, "missing": 6, "overdue": 2}
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    plan_type: Mapped[str] = mapped_column(String(20), default="device_doc")
    sync_type: Mapped[str] = mapped_column(String(20), default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    # relationships
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        back_populates="plans"
    )
    plan_items: Mapped[List["PlanItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


# ──────────────────────────────────────────────────────────────
# 5. knb_plan_items — 计划收集项（笛卡尔积）
# ──────────────────────────────────────────────────────────────
class PlanItem(Base):
    __tablename__ = "knb_plan_items"
    __table_args__ = (
        UniqueConstraint("plan_id", "category_id", "target_id"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    plan_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knb_collection_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knb_document_categories.id"),
        nullable=False,
    )
    target_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knb_collection_targets.id"),
        nullable=False,
    )
    requirement_override: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    # 综合评估结果
    overall_completion: Mapped[Optional[str]] = mapped_column(Text)
    overall_score: Mapped[Optional[int]] = mapped_column(Integer)
    overall_status: Mapped[Optional[str]] = mapped_column(String(20))
    # 已完成/待完善/缺失
    evaluation_detail: Mapped[Optional[dict]] = mapped_column(JSONB)
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    not_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    not_applicable_by: Mapped[Optional[str]] = mapped_column(String(100))
    not_applicable_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    not_applicable_reason: Mapped[Optional[str]] = mapped_column(Text)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)

    # relationships
    plan: Mapped["CollectionPlan"] = relationship(back_populates="plan_items")
    category: Mapped["DocumentCategory"] = relationship(
        back_populates="plan_items"
    )
    target: Mapped["CollectionTarget"] = relationship(
        back_populates="plan_items"
    )
    documents: Mapped[List["Document"]] = relationship(
        back_populates="plan_item", cascade="all, delete-orphan"
    )


# ──────────────────────────────────────────────────────────────
# 6. knb_documents — 文档主表
# ──────────────────────────────────────────────────────────────
class Document(Base):
    __tablename__ = "knb_documents"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    plan_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knb_plan_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    # relationships
    plan_item: Mapped["PlanItem"] = relationship(back_populates="documents")
    versions: Mapped[List["DocumentVersion"]] = relationship(
        back_populates="document",
        foreign_keys="DocumentVersion.document_id",
        cascade="all, delete-orphan",
    )


# ──────────────────────────────────────────────────────────────
# 7. knb_document_versions — 文档版本
# ──────────────────────────────────────────────────────────────
class DocumentVersion(Base):
    __tablename__ = "knb_document_versions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knb_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_label: Mapped[Optional[str]] = mapped_column(String(20))
    original_filename: Mapped[Optional[str]] = mapped_column(String(500))
    storage_path: Mapped[Optional[str]] = mapped_column(String(1000))
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    file_hash: Mapped[Optional[str]] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    chunk_method: Mapped[Optional[str]] = mapped_column(String(20))
    extracted_text: Mapped[Optional[str]] = mapped_column(Text)
    pdf_preview_path: Mapped[Optional[str]] = mapped_column(String(1000))
    parent_document_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knb_documents.id"),
    )
    auto_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_relevance_score: Mapped[Optional[int]] = mapped_column(Integer)
    ai_quality_score: Mapped[Optional[int]] = mapped_column(Integer)
    ai_relevance_remark: Mapped[Optional[str]] = mapped_column(Text)
    ai_quality_remark: Mapped[Optional[str]] = mapped_column(Text)
    rejected_reason: Mapped[Optional[str]] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_status: Mapped[Optional[str]] = mapped_column(String(20))
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(100))
    # 后台任务进度
    convert_status: Mapped[Optional[str]] = mapped_column(String(20))
    extract_status: Mapped[Optional[str]] = mapped_column(String(20))
    # RAGFlow 文档解析状态: unstart / running / done / fail / cancel
    parse_status: Mapped[Optional[str]] = mapped_column(String(20))
    # 图纸解析进度
    drawing_parse_status: Mapped[Optional[str]] = mapped_column(String(20))  # pending/processing/done/failed
    drawing_parse_progress: Mapped[Optional[int]] = mapped_column(Integer)  # 0-100
    drawing_parse_step: Mapped[Optional[str]] = mapped_column(String(100))  # 当前步骤描述
    drawing_parse_detail: Mapped[Optional[str]] = mapped_column(Text)  # 详细进度信息
    has_stamp: Mapped[Optional[bool]] = mapped_column(Boolean)
    has_signature: Mapped[Optional[bool]] = mapped_column(Boolean)
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_until: Mapped[Optional[date]] = mapped_column(Date)
    compliance_score: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    # relationships
    document: Mapped["Document"] = relationship(
        back_populates="versions",
        foreign_keys=[document_id],
    )
    rag_mapping: Mapped[Optional["RAGDocumentMap"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


# ──────────────────────────────────────────────────────────────
# 8. knb_rag_document_map — RAGFlow 映射
# ──────────────────────────────────────────────────────────────
class RAGDocumentMap(Base):
    __tablename__ = "knb_rag_document_map"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("knb_document_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    rag_document_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rag_dataset_id: Mapped[str] = mapped_column(String(100), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    # relationships
    version: Mapped["DocumentVersion"] = relationship(
        back_populates="rag_mapping"
    )


# ──────────────────────────────────────────────────────────────
# 9. knb_preset_categories — 预设文档类别
# ──────────────────────────────────────────────────────────────
class PresetCategory(Base):
    __tablename__ = "knb_preset_categories"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    parent_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("knb_preset_categories.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    requirement_desc: Mapped[str] = mapped_column(Text, nullable=False)
    category_type: Mapped[str] = mapped_column(String(50), nullable=False)  # device_doc / sop_doc / compliance
    level: Mapped[int] = mapped_column(Integer, default=0)   # 0=一级, 1=二级, 2=三级(叶子)
    is_leaf: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    children = relationship("PresetCategory", backref=backref("parent", remote_side=[id]))


# ──────────────────────────────────────────────────────────────
# 10. knb_operation_logs — 操作日志
# ──────────────────────────────────────────────────────────────
class OperationLog(Base):
    __tablename__ = "knb_operation_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(String(100))
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    real_name: Mapped[Optional[str]] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)  # kb / plan / plan_item / document / version
    target_id: Mapped[Optional[str]] = mapped_column(String(36))
    target_name: Mapped[Optional[str]] = mapped_column(String(500))
    kb_id: Mapped[Optional[str]] = mapped_column(String(36))  # 关联KB便于筛选
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ──────────────────────────────────────────────────────────────
# 11. knb_kb_type_states — 知识库类型启用/禁用状态
# ──────────────────────────────────────────────────────────────
class KbTypeState(Base):
    __tablename__ = "knb_kb_type_states"

    kb_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(100))
