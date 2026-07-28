-- AI 报告持久化表（从 SQLite ai_analysis_report 迁移至 PostgreSQL）
-- 幂等：全部 IF NOT EXISTS，可重复执行

CREATE TABLE IF NOT EXISTS ai_analysis_report (
    id                      SERIAL PRIMARY KEY,
    report_code             TEXT        NOT NULL,
    title                   TEXT,
    period_label            TEXT,
    request_payload         TEXT,
    agent_response_raw      TEXT,
    agent_response_processed TEXT,
    markdown_content        TEXT,
    summary_markdown        TEXT,
    kb_report_markdown      TEXT,
    knowledge_base_payload  TEXT,
    status                  INTEGER     NOT NULL DEFAULT 0,
    error_message           TEXT,
    create_time             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    workshop_id             INTEGER     NOT NULL DEFAULT 0,
    date_type               TEXT        NOT NULL DEFAULT '',
    once_qualified_flag     INTEGER     NOT NULL DEFAULT 0,
    class_id                INTEGER     NOT NULL DEFAULT 0,
    procedure_id            INTEGER     NOT NULL DEFAULT 0,
    report_date             TEXT        NOT NULL DEFAULT '',
    CONSTRAINT uq_ai_analysis_report UNIQUE (
        report_code, workshop_id, date_type,
        once_qualified_flag, class_id, procedure_id, report_date
    )
);

-- 按 report_code + create_time 查询（报告列表按时间排序）
CREATE INDEX IF NOT EXISTS idx_report_code_time
    ON ai_analysis_report(report_code, create_time);
