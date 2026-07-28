# cython: annotation_typing=False, infer_types=False, language_level=3
"""预设类别管理服务"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.core.knowledge_management.models import PresetCategory, DocumentCategory, KnowledgeBase


class PresetCategoryService:

    def get_tree(self, db: Session) -> list[dict]:
        items = db.query(PresetCategory).filter(PresetCategory.is_active == True) \
            .order_by(PresetCategory.sort_order).all()
        return self._build_tree(items)

    def _build_tree(self, items, parent_id=None):
        result = []
        for item in items:
            if item.parent_id == parent_id:
                result.append({
                    "id": item.id, "name": item.name,
                    "category_type": item.category_type,
                    "level": item.level, "is_leaf": item.is_leaf,
                    "requirement_desc": item.requirement_desc,
                    "sort_order": item.sort_order,
                    "children": self._build_tree(items, item.id),
                })
        return result

    def create(self, db: Session, data: dict):
        item = PresetCategory(**data)
        db.add(item)
        db.commit()
        return item

    def update(self, db: Session, preset_id: str, data: dict):
        item = db.query(PresetCategory).filter(PresetCategory.id == preset_id).first()
        if not item: return None
        for k, v in data.items():
            if hasattr(item, k): setattr(item, k, v)
        item.updated_at = datetime.now(timezone.utc)
        db.commit()
        return item

    def delete(self, db: Session, preset_id: str):
        item = db.query(PresetCategory).filter(PresetCategory.id == preset_id).first()
        if item:
            item.is_active = False
            db.commit()

    def sync_to_all_kb(self, db: Session, category_type: str) -> dict:
        # 注意：custom_base 类型知识库完全手动，不自动同步任何预设类别
        if category_type == 'compliance':
            kbs = db.query(KnowledgeBase).filter(
                KnowledgeBase.kb_type == 'compliance', KnowledgeBase.status == 'active').all()
        else:
            # device_doc / sop_doc 预设类别同步到 kb_type='device' 的知识库
            kbs = db.query(KnowledgeBase).filter(
                KnowledgeBase.kb_type == 'device', KnowledgeBase.status == 'active').all()
        presets = db.query(PresetCategory).filter(
            PresetCategory.category_type == category_type,
            PresetCategory.is_leaf == True, PresetCategory.is_active == True,
        ).all()
        added_total = 0
        for kb in kbs:
            # 加载此 KB 已有的所有 DocumentCategory，建立 (name, preset_category_id) 索引
            existing_cats = db.query(DocumentCategory).filter(
                DocumentCategory.knowledge_base_id == kb.id
            ).all()
            # 用 preset_category_id（外键字段）去重；手动创建的 preset_category_id 为 None
            existing_keys = {(c.name, str(c.preset_category_id) if c.preset_category_id else None) for c in existing_cats}
            for p in presets:
                if (p.name, str(p.id)) not in existing_keys:
                    db.add(DocumentCategory(
                        knowledge_base_id=kb.id, name=p.name,
                        requirement_desc=p.requirement_desc,
                        preset_category_id=p.id, sort_order=p.sort_order,
                        is_custom=False,
                    ))
                    added_total += 1
        db.commit()
        return {"synced_kb_count": len(kbs), "added_categories": added_total}


preset_category_svc = PresetCategoryService()
