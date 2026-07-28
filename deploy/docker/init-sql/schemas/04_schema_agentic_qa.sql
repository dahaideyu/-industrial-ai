-- ============================================
-- 04_schema_agentic_qa.sql
-- Agentic QA 应用数据表（原 SQLite → 迁移至 PostgreSQL knowledge_base）
-- 表名前缀：无特殊前缀（users / sessions / messages / entity_configs）
-- 注意：SQLAlchemy Base.metadata.create_all() 也会在应用启动时自动建表，
--       本脚本用于首次部署或手动重建场景，与 create_all 幂等兼容。
-- ============================================

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(64)  NOT NULL UNIQUE,
    password_hash   VARCHAR(128) NOT NULL,
    role            VARCHAR(16)  NOT NULL DEFAULT 'user',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 会话表
CREATE TABLE IF NOT EXISTS sessions (
    id              VARCHAR(64)  PRIMARY KEY,
    user_id         INTEGER      NOT NULL,
    title           VARCHAR(256) NOT NULL DEFAULT '新对话',
    memory          TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 消息表（关联 sessions，级联删除）
CREATE TABLE IF NOT EXISTS messages (
    id                      VARCHAR(64) PRIMARY KEY,
    session_id              VARCHAR(64) NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role                    VARCHAR(16) NOT NULL,
    content                 TEXT,
    sql                     TEXT,
    results                 TEXT,        -- JSON
    steps                   TEXT,        -- JSON
    intent                  VARCHAR(32),
    source                  VARCHAR(32),
    analysis_chart          TEXT,        -- JSON
    analysis_suggestions    TEXT,        -- JSON
    result_groups           TEXT,        -- JSON
    feedback_status         VARCHAR(16),
    feedback_text           TEXT,
    entity_candidates       TEXT,        -- JSON
    needs_clarification     BOOLEAN      NOT NULL DEFAULT FALSE,
    clarification_options   TEXT,        -- JSON
    clarification_groups    TEXT,        -- JSON
    followups               TEXT,        -- JSON
    thinking                TEXT,
    rag_thinking            TEXT,
    rag_references          TEXT,        -- JSON
    timestamp               INTEGER      NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);

-- 实体配置表
CREATE TABLE IF NOT EXISTS entity_configs (
    id              SERIAL PRIMARY KEY,
    entity_type     VARCHAR(64)  NOT NULL UNIQUE,
    label           VARCHAR(64)  NOT NULL,
    table_name      VARCHAR(128) NOT NULL,
    search_columns  TEXT         NOT NULL DEFAULT '[]',   -- JSON array
    label_column    VARCHAR(64)  NOT NULL DEFAULT 'name',
    value_column    VARCHAR(64)  NOT NULL DEFAULT 'id',
    context_columns TEXT         NOT NULL DEFAULT '[]',   -- JSON array
    keyword_hints   TEXT         NOT NULL DEFAULT '[]',   -- JSON array
    filter_condition TEXT        NOT NULL DEFAULT 'del_flag = 0',
    is_indexed      BOOLEAN      NOT NULL DEFAULT FALSE
);
