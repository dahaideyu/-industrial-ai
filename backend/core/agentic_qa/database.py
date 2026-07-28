# cython: annotation_typing=False, infer_types=False, language_level=3
"""数据库引擎和会话工厂 — 统一使用 PostgreSQL knowledge_base 库"""
import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from backend.core.agentic_qa.config import settings
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("core.database")


def _get_pg_url() -> str:
    """从环境变量构造 PostgreSQL 连接串（统一使用 PG_*）"""
    host = os.getenv("PG_HOST", "127.0.0.1")
    port = os.getenv("PG_PORT", "5432")
    db = os.getenv("PG_DB", "knowledge_base")
    user = os.getenv("PG_USER", "zxzz")
    password = os.getenv("PG_PASSWORD", "")
    encoded_password = quote_plus(password)
    return f"postgresql://{user}:{encoded_password}@{host}:{port}/{db}"


# 如果配置的仍是 SQLite（或为空），自动切换到 PostgreSQL
_raw_url = settings.database_url
if not _raw_url or _raw_url.startswith("sqlite"):
    _raw_url = _get_pg_url()
    logger.info("AQA 数据库已切换为 PostgreSQL: %s@%s", _raw_url.split("://")[1].split("@")[0], _raw_url.split("@")[1].split("/")[0])

engine = create_engine(_raw_url, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db():
    """创建所有表并执行列迁移（首次启动时调用）"""
    import backend.services.agentic_qa.models.user           # noqa: F401 — 确保模型被注册
    import backend.services.agentic_qa.models.session        # noqa: F401
    import backend.services.agentic_qa.models.message        # noqa: F401
    import backend.services.agentic_qa.models.entity_config  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_columns()
    logger.info("AQA database tables created/verified")


def _migrate_columns():
    """为旧数据库添加缺失的列（PG 用 information_schema 检测）"""
    try:
        with engine.connect() as conn:
            # 获取 messages 表现有列
            result = conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'messages'")
            )
            existing = {row[0] for row in result}

            new_columns = [
                ("clarification_groups", "TEXT"),
                ("followups", "TEXT"),
                ("thinking", "TEXT"),
            ]
            for col_name, col_type in new_columns:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}"))
                    logger.info("[migrate] Added column messages.%s", col_name)
            conn.commit()
    except Exception as e:
        logger.warning("[migrate] Column migration skipped: %s", e)


def get_db():
    """FastAPI 依赖：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
