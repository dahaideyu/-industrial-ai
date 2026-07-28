# cython: annotation_typing=False, infer_types=False, language_level=3
"""PostgreSQL 数据库连接管理"""
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from backend.core.knowledge_management.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _run_migrations():
    """对已有表执行增量迁移（新增列 + 数据回填）"""
    migrations = [
        # 为 knb_collection_plans 添加 priority 和 due_date 字段
        "ALTER TABLE knb_collection_plans ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal'",
        "ALTER TABLE knb_collection_plans ADD COLUMN IF NOT EXISTS due_date VARCHAR(20)",
        # 为 knb_plan_items 的 priority 默认值从中文改为英文
        "ALTER TABLE knb_plan_items ALTER COLUMN priority SET DEFAULT 'normal'",
        # 回填已有数据中的中文优先级值
        "UPDATE knb_plan_items SET priority = 'normal' WHERE priority = '一般'",
        "UPDATE knb_collection_plans SET priority = 'normal' WHERE priority = '一般' AND priority IS NOT NULL",
        # 为 knb_document_versions 添加 RAGFlow 解析状态字段
        "ALTER TABLE knb_document_versions ADD COLUMN IF NOT EXISTS parse_status VARCHAR(20)",
        # 为 knb_plan_items 添加评估时间字段
        "ALTER TABLE knb_plan_items ADD COLUMN IF NOT EXISTS evaluated_at TIMESTAMPTZ",
        # 为 knb_collection_plans 添加评估时间、评分字段
        "ALTER TABLE knb_collection_plans ADD COLUMN IF NOT EXISTS evaluated_at TIMESTAMPTZ",
        "ALTER TABLE knb_collection_plans ADD COLUMN IF NOT EXISTS overall_score INTEGER",
        # knb_knowledge_bases
        "ALTER TABLE knb_knowledge_bases ADD COLUMN IF NOT EXISTS device_type VARCHAR(255)",
        "ALTER TABLE knb_knowledge_bases ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active'",
        "ALTER TABLE knb_knowledge_bases ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '{}'",
        "ALTER TABLE knb_knowledge_bases ADD COLUMN IF NOT EXISTS sync_type VARCHAR(20) DEFAULT 'manual'",
        "ALTER TABLE knb_knowledge_bases ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ",
        "ALTER TABLE knb_knowledge_bases ADD COLUMN IF NOT EXISTS kb_type VARCHAR(20) DEFAULT 'device_doc'",
        "ALTER TABLE knb_knowledge_bases ADD COLUMN IF NOT EXISTS overall_progress INTEGER",
        "ALTER TABLE knb_knowledge_bases ADD COLUMN IF NOT EXISTS overall_score INTEGER",
        # knb_plan_items
        "ALTER TABLE knb_plan_items ADD COLUMN IF NOT EXISTS not_applicable BOOLEAN DEFAULT FALSE",
        "ALTER TABLE knb_plan_items ADD COLUMN IF NOT EXISTS not_applicable_by VARCHAR(100)",
        "ALTER TABLE knb_plan_items ADD COLUMN IF NOT EXISTS not_applicable_at TIMESTAMPTZ",
        "ALTER TABLE knb_plan_items ADD COLUMN IF NOT EXISTS not_applicable_reason TEXT",
        "ALTER TABLE knb_plan_items ADD COLUMN IF NOT EXISTS is_custom BOOLEAN DEFAULT FALSE",
        # knb_document_categories
        "ALTER TABLE knb_document_categories ADD COLUMN IF NOT EXISTS preset_category_id UUID",
        "ALTER TABLE knb_document_categories ADD COLUMN IF NOT EXISTS parent_id UUID",
        "ALTER TABLE knb_document_categories ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0",
        "ALTER TABLE knb_document_categories ADD COLUMN IF NOT EXISTS is_custom BOOLEAN DEFAULT FALSE",
        # knb_document_versions
        "ALTER TABLE knb_document_versions ADD COLUMN IF NOT EXISTS has_stamp BOOLEAN",
        "ALTER TABLE knb_document_versions ADD COLUMN IF NOT EXISTS has_signature BOOLEAN",
        "ALTER TABLE knb_document_versions ADD COLUMN IF NOT EXISTS valid_from DATE",
        "ALTER TABLE knb_document_versions ADD COLUMN IF NOT EXISTS valid_until DATE",
        "ALTER TABLE knb_document_versions ADD COLUMN IF NOT EXISTS compliance_score INTEGER",
        # knb_collection_plans
        "ALTER TABLE knb_collection_plans ADD COLUMN IF NOT EXISTS plan_type VARCHAR(20) DEFAULT 'device_doc'",
        "ALTER TABLE knb_collection_plans ADD COLUMN IF NOT EXISTS sync_type VARCHAR(20) DEFAULT 'manual'",

        # 知识库启用/禁用功能
        "ALTER TABLE knb_knowledge_bases ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE",
        # 知识库类型启用状态表（4 个预置类型：compliance/device_doc/sop_doc/history）
        "CREATE TABLE IF NOT EXISTS knb_kb_type_states ("
        "  kb_type VARCHAR(30) PRIMARY KEY,"
        "  enabled BOOLEAN NOT NULL DEFAULT TRUE,"
        "  updated_at TIMESTAMPTZ DEFAULT NOW(),"
        "  updated_by VARCHAR(100))",

        # 新建 knb_preset_categories 表（如果不存在）
        "CREATE TABLE IF NOT EXISTS knb_preset_categories ("
        "  id UUID PRIMARY KEY, parent_id UUID, name VARCHAR(255) NOT NULL,"
        "  requirement_desc TEXT NOT NULL, category_type VARCHAR(50) NOT NULL,"
        "  level INTEGER DEFAULT 0, is_leaf BOOLEAN DEFAULT TRUE,"
        "  sort_order INTEGER DEFAULT 0, is_active BOOLEAN DEFAULT TRUE,"
        "  version INTEGER DEFAULT 1, created_at TIMESTAMPTZ DEFAULT NOW(),"
        "  updated_at TIMESTAMPTZ DEFAULT NOW())",

        # 新建 knb_operation_logs 表（如果不存在）
        "CREATE TABLE IF NOT EXISTS knb_operation_logs ("
        "  id UUID PRIMARY KEY, user_id VARCHAR(100), username VARCHAR(100) NOT NULL,"
        "  real_name VARCHAR(100), operation VARCHAR(50) NOT NULL,"
        "  target_type VARCHAR(50) NOT NULL, target_id UUID,"
        "  target_name VARCHAR(500), kb_id UUID, remark TEXT,"
        "  created_at TIMESTAMPTZ DEFAULT NOW())",

        # 操作日志索引
        "CREATE INDEX IF NOT EXISTS idx_oplog_target ON knb_operation_logs(target_type, target_id)",
        "CREATE INDEX IF NOT EXISTS idx_oplog_user ON knb_operation_logs(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_oplog_time ON knb_operation_logs(created_at DESC NULLS LAST)",

        # 文档搜索：pg_trgm 扩展 + GIN 索引（加速 ILIKE 模糊查询）
        "CREATE EXTENSION IF NOT EXISTS pg_trgm",
        "CREATE INDEX IF NOT EXISTS idx_knb_docver_filename_trgm ON knb_document_versions USING GIN (original_filename gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS idx_knb_docs_displayname_trgm ON knb_documents USING GIN (display_name gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS idx_knb_docver_is_current ON knb_document_versions (is_current) WHERE is_current = TRUE",
    ]
    with engine.begin() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                logger.info("迁移执行成功: %s", sql[:80])
            except Exception as e:
                logger.error("迁移执行失败: %s — %s", sql[:80], e)


