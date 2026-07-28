# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库 CRUD 服务"""
import logging

from sqlalchemy.orm import Session

from backend.clients.knowledge_management.ragflow_client import KnowledgeRAGFlowClient
from backend.core.knowledge_management.exceptions import NotFoundError, RAGFlowError
from backend.core.knowledge_management.models import KnowledgeBase
from services.knowledge_management.operation_log_svc import oplog_svc

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """知识库生命周期管理：CRUD + RAGFlow dataset 联动。"""

    def __init__(self, ragflow_client: KnowledgeRAGFlowClient):
        self._ragflow = ragflow_client

    # ------------------------------------------------------------------
    #  CRUD
    # ------------------------------------------------------------------

    def create(self, db: Session, data: dict) -> KnowledgeBase:
        """创建知识库，同步创建 RAGFlow dataset。

        Args:
            db: 数据库会话。
            data: 包含 name, description, chunk_method, parser_config 等字段。
                  vector_model 如果未提供则使用 .env 中的默认配置。

        Returns:
            新创建的 KnowledgeBase 实例。

        Raises:
            RAGFlowError: RAGFlow 创建数据集失败时抛出。
        """
        # 如果未提供 vector_model，使用 .env 中的默认配置
        if "vector_model" not in data or not data["vector_model"]:
            from backend.core.knowledge_management.config import settings
            data["vector_model"] = settings.ragflow_embedding_model

        kb = KnowledgeBase(**data)
        db.add(kb)
        db.flush()  # 获取 id

        try:
            rag_dataset_id = self._ragflow.create_dataset(
                name=kb.name,
                description=kb.description or "",
                chunk_method=kb.chunk_method or "naive",
                parser_config=kb.parser_config,
            )
            kb.rag_dataset_id = rag_dataset_id
        except RAGFlowError:
            logger.exception("创建 RAGFlow 数据集失败，知识库 name=%s", kb.name)
            raise

        oplog_svc.log(db, username="system", operation="kb_create", target_type="kb", target_name=data.get("name", ""), kb_id=kb.id)
        db.commit()
        db.refresh(kb)
        return kb

    def get(self, db: Session, kb_id: str) -> KnowledgeBase:
        """获取知识库，不存在时抛出 NotFoundError。"""
        kb = db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise NotFoundError(f"知识库不存在: {kb_id}")
        return kb

    def list(self, db: Session) -> list[KnowledgeBase]:
        """按 created_at 降序返回所有知识库。"""
        return (
            db.query(KnowledgeBase)
            .order_by(KnowledgeBase.created_at.desc())
            .all()
        )

    def update(self, db: Session, kb_id: str, data: dict) -> KnowledgeBase:
        """更新知识库字段。

        Args:
            db: 数据库会话。
            kb_id: 知识库 ID。
            data: 需要更新的字段字典。

        Returns:
            更新后的 KnowledgeBase 实例。
        """
        # 白名单：只允许更新安全字段，防止 mass assignment 覆盖 id / rag_dataset_id
        _ALLOWED_UPDATE_FIELDS = {"name", "description", "chunk_method", "parser_config", "vector_model"}
        kb = self.get(db, kb_id)
        for key, value in data.items():
            if key in _ALLOWED_UPDATE_FIELDS and hasattr(kb, key):
                setattr(kb, key, value)
        db.commit()
        db.refresh(kb)
        return kb

    def delete(self, db: Session, kb_id: str):
        """删除知识库：先删 RAGFlow dataset，再删数据库（CASCADE）。

        RAGFlow 删除失败时记录日志但不阻塞数据库删除。
        """
        kb = self.get(db, kb_id)

        # 先删 RAGFlow 数据集
        if kb.rag_dataset_id:
            try:
                self._ragflow.delete_dataset(kb.rag_dataset_id)
            except RAGFlowError:
                logger.warning(
                    "删除 RAGFlow 数据集失败，继续删除本地数据: dataset_id=%s",
                    kb.rag_dataset_id,
                )

        db.delete(kb)
        db.commit()

    # ------------------------------------------------------------------
    #  RAGFlow 文档查询
    # ------------------------------------------------------------------

    def get_rag_documents(
        self, db: Session, kb_id: str, page: int = 1, page_size: int = 30
    ) -> dict:
        """调用 RAGFlow 获取该知识库数据集下的文档列表。

        Args:
            db: 数据库会话。
            kb_id: 知识库 ID。
            page: 页码（从 1 开始）。
            page_size: 每页数量。

        Returns:
            RAGFlow 返回的文档列表和分页信息。

        Raises:
            NotFoundError: 知识库不存在。
            ValidationError: 知识库未关联 RAGFlow 数据集。
        """
        kb = self.get(db, kb_id)
        if not kb.rag_dataset_id:
            from backend.core.knowledge_management.exceptions import ValidationError
            raise ValidationError(f"知识库未关联 RAGFlow 数据集: {kb_id}")
        return self._ragflow.list_documents(
            kb.rag_dataset_id, page=page, page_size=page_size
        )


# 模块级服务实例
# 注意：requests.Session 非线程安全，高并发下如有问题可改用工厂函数延迟创建
kb_svc = KnowledgeBaseService(KnowledgeRAGFlowClient())
