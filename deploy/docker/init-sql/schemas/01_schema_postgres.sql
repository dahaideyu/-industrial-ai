-- Schema-only dump of database `postgres` (from remote 10.1.2.227, via psycopg2 introspection — pg_dump not available on this machine).
-- 幂等：全部 IF NOT EXISTS，可重复执行。

CREATE EXTENSION IF NOT EXISTS "timescaledb";

CREATE TABLE IF NOT EXISTS alarm_analysis_daily (
    id SERIAL,
    report_date DATE NOT NULL,
    device_id VARCHAR(50),
    statistics JSONB,
    analysis JSONB,
    query_params JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS alarm_analysis_monthly (
    id SERIAL,
    report_date DATE NOT NULL,
    device_id VARCHAR(50),
    statistics JSONB,
    analysis JSONB,
    query_params JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS alarm_analysis_weekly (
    id SERIAL,
    report_date DATE NOT NULL,
    device_id VARCHAR(50),
    statistics JSONB,
    analysis JSONB,
    query_params JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS analysis_job_config (
    id SERIAL,
    job_name VARCHAR(50) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    interval_seconds INTEGER NOT NULL DEFAULT 3600,
    enabled BOOLEAN DEFAULT true,
    last_manual_trigger TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS analysis_job_log (
    id SERIAL,
    job_run_id INTEGER,
    log_level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS analysis_job_run (
    id SERIAL,
    job_name VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'::character varying,
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    duration_seconds INTEGER,
    result_summary JSONB,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS dev_device_param (
    id BIGINT,
    name VARCHAR(255),
    device_type VARCHAR(20),
    description VARCHAR(255),
    type VARCHAR(20),
    accuracy VARCHAR(10),
    unit VARCHAR(20),
    device_id BIGINT,
    device_no VARCHAR(40),
    max_value INTEGER,
    min_value INTEGER,
    create_time TIMESTAMP,
    value VARCHAR(255),
    status VARCHAR(10),
    report_time TIMESTAMP,
    gather_time TIMESTAMP,
    qualified_value VARCHAR(10),
    batch_no VARCHAR(255),
    show_flag SMALLINT DEFAULT 0,
    dzc_flag SMALLINT DEFAULT 0,
    source VARCHAR(20),
    report_type VARCHAR(20),
    report_cycle INTEGER,
    report_cycle_unit VARCHAR(10),
    gateway_point_uid VARCHAR(255),
    sort_num INTEGER,
    north_driver_uid VARCHAR(255),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS dev_device_param_detail_record (
    id BIGINT,
    device_code VARCHAR(50),
    device_name VARCHAR(50),
    p_name VARCHAR(50),
    p_value VARCHAR(50),
    report_time TIMESTAMP,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    gather_time TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS dev_device_status (
    id BIGINT,
    name VARCHAR(50) NOT NULL,
    code INTEGER NOT NULL,
    serial_code INTEGER NOT NULL,
    color VARCHAR(20),
    icon VARCHAR(100),
    status VARCHAR(20) NOT NULL,
    alarm SMALLINT,
    close_alarm SMALLINT,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS dev_device_status_record (
    id INTEGER,
    device_id INTEGER,
    status SMALLINT,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration BIGINT,
    order_number VARCHAR(255),
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_start_time TIMESTAMP,
    qualified_count INTEGER DEFAULT 0,
    unqualified_count INTEGER DEFAULT 0,
    report_qualified_count INTEGER DEFAULT 0,
    report_unqualified_count INTEGER DEFAULT 0,
    ct_serial_no INTEGER,
    product_id BIGINT,
    report_ct NUMERIC(10,2)
);

CREATE TABLE IF NOT EXISTS device_alarm_info (
    device_id VARCHAR(255) NOT NULL,
    device_status VARCHAR(255),
    point_uid INTEGER,
    point_id VARCHAR(255) NOT NULL,
    value_type VARCHAR(255),
    point_value INTEGER NOT NULL,
    point_value_full NUMERIC(14,4),
    point_time TIMESTAMP NOT NULL,
    upload_cycle INTEGER,
    south_driver_name VARCHAR(255),
    time TIMESTAMP,
    load_time TIMESTAMP,
    raw_json JSONB
);

CREATE TABLE IF NOT EXISTS device_diagnosis (
    device_code VARCHAR(64),
    eval_date DATE,
    diagnosis TEXT,
    risk_hint VARCHAR(16),
    trace JSONB,
    rounds SMALLINT,
    elapsed_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (device_code, eval_date)
);

-- 电表能耗点位表，结构与 device_alarm_info 类似（无 value_type，point_value 是
-- numeric 连续量），由 mqtt_etl 的 EnergyMessageParser 写入。这里也要建它（而不是只靠
-- mqtt_etl 自己的 _ensure_schema），因为 backend 的 get_param_data/get_param_data_aggregated
-- 会 UNION 这张表——mqtt-etl 容器没起过的环境里表不存在会导致查询报错。
CREATE TABLE IF NOT EXISTS device_energy_info (
    device_id VARCHAR(255) NOT NULL,
    device_status VARCHAR(255),
    point_uid INTEGER,
    point_id VARCHAR(255) NOT NULL,
    point_value NUMERIC(14,4),
    point_time TIMESTAMP NOT NULL,
    upload_cycle INTEGER,
    south_driver_name VARCHAR(255),
    time TIMESTAMP,
    load_time TIMESTAMP,
    raw_json JSONB
);

-- device_id 是 varchar 设备编码（如 102000000995，与 device_alarm_info.device_id、
-- dev_device_param.device_no 同一套编码），不是自增整型；id 对应 MySQL dev_device.id。
-- 数据由 deploy/docker/scripts/sync_device_dict.py 从 MySQL 同步（首次部署手动执行）。
CREATE TABLE IF NOT EXISTS device_info (
    device_id VARCHAR(64) NOT NULL,
    device_name VARCHAR(255) NOT NULL,
    id INTEGER,
    PRIMARY KEY (device_id)
);

-- 电表 → 对应生产设备 的映射关系（贝特瑞现场：一个生产设备对应一个独立电表，
-- 两者在 device_info 里各是一条设备记录）。
-- 数据由 deploy/docker/scripts/sync_btr_device_dict.py 导入。
CREATE TABLE IF NOT EXISTS device_energy_meter (
    meter_device_id VARCHAR(64) NOT NULL,
    production_device_id VARCHAR(64) NOT NULL REFERENCES device_info(device_id),
    PRIMARY KEY (meter_device_id)
);

CREATE TABLE IF NOT EXISTS device_param_alert_diagnosis (
    device_code VARCHAR(64) NOT NULL,
    metric VARCHAR(128) NOT NULL,
    stage SMALLINT,
    eval_date DATE NOT NULL,
    baseline_days SMALLINT NOT NULL,
    display_name VARCHAR(256),
    severity VARCHAR(12),
    direction VARCHAR(8),
    problem TEXT,
    kb_evidence TEXT,
    kb_refs JSONB,
    ok BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS device_param_analysis_log (
    id SERIAL,
    device_code VARCHAR(64) NOT NULL,
    device_name VARCHAR(128),
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    running_only BOOLEAN,
    analysis TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS device_param_daily_stats (
    device_code VARCHAR(64) NOT NULL,
    metric VARCHAR(128) NOT NULL,
    stat_date DATE NOT NULL,
    stage SMALLINT,
    running_only BOOLEAN NOT NULL DEFAULT true,
    cnt BIGINT NOT NULL,
    sum_val DOUBLE PRECISION,
    sum_sq DOUBLE PRECISION,
    vmin DOUBLE PRECISION,
    vmax DOUBLE PRECISION,
    mean DOUBLE PRECISION,
    std DOUBLE PRECISION,
    median DOUBLE PRECISION,
    p25 DOUBLE PRECISION,
    p75 DOUBLE PRECISION,
    mad DOUBLE PRECISION,
    first_val DOUBLE PRECISION,
    last_val DOUBLE PRECISION,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS device_param_drift_config (
    device_code VARCHAR(64),
    config JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT now(),
    updated_by VARCHAR(128),
    PRIMARY KEY (device_code)
);

CREATE TABLE IF NOT EXISTS device_param_insight (
    device_code VARCHAR(64),
    kind VARCHAR(24),
    params JSONB,
    payload JSONB,
    eval_date DATE,
    computed_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (device_code, kind)
);

CREATE TABLE IF NOT EXISTS device_param_profile (
    device_code VARCHAR(64),
    p_name VARCHAR(128),
    profile JSONB NOT NULL,
    confirmed BOOLEAN NOT NULL DEFAULT false,
    updated_by VARCHAR(128),
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (device_code, p_name)
);

CREATE TABLE IF NOT EXISTS device_param_trend_alert (
    device_code VARCHAR(64) NOT NULL,
    metric VARCHAR(128) NOT NULL,
    stage SMALLINT,
    eval_date DATE NOT NULL,
    baseline_days SMALLINT NOT NULL,
    running_only BOOLEAN NOT NULL DEFAULT true,
    display_name VARCHAR(256),
    unit VARCHAR(32),
    baseline_median DOUBLE PRECISION,
    baseline_mad DOUBLE PRECISION,
    recent_median DOUBLE PRECISION,
    recent_n SMALLINT,
    change_pct DOUBLE PRECISION,
    robust_z DOUBLE PRECISION,
    mk_trend VARCHAR(8),
    mk_p DOUBLE PRECISION,
    sen_slope DOUBLE PRECISION,
    direction VARCHAR(8),
    severity VARCHAR(12),
    sample_days SMALLINT,
    note TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS device_stage_state_config (
    device_code VARCHAR(64),
    config JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT now(),
    updated_by VARCHAR(128),
    PRIMARY KEY (device_code)
);

CREATE TABLE IF NOT EXISTS point_info (
    point_id VARCHAR(255) NOT NULL,
    point_name VARCHAR(255) NOT NULL,
    belong_devide VARCHAR(255) NOT NULL,
    remark VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS sys_user (
    id SERIAL,
    username VARCHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(128),
    role VARCHAR(32) NOT NULL DEFAULT 'admin'::character varying,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS system_job_config (
    job_id VARCHAR(64),
    cron VARCHAR(64),
    enabled BOOLEAN DEFAULT true,
    updated_at TIMESTAMP DEFAULT now(),
    updated_by VARCHAR(128),
    PRIMARY KEY (job_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS alarm_analysis_daily_report_date_device_id_key ON public.alarm_analysis_daily USING btree (report_date, device_id);
CREATE INDEX IF NOT EXISTS idx_alarm_daily_date ON public.alarm_analysis_daily USING btree (report_date);
CREATE UNIQUE INDEX IF NOT EXISTS alarm_analysis_monthly_report_date_device_id_key ON public.alarm_analysis_monthly USING btree (report_date, device_id);
CREATE INDEX IF NOT EXISTS idx_alarm_monthly_date ON public.alarm_analysis_monthly USING btree (report_date);
CREATE UNIQUE INDEX IF NOT EXISTS alarm_analysis_weekly_report_date_device_id_key ON public.alarm_analysis_weekly USING btree (report_date, device_id);
CREATE INDEX IF NOT EXISTS idx_alarm_weekly_date ON public.alarm_analysis_weekly USING btree (report_date);
CREATE UNIQUE INDEX IF NOT EXISTS analysis_job_config_job_name_key ON public.analysis_job_config USING btree (job_name);
CREATE INDEX IF NOT EXISTS idx_job_log_job_run_id ON public.analysis_job_log USING btree (job_run_id);
CREATE INDEX IF NOT EXISTS idx_job_run_name_status ON public.analysis_job_run USING btree (job_name, status);
CREATE INDEX IF NOT EXISTS idx_job_run_start_time ON public.analysis_job_run USING btree (start_time);
CREATE INDEX IF NOT EXISTS idx_dev_device_param_device_no ON public.dev_device_param USING btree (device_no);
CREATE INDEX IF NOT EXISTS idx_dev_device_param_device_no_name ON public.dev_device_param USING btree (device_no, name);
CREATE INDEX IF NOT EXISTS idx_dev_device_param_name ON public.dev_device_param USING btree (name);
CREATE INDEX IF NOT EXISTS dev_device_param_detail_record_gather_time_idx ON public.dev_device_param_detail_record USING btree (gather_time DESC);
CREATE INDEX IF NOT EXISTS idx_dev_device_param_detail_record_code_name_time ON public.dev_device_param_detail_record USING btree (device_code, p_name, gather_time DESC);
CREATE INDEX IF NOT EXISTS idx_dev_device_param_detail_record_code_time ON public.dev_device_param_detail_record USING btree (device_code, gather_time DESC);
CREATE INDEX IF NOT EXISTS idx_dev_device_param_detail_record_id ON public.dev_device_param_detail_record USING btree (id);
CREATE INDEX IF NOT EXISTS idx_dev_device_status_code ON public.dev_device_status USING btree (code);
CREATE INDEX IF NOT EXISTS dev_device_status_record_start_time_idx ON public.dev_device_status_record USING btree (start_time DESC);
CREATE INDEX IF NOT EXISTS idx_dev_device_status_record_device_id ON public.dev_device_status_record USING btree (device_id);
CREATE INDEX IF NOT EXISTS idx_dev_device_status_record_device_start ON public.dev_device_status_record USING btree (device_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_dev_device_status_record_id ON public.dev_device_status_record USING btree (id);
CREATE INDEX IF NOT EXISTS idx_dev_device_status_record_start_time ON public.dev_device_status_record USING btree (start_time DESC);
CREATE INDEX IF NOT EXISTS device_alarm_info_device_id_point_time_idx ON public.device_alarm_info USING btree (device_id, point_time DESC);
CREATE INDEX IF NOT EXISTS device_alarm_info_point_time_idx ON public.device_alarm_info USING btree (point_time DESC);
CREATE INDEX IF NOT EXISTS ix_device_diagnosis_date ON public.device_diagnosis USING btree (eval_date, risk_hint);
CREATE UNIQUE INDEX IF NOT EXISTS uq_device_param_alert_diagnosis ON public.device_param_alert_diagnosis USING btree (device_code, metric, COALESCE((stage)::integer, '-1'::integer), eval_date, baseline_days);
CREATE INDEX IF NOT EXISTS ix_device_param_analysis_log_device ON public.device_param_analysis_log USING btree (device_code, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_device_param_daily_stats_lookup ON public.device_param_daily_stats USING btree (device_code, metric, stat_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_device_param_daily_stats ON public.device_param_daily_stats USING btree (device_code, metric, stat_date, COALESCE((stage)::integer, '-1'::integer), running_only);
CREATE INDEX IF NOT EXISTS ix_device_param_trend_alert_lookup ON public.device_param_trend_alert USING btree (device_code, eval_date, severity);
CREATE UNIQUE INDEX IF NOT EXISTS uq_device_param_trend_alert ON public.device_param_trend_alert USING btree (device_code, metric, COALESCE((stage)::integer, '-1'::integer), eval_date, baseline_days, running_only);
CREATE UNIQUE INDEX IF NOT EXISTS point_info_unique ON public.point_info USING btree (point_id, belong_devide);
CREATE UNIQUE INDEX IF NOT EXISTS sys_user_username_key ON public.sys_user USING btree (username);

ALTER TABLE analysis_job_log DROP CONSTRAINT IF EXISTS analysis_job_log_job_run_id_fkey;
ALTER TABLE analysis_job_log ADD CONSTRAINT analysis_job_log_job_run_id_fkey FOREIGN KEY (job_run_id) REFERENCES analysis_job_run(id);

SELECT create_hypertable('dev_device_param_detail_record', 'gather_time', chunk_time_interval => INTERVAL '604800 seconds', if_not_exists => TRUE);
SELECT create_hypertable('dev_device_status_record', 'start_time', chunk_time_interval => INTERVAL '604800 seconds', if_not_exists => TRUE);
SELECT create_hypertable('device_alarm_info', 'point_time', chunk_time_interval => INTERVAL '604800 seconds', if_not_exists => TRUE);
SELECT add_dimension('device_alarm_info', 'device_id', number_partitions => 8, if_not_exists => TRUE);
SELECT create_hypertable('device_energy_info', 'point_time', chunk_time_interval => INTERVAL '604800 seconds', if_not_exists => TRUE);
SELECT add_dimension('device_energy_info', 'device_id', number_partitions => 8, if_not_exists => TRUE);

-- ============================================================
-- 连续聚合（小时级预计算）：>3h 聚合查询直接读视图，不扫原始表
-- ============================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS device_alarm_hourly
WITH (timescaledb.continuous) AS
SELECT
    device_id,
    point_id,
    time_bucket('1 hour', point_time) AS bucket,
    AVG(COALESCE(point_value_full, point_value::numeric)) AS avg_val,
    MIN(COALESCE(point_value_full, point_value::numeric)) AS min_val,
    MAX(COALESCE(point_value_full, point_value::numeric)) AS max_val,
    SUM(COALESCE(point_value_full, point_value::numeric)) AS sum_val,
    COUNT(*) AS cnt
FROM device_alarm_info
WHERE point_value_full IS NOT NULL OR point_value IS NOT NULL
GROUP BY device_id, point_id, bucket;

CREATE MATERIALIZED VIEW IF NOT EXISTS device_energy_hourly
WITH (timescaledb.continuous) AS
SELECT
    device_id,
    point_id,
    time_bucket('1 hour', point_time) AS bucket,
    AVG(point_value) AS avg_val,
    MIN(point_value) AS min_val,
    MAX(point_value) AS max_val,
    SUM(point_value) AS sum_val,
    COUNT(*) AS cnt
FROM device_energy_info
WHERE point_value IS NOT NULL
GROUP BY device_id, point_id, bucket;

SELECT add_continuous_aggregate_policy('device_alarm_hourly',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('device_energy_hourly',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);