def _ensure_compliance_kb():
    """确保当前基地存在合规性知识库（幂等，含RAGFlow dataset + 计划 + 收集项）"""
    from backend.core.knowledge_management.models import (
        KnowledgeBase, CollectionTarget, CollectionPlan, PlanItem, DocumentCategory,
    )
    from backend.core.knowledge_management.config import settings
    from backend.clients.knowledge_management.ragflow_client import KnowledgeRAGFlowClient

    db = next(get_db())
    try:
        exists = db.query(KnowledgeBase).filter(
            KnowledgeBase.kb_type == 'compliance',
            KnowledgeBase.tags['base'].astext == settings.knb_base_name,
        ).first()
        if exists:
            # 即使KB已存在，也要确保有 target/plan/items（防御性检查）
            _ensure_compliance_kb_structure(db, exists.id)
            # 重试 RAGFlow dataset（之前可能因网络/服务不可用失败）
            if not exists.rag_dataset_id:
                try:
                    from backend.clients.knowledge_management.ragflow_client import KnowledgeRAGFlowClient
                    ragflow = KnowledgeRAGFlowClient()
                    rag_dataset_id = ragflow.create_dataset(
                        name=exists.name,
                        description="基地级别合规性知识库 — 安环合规文档与证书",
                        chunk_method="naive",
                        parser_config=None,
                        embedding_model=settings.ragflow_embedding_model,
                    )
                    exists.rag_dataset_id = rag_dataset_id
                    db.commit()
                    logger.info("合规性KB RAGFlow dataset 重试成功: %s", rag_dataset_id)
                except Exception as e:
                    logger.warning("合规性KB RAGFlow dataset 重试失败: %s", e)
            return

        kb = KnowledgeBase(
            name=f"{settings.knb_base_name}-合规性知识库",
            kb_type="compliance",
            tags={"base": settings.knb_base_name},
            sync_type="auto",
            status="active",
            vector_model=settings.ragflow_embedding_model,
        )
        db.add(kb)
        db.flush()
        # 先提交一次确保 ID 持久化（避免 sync_to_all_kb 查不到）
        db.commit()
        db.refresh(kb)

        # 在 RAGFlow 创建对应的 dataset
        try:
            ragflow = KnowledgeRAGFlowClient()
            rag_dataset_id = ragflow.create_dataset(
                name=kb.name,
                description="基地级别合规性知识库 — 安环合规文档与证书",
                chunk_method="naive",
                parser_config=None,
                embedding_model=settings.ragflow_embedding_model,
            )
            kb.rag_dataset_id = rag_dataset_id
            db.commit()
        except Exception as e:
            logger.warning("合规性KB RAGFlow dataset 创建失败（将重试）: %s", e)

        # 同步合规性预设类别到KB
        from backend.services.knowledge_management.preset_category_svc import preset_category_svc
        result = preset_category_svc.sync_to_all_kb(db, 'compliance')
        logger.info("合规性预设类别同步: added=%d to %d KBs", result.get("added_categories", 0), result.get("synced_kb_count", 0))
        db.commit()

        # 再次刷新确保类别可见
        db.refresh(kb)

        # 创建 CollectionTarget（如果还没有）
        target = db.query(CollectionTarget).filter(
            CollectionTarget.knowledge_base_id == kb.id
        ).first()
        if not target:
            target = CollectionTarget(
                knowledge_base_id=kb.id,
                name=f"{settings.knb_base_name}基地合规文档",
                target_type="基地",
            )
            db.add(target)
            db.flush()
            db.commit()
            db.refresh(target)

        # 创建合规性收集计划（如果还没有）
        plan = db.query(CollectionPlan).filter(
            CollectionPlan.knowledge_base_id == kb.id,
            CollectionPlan.plan_type == 'compliance'
        ).first()
        if not plan:
            plan = CollectionPlan(
                knowledge_base_id=kb.id,
                name="安环合规文档采集",
                plan_type="compliance",
                sync_type="auto",
            )
            db.add(plan)
            db.flush()
            db.commit()
            db.refresh(plan)

        # 为合规性类别创建 PlanItems（如果还没有）
        existing_items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).count()
        if existing_items == 0:
            categories = db.query(DocumentCategory).filter(
                DocumentCategory.knowledge_base_id == kb.id,
            ).all()
            for cat in categories:
                db.add(PlanItem(
                    plan_id=plan.id, category_id=cat.id,
                    target_id=target.id, is_custom=False,
                ))
            db.commit()

        logger.info("合规性知识库创建完成: %s (categories=%d, items=%d)",
                    kb.name,
                    db.query(DocumentCategory).filter(DocumentCategory.knowledge_base_id == kb.id).count(),
                    db.query(PlanItem).filter(PlanItem.plan_id == plan.id).count())
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


