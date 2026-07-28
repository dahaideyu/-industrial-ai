# cython: annotation_typing=False, infer_types=False, language_level=3
"""操作日志服务"""
from typing import Optional
from sqlalchemy.orm import Session
from backend.core.knowledge_management.models import OperationLog


class OperationLogService:
    """轻量级操作日志 — 单表记录"""

    def log(self, db: Session, *,
            username: str, operation: str,
            target_type: str, target_id: Optional[str] = None,
            target_name: Optional[str] = None,
            user_id: Optional[str] = None,
            real_name: Optional[str] = None,
            kb_id: Optional[str] = None,
            remark: Optional[str] = None):
        entry = OperationLog(
            user_id=user_id,
            username=username,
            real_name=real_name,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            kb_id=kb_id,
            remark=remark,
        )
        db.add(entry)
        db.flush()

    def list(self, db: Session, *,
             kb_id: Optional[str] = None,
             user_id: Optional[str] = None,
             operation: Optional[str] = None,
             target_type: Optional[str] = None,
             page: int = 1, page_size: int = 50):
        q = db.query(OperationLog)
        if kb_id: q = q.filter(OperationLog.kb_id == kb_id)
        if user_id: q = q.filter(OperationLog.user_id == user_id)
        if operation: q = q.filter(OperationLog.operation == operation)
        if target_type: q = q.filter(OperationLog.target_type == target_type)
        total = q.count()
        items = q.order_by(OperationLog.created_at.desc()) \
            .offset((page - 1) * page_size).limit(page_size).all()
        return {"items": items, "total": total, "page": page, "page_size": page_size}


oplog_svc = OperationLogService()
