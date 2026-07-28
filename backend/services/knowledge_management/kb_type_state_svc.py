# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库类型状态服务：管理 4 个预置 KB 类型的启用/禁用"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.core.knowledge_management.models import KbTypeState

logger = logging.getLogger(__name__)

# 预置的 4 个 KB 类型
PRESET_KB_TYPES = ['compliance', 'device_doc', 'sop_doc', 'history']


class KbTypeStateService:
    """KB 类型启用/禁用状态管理。

    当某个 kb_type 被禁用时，所有该类型下的 KB 在统计中不计入。
    """

    def list_states(self, db: Session) -> dict:
        """列出所有 kb_type 的启用状态。

        Returns:
            {"compliance": True, "device_doc": True, "sop_doc": False, "history": True}
        """
        rows = db.query(KbTypeState).all()
        state_map = {t: True for t in PRESET_KB_TYPES}  # 默认全启用
        for row in rows:
            state_map[row.kb_type] = row.enabled
        return state_map

    def set_enabled(self, db: Session, kb_type: str, enabled: bool, updated_by: str = "system"):
        """设置某个 kb_type 的启用状态。"""
        if kb_type not in PRESET_KB_TYPES:
            raise ValueError(f"未知的 kb_type: {kb_type}，必须是 {PRESET_KB_TYPES} 之一")

        row = db.query(KbTypeState).filter(KbTypeState.kb_type == kb_type).first()
        if row is None:
            row = KbTypeState(kb_type=kb_type, enabled=enabled, updated_by=updated_by)
            db.add(row)
        else:
            row.enabled = enabled
            row.updated_at = datetime.now(timezone.utc)
            row.updated_by = updated_by
        db.commit()
        logger.info("KB 类型状态变更: kb_type=%s, enabled=%s, by=%s", kb_type, enabled, updated_by)
        return {"kb_type": kb_type, "enabled": enabled}

    def get_disabled_types(self, db: Session) -> set[str]:
        """返回所有被禁用的 kb_type 集合。"""
        rows = db.query(KbTypeState).filter(KbTypeState.enabled == False).all()
        return {r.kb_type for r in rows}


# 模块级单例
kb_type_state_svc = KbTypeStateService()