def _ensure_compliance_kb_structure(db, kb_id):
    """防御性检查：确保合规性KB有完整的 target/plan/items 结构"""
    from backend.core.knowledge_management.models import (
        CollectionTarget, CollectionPlan, PlanItem, DocumentCategory,
    )
    from backend.core.knowledge_management.config import settings

    target = db.query(CollectionTarget).filter(
        CollectionTarget.knowledge_base_id == kb_id
    ).first()
    if not target:
        target = CollectionTarget(
            knowledge_base_id=kb_id,
            name=f"{settings.knb_base_name}基地合规文档",
            target_type="基地",
        )
        db.add(target)
        db.flush()

    plan = db.query(CollectionPlan).filter(
        CollectionPlan.knowledge_base_id == kb_id,
        CollectionPlan.plan_type == 'compliance'
    ).first()
    if not plan:
        plan = CollectionPlan(
            knowledge_base_id=kb_id, name="安环合规文档采集",
            plan_type="compliance", sync_type="auto",
        )
        db.add(plan)
        db.flush()

    # 为所有类别补齐 PlanItem（处理「重新加载预设」后新增类别的情况）
    all_cats = db.query(DocumentCategory).filter(
        DocumentCategory.knowledge_base_id == kb_id,
    ).all()
    existing_item_cat_ids = {pi.category_id for pi in db.query(PlanItem).filter(
        PlanItem.plan_id == plan.id
    ).all()}
    for cat in all_cats:
        if cat.id not in existing_item_cat_ids:
            db.add(PlanItem(
                plan_id=plan.id, category_id=cat.id,
                target_id=target.id, is_custom=False,
            ))

    db.commit()


