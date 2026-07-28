-- TimescaleDB 连续聚合：小时级预计算，>3h 的聚合查询直接从物化视图读，不再扫原始表
-- 基于步骤二的 point_value_full 列，无需 LATERAL JSONB 拆包

-- device_alarm_info 小时级连续聚合（工艺点位）
-- COALESCE(point_value_full, point_value) 兼容回填前的 INTEGER 精度历史数据
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

-- device_energy_info 小时级连续聚合（能耗点位，point_value 已是 NUMERIC 全精度）
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

-- 自动刷新策略：后台每小时刷新一次，处理 1h 前到 1d 前的数据
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
