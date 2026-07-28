# cython: annotation_typing=False, infer_types=False, language_level=3
"""设备类型同步服务 — 查询 AQA MySQL，增量创建/停用知识库"""
import logging
from datetime import datetime, timezone
import pymysql

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session
from backend.core.knowledge_management.config import settings
from backend.core.knowledge_management.models import (
    KnowledgeBase, DocumentCategory, CollectionTarget, CollectionPlan, PlanItem,
    PresetCategory,
)


class DeviceTypeSyncService:

    def _get_aqa_connection(self):
        return pymysql.connect(
            host=settings.aqa_mysql_host, port=settings.aqa_mysql_port,
            user=settings.aqa_mysql_user, password=settings.aqa_mysql_password,
            database=settings.aqa_mysql_database, charset='utf8mb4',
        )

    def get_device_types_from_aqa(self) -> list[dict]:
        sql = """
        SELECT DISTINCT t.name AS device_type, sw.name AS workshop
        FROM dev_device_type t
        LEFT JOIN dev_device d ON t.id = d.type_id
        LEFT JOIN sys_line l ON d.line_id = l.id
        LEFT JOIN sys_workshop sw ON l.dept_id = sw.id
        WHERE t.del_flag=0 AND d.del_flag=0 AND l.del_flag=0 AND sw.del_flag=0
          AND t.name != '其他'
        """
        conn = self._get_aqa_connection()
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(sql)
                return cursor.fetchall()
        finally:
            conn.close()

    def sync_device_types(self, db: Session) -> dict:
        # 获取被禁用的 KB 类型（device_doc/sop_doc）— 这些类型下不创建/恢复 KB
        from backend.services.knowledge_management.kb_type_state_svc import kb_type_state_svc
        disabled_types = kb_type_state_svc.get_disabled_types(db)

        aqa_devices = self.get_device_types_from_aqa()
        # 类型禁用 → 该设备的所有 plan 都不创建
        if 'device_doc' in disabled_types and 'sop_doc' in disabled_types:
            aqa_devices = []  # 完全跳过

        aqa_names = {d['device_type'] for d in aqa_devices}
        # 兼容旧架构：kb_type in (device_doc, sop_doc, history) 或 新架构: device
        existing = db.query(KnowledgeBase).filter(
            KnowledgeBase.kb_type.in_(['device', 'device_doc', 'sop_doc', 'history']),
            KnowledgeBase.device_type.isnot(None)
        ).all()
        # 已存在的 device_type（去重），按 device_type 维度
        existing_names = {kb.device_type for kb in existing}
        created, disabled_count, recovered = 0, 0, 0
        for d in aqa_devices:
            if d['device_type'] not in existing_names:
                self._create_kb_set(db, d['device_type'], d['workshop'])
                created += 1
        # 补建：KB 已存在但 rag_dataset_id 为空（之前因 RAGFlow/网络问题失败）
        for kb in existing:
            if not kb.rag_dataset_id and kb.status == 'active':
                workshop = (kb.tags or {}).get('workshop', '')
                try:
                    from backend.clients.knowledge_management.ragflow_client import KnowledgeRAGFlowClient
                    ragflow = KnowledgeRAGFlowClient()
                    rag_dataset_id = ragflow.create_dataset(
                        name=f"{workshop}-{kb.device_type}",
                        description=f"{kb.device_type} — 设备知识库（含设备说明+SOP文档）",
                        chunk_method="naive",
                        parser_config=None,
                        embedding_model=settings.ragflow_embedding_model,
                    )
                    kb.rag_dataset_id = rag_dataset_id
                    db.commit()
                    logger.info("补建设备 KB RAGFlow dataset 成功: %s -> %s", kb.device_type, rag_dataset_id)
                    recovered += 1
                except Exception as e:
                    logger.warning("补建设备 KB RAGFlow dataset 失败 device_type=%s: %s", kb.device_type, e)
        for kb in existing:
            # 已被用户禁用的 KB 不要被 sync 重新激活
            if not kb.enabled and kb.status == 'active':
                continue  # 保持禁用
            if kb.device_type not in aqa_names and kb.status == 'active':
                kb.status = 'disabled'
                disabled_count += 1
        db.commit()
        return {"created": created, "disabled": disabled_count, "recovered": recovered}

    def create_single_kb(self, db: Session, device_type: str, workshop: str):
        existing = db.query(KnowledgeBase).filter(
            KnowledgeBase.device_type == device_type,
            KnowledgeBase.kb_type.in_(['device', 'device_doc', 'sop_doc', 'history'])
        ).first()
        if existing:
            return None
        return self._create_kb_set(db, device_type, workshop)

    def _create_kb_set(self, db: Session, device_type: str, workshop: str):
        """为设备类型创建1个统一知识库（含设备说明+SOP+历史沉淀三个计划）"""
        base_name = settings.knb_base_name
        tags = {"base": base_name, "workshop": workshop}
        now = datetime.now(timezone.utc)

        # 创建1个统一KB
        kb = KnowledgeBase(
            name=device_type,
            device_type=device_type,
            kb_type="device",
            tags=tags,
            sync_type="auto",
            status="active",
            synced_at=now,
            vector_model=settings.ragflow_embedding_model,
        )
        db.add(kb)
        db.flush()

        # 在 RAGFlow 创建 dataset
        try:
            from backend.clients.knowledge_management.ragflow_client import KnowledgeRAGFlowClient
            ragflow = KnowledgeRAGFlowClient()
            rag_dataset_id = ragflow.create_dataset(
                name=f"{workshop}-{device_type}",
                description=f"{device_type} — 设备知识库（含设备说明+SOP文档）",
                chunk_method="naive",
                parser_config=None,
                embedding_model=settings.ragflow_embedding_model,
            )
            kb.rag_dataset_id = rag_dataset_id
        except Exception as e:
            logger.warning("自动创建KB的RAGFlow dataset失败 device_type=%s: %s", device_type, e)

        # 同步设备说明 + SOP 预设类别
        self._sync_presets_to_kb(db, kb.id, "device_doc")
        self._sync_presets_to_kb(db, kb.id, "sop_doc")

        # 创建1个 CollectionTarget
        self._create_target(db, kb.id, device_type)

        # 创建设备说明收集计划
        self._create_plan_with_items(db, kb.id, "device_doc")
        # 创建SOP收集计划
        self._create_plan_with_items(db, kb.id, "sop_doc")
        # 创建历史沉淀收集计划（pending）— 仅作占位，等数据→文档转换方案实施
        self._create_history_plan(db, kb.id)

    def _create_history_plan(self, db: Session, kb_id: str):
        """历史沉淀收集计划（占位）"""
        plan = CollectionPlan(
            knowledge_base_id=kb_id, name="历史沉淀文档采集",
            plan_type="history", sync_type="auto", status="pending",
        )
        db.add(plan)
        db.flush()
        # 历史沉淀暂无 source，但为了 dashboard 统一统计加上 1 个 placeholder target
        target = db.query(CollectionTarget).filter(
            CollectionTarget.knowledge_base_id == kb_id
        ).first()
        if target:
            placeholder_cat = db.query(DocumentCategory).filter(
                DocumentCategory.knowledge_base_id == kb_id,
            ).first()
            if placeholder_cat:
                db.add(PlanItem(
                    plan_id=plan.id, category_id=placeholder_cat.id,
                    target_id=target.id, is_custom=False,
                ))

        db.commit()
        return [kb_id]

    def _sync_presets_to_kb(self, db: Session, kb_id: str, category_type: str):
        presets = db.query(PresetCategory).filter(
            PresetCategory.category_type == category_type,
            PresetCategory.is_leaf == True,
            PresetCategory.is_active == True,
        ).all()
        for p in presets:
            db.add(DocumentCategory(
                knowledge_base_id=kb_id, name=p.name,
                requirement_desc=p.requirement_desc,
                preset_category_id=p.id, sort_order=p.sort_order,
                is_custom=False,
            ))

    def _create_target(self, db: Session, kb_id: str, device_type: str):
        # name 使用"设备类型"标识（统一类型标签），attributes记录具体设备类型名
        db.add(CollectionTarget(
            knowledge_base_id=kb_id, name="设备类型", target_type="设备类型",
            attributes=[{"label": "设备类型", "value": device_type}],
        ))
        # 立即 flush 确保 id 可用，避免后续查询时 PlanItem 引用 NULL target_id
        db.flush()

    def _create_plan_with_items(self, db: Session, kb_id: str, plan_type: str):
        plan_name = {"device_doc": "设备说明文档采集", "sop_doc": "SOP文档采集"}.get(plan_type, plan_type)
        plan = CollectionPlan(knowledge_base_id=kb_id, name=plan_name,
                              plan_type=plan_type, sync_type="auto")
        db.add(plan)
        db.flush()
        # 只关联对应类型的预设类别
        categories = db.query(DocumentCategory).join(
            PresetCategory, DocumentCategory.preset_category_id == PresetCategory.id
        ).filter(
            DocumentCategory.knowledge_base_id == kb_id,
            PresetCategory.category_type == plan_type,
        ).all()
        targets = db.query(CollectionTarget).filter(
            CollectionTarget.knowledge_base_id == kb_id).all()
        item_count = 0
        for cat in categories:
            for tgt in targets:
                db.add(PlanItem(plan_id=plan.id, category_id=cat.id,
                                target_id=tgt.id, is_custom=False))
                item_count += 1
        # 初始化计划级统计（所有收集项默认 missing）
        plan.overall_progress = 0
        plan.overall_stats = {
            "completed": 0,
            "improving": 0,
            "missing": item_count,
            "overdue": 0,
        }


device_sync_svc = DeviceTypeSyncService()