def init_db():
    """创建所有表（首次启动时调用），支持数据库未就绪时重试"""
    import time
    import backend.core.knowledge_management.models  # noqa: F401 — 确保模型被注册
    import backend.models.knowledge_qa                # noqa: F401 — 确保 KB-QA 会话/消息/chat assistant 表被创建

    # ---- 1. 创建表 & 迁移（带重试，应对 PostgreSQL 启动延迟） ----
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            Base.metadata.create_all(bind=engine)
            _run_migrations()
            logger.info("数据库表创建/迁移完成 (attempt=%d)", attempt)
            break
        except Exception as e:
            if attempt < max_retries:
                logger.warning("数据库初始化失败 (attempt=%d/%d)，3s 后重试: %s", attempt, max_retries, e)
                time.sleep(3)
            else:
                logger.error("数据库初始化失败，已达最大重试次数: %s", e)
                raise

    # ---- 2. 种子预设类别 ----
    try:
        from backend.core.knowledge_management.preset_seed import seed_preset_categories
        db = next(get_db())
        try:
            result = seed_preset_categories(db)
            logger.info("预设类别种子完成: %s", result)
        finally:
            db.close()
    except Exception as e:
        logger.error("预设类别初始化失败（不影响主流程）: %s", e)

    # ---- 3. 确保合规性KB存在 ----
    try:
        _ensure_compliance_kb()
        logger.info("合规性知识库初始化完成")
    except Exception as e:
        logger.error("合规性知识库初始化失败（不影响主流程）: %s", e)

    # ---- 4. 同步设备类型 ----
    try:
        from backend.services.knowledge_management.device_sync_svc import device_sync_svc
        db2 = next(get_db())
        try:
            result = device_sync_svc.sync_device_types(db2)
            logger.info("启动时设备类型同步完成: created=%s, disabled=%s, recovered=%s",
                        result.get("created", 0), result.get("disabled", 0), result.get("recovered", 0))
        finally:
            db2.close()
    except Exception as e:
        logger.warning("启动时设备类型同步失败（AQA数据库可能不可达）: %s", e)
