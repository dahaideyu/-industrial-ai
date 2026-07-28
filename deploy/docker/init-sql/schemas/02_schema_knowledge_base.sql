-- Schema-only dump of database `knowledge_base` (from remote 10.1.2.227, via psycopg2 introspection — pg_dump not available on this machine).
-- 幂等：全部 IF NOT EXISTS，可重复执行。

CREATE TABLE IF NOT EXISTS kb_qa_messages (
    id SERIAL,
    session_id VARCHAR(36) NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    used_kb_ids TEXT,
    rag_references TEXT,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS kb_qa_sessions (
    id VARCHAR(36),
    user_id INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS kb_qa_user_chat_assistants (
    id SERIAL,
    user_id INTEGER NOT NULL,
    ragflow_chat_id VARCHAR(100) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    last_used_at TIMESTAMP NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS knb_collection_plans (
    id UUID,
    knowledge_base_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL,
    priority VARCHAR(20) NOT NULL,
    due_date VARCHAR(20),
    overall_progress INTEGER,
    overall_score INTEGER,
    overall_analysis TEXT,
    overall_stats JSONB,
    evaluated_at TIMESTAMPTZ,
    plan_type VARCHAR(20) NOT NULL,
    sync_type VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS knb_collection_targets (
    id UUID,
    knowledge_base_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    attributes JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS knb_document_categories (
    id UUID,
    knowledge_base_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    requirement_desc TEXT NOT NULL,
    preset_category_id UUID,
    parent_id UUID,
    sort_order INTEGER NOT NULL,
    is_custom BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS knb_document_versions (
    id UUID,
    document_id UUID NOT NULL,
    version_label VARCHAR(20),
    original_filename VARCHAR(500),
    storage_path VARCHAR(1000),
    file_size BIGINT,
    file_hash VARCHAR(128),
    status VARCHAR(30) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    chunk_method VARCHAR(20),
    extracted_text TEXT,
    pdf_preview_path VARCHAR(1000),
    parent_document_id UUID,
    auto_generated BOOLEAN NOT NULL,
    ai_relevance_score INTEGER,
    ai_quality_score INTEGER,
    ai_relevance_remark TEXT,
    ai_quality_remark TEXT,
    rejected_reason TEXT,
    is_current BOOLEAN NOT NULL,
    publish_status VARCHAR(20),
    uploaded_by VARCHAR(100),
    convert_status VARCHAR(20),
    extract_status VARCHAR(20),
    parse_status VARCHAR(20),
    drawing_parse_status VARCHAR(20),
    drawing_parse_progress INTEGER,
    drawing_parse_step VARCHAR(100),
    drawing_parse_detail TEXT,
    has_stamp BOOLEAN,
    has_signature BOOLEAN,
    valid_from DATE,
    valid_until DATE,
    compliance_score INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS knb_documents (
    id UUID,
    plan_item_id UUID NOT NULL,
    display_name VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS knb_kb_type_states (
    kb_type VARCHAR(30),
    enabled BOOLEAN NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    updated_by VARCHAR(100),
    PRIMARY KEY (kb_type)
);

CREATE TABLE IF NOT EXISTS knb_knowledge_bases (
    id UUID,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    rag_dataset_id VARCHAR(100),
    vector_model VARCHAR(100),
    chunk_method VARCHAR(50),
    parser_config JSONB,
    device_type VARCHAR(255),
    status VARCHAR(20) NOT NULL,
    tags JSONB,
    sync_type VARCHAR(20) NOT NULL,
    synced_at TIMESTAMPTZ,
    kb_type VARCHAR(20) NOT NULL,
    overall_progress INTEGER,
    overall_score INTEGER,
    enabled BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS knb_operation_logs (
    id UUID,
    user_id VARCHAR(100),
    username VARCHAR(100) NOT NULL,
    real_name VARCHAR(100),
    operation VARCHAR(50) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id VARCHAR(36),
    target_name VARCHAR(500),
    kb_id VARCHAR(36),
    remark TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS knb_plan_items (
    id UUID,
    plan_id UUID NOT NULL,
    category_id UUID NOT NULL,
    target_id UUID NOT NULL,
    requirement_override TEXT,
    priority VARCHAR(20) NOT NULL DEFAULT 'normal'::character varying,
    due_date DATE,
    overall_completion TEXT,
    overall_score INTEGER,
    overall_status VARCHAR(20),
    evaluation_detail JSONB,
    evaluated_at TIMESTAMPTZ,
    not_applicable BOOLEAN NOT NULL,
    not_applicable_by VARCHAR(100),
    not_applicable_at TIMESTAMPTZ,
    not_applicable_reason TEXT,
    is_custom BOOLEAN NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS knb_preset_categories (
    id UUID,
    parent_id UUID,
    name VARCHAR(255) NOT NULL,
    requirement_desc TEXT NOT NULL,
    category_type VARCHAR(50) NOT NULL,
    level INTEGER NOT NULL,
    is_leaf BOOLEAN NOT NULL,
    sort_order INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL,
    version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS knb_rag_document_map (
    id UUID,
    version_id UUID NOT NULL,
    rag_document_id VARCHAR(100) NOT NULL,
    rag_dataset_id VARCHAR(100) NOT NULL,
    is_current BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_kb_qa_messages_created_at ON public.kb_qa_messages USING btree (created_at);
CREATE INDEX IF NOT EXISTS ix_kb_qa_messages_session_id ON public.kb_qa_messages USING btree (session_id);
CREATE INDEX IF NOT EXISTS ix_kb_qa_sessions_user_id ON public.kb_qa_sessions USING btree (user_id);
CREATE INDEX IF NOT EXISTS ix_kb_qa_user_chat_assistants_last_used_at ON public.kb_qa_user_chat_assistants USING btree (last_used_at);
CREATE UNIQUE INDEX IF NOT EXISTS ix_kb_qa_user_chat_assistants_user_id ON public.kb_qa_user_chat_assistants USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_oplog_target ON public.knb_operation_logs USING btree (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_oplog_time ON public.knb_operation_logs USING btree (created_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_oplog_user ON public.knb_operation_logs USING btree (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS knb_plan_items_plan_id_category_id_target_id_key ON public.knb_plan_items USING btree (plan_id, category_id, target_id);
CREATE UNIQUE INDEX IF NOT EXISTS knb_rag_document_map_version_id_key ON public.knb_rag_document_map USING btree (version_id);

ALTER TABLE knb_preset_categories DROP CONSTRAINT IF EXISTS knb_preset_categories_parent_id_fkey;
ALTER TABLE knb_preset_categories ADD CONSTRAINT knb_preset_categories_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES knb_preset_categories(id);
ALTER TABLE knb_document_categories DROP CONSTRAINT IF EXISTS knb_document_categories_knowledge_base_id_fkey;
ALTER TABLE knb_document_categories ADD CONSTRAINT knb_document_categories_knowledge_base_id_fkey FOREIGN KEY (knowledge_base_id) REFERENCES knb_knowledge_bases(id) ON DELETE CASCADE;
ALTER TABLE knb_collection_targets DROP CONSTRAINT IF EXISTS knb_collection_targets_knowledge_base_id_fkey;
ALTER TABLE knb_collection_targets ADD CONSTRAINT knb_collection_targets_knowledge_base_id_fkey FOREIGN KEY (knowledge_base_id) REFERENCES knb_knowledge_bases(id) ON DELETE CASCADE;
ALTER TABLE knb_collection_plans DROP CONSTRAINT IF EXISTS knb_collection_plans_knowledge_base_id_fkey;
ALTER TABLE knb_collection_plans ADD CONSTRAINT knb_collection_plans_knowledge_base_id_fkey FOREIGN KEY (knowledge_base_id) REFERENCES knb_knowledge_bases(id) ON DELETE CASCADE;
ALTER TABLE kb_qa_messages DROP CONSTRAINT IF EXISTS kb_qa_messages_session_id_fkey;
ALTER TABLE kb_qa_messages ADD CONSTRAINT kb_qa_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES kb_qa_sessions(id);
ALTER TABLE knb_plan_items DROP CONSTRAINT IF EXISTS knb_plan_items_plan_id_fkey;
ALTER TABLE knb_plan_items ADD CONSTRAINT knb_plan_items_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES knb_collection_plans(id) ON DELETE CASCADE;
ALTER TABLE knb_plan_items DROP CONSTRAINT IF EXISTS knb_plan_items_category_id_fkey;
ALTER TABLE knb_plan_items ADD CONSTRAINT knb_plan_items_category_id_fkey FOREIGN KEY (category_id) REFERENCES knb_document_categories(id);
ALTER TABLE knb_plan_items DROP CONSTRAINT IF EXISTS knb_plan_items_target_id_fkey;
ALTER TABLE knb_plan_items ADD CONSTRAINT knb_plan_items_target_id_fkey FOREIGN KEY (target_id) REFERENCES knb_collection_targets(id);
ALTER TABLE knb_documents DROP CONSTRAINT IF EXISTS knb_documents_plan_item_id_fkey;
ALTER TABLE knb_documents ADD CONSTRAINT knb_documents_plan_item_id_fkey FOREIGN KEY (plan_item_id) REFERENCES knb_plan_items(id) ON DELETE CASCADE;
ALTER TABLE knb_document_versions DROP CONSTRAINT IF EXISTS knb_document_versions_document_id_fkey;
ALTER TABLE knb_document_versions ADD CONSTRAINT knb_document_versions_document_id_fkey FOREIGN KEY (document_id) REFERENCES knb_documents(id) ON DELETE CASCADE;
ALTER TABLE knb_document_versions DROP CONSTRAINT IF EXISTS knb_document_versions_parent_document_id_fkey;
ALTER TABLE knb_document_versions ADD CONSTRAINT knb_document_versions_parent_document_id_fkey FOREIGN KEY (parent_document_id) REFERENCES knb_documents(id);
ALTER TABLE knb_rag_document_map DROP CONSTRAINT IF EXISTS knb_rag_document_map_version_id_fkey;
ALTER TABLE knb_rag_document_map ADD CONSTRAINT knb_rag_document_map_version_id_fkey FOREIGN KEY (version_id) REFERENCES knb_document_versions(id) ON DELETE CASCADE;
