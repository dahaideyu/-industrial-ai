-- 5分钟粒度连续聚合：支撑特征视图"滑动均值/滑动标准差/变化率"的代数重建
-- 列结构复刻 device_alarm_hourly/device_energy_hourly，多存一列 sum_sq 备用
-- (当前滑动均值/标准差/变化率的现有前端语义只需要 avg_val 一列即可精确复刻，
--  sum_sq 是为以后如果要引入"窗口内原始点真实标准差"这个新指标留的余量)
--
-- WITH NO DATA：不做默认全历史回填。5分钟粒度回填9+个月历史体量太大且没意义——
-- 特征视图最多看7天，长期趋势已有 hourly CAGG / device_param_daily_stats 覆盖。
-- 建好后只显式物化最近30天。

CREATE MATERIALIZED VIEW IF NOT EXISTS device_alarm_5min
WITH (timescaledb.continuous) AS
SELECT
    device_id,
    point_id,
    time_bucket('5 minutes', point_time) AS bucket,
    AVG(COALESCE(point_value_full, point_value::numeric)) AS avg_val,
    MIN(COALESCE(point_value_full, point_value::numeric)) AS min_val,
    MAX(COALESCE(point_value_full, point_value::numeric)) AS max_val,
    SUM(COALESCE(point_value_full, point_value::numeric)) AS sum_val,
    SUM(POWER(COALESCE(point_value_full, point_value::numeric), 2)) AS sum_sq,
    COUNT(*) AS cnt
FROM device_alarm_info
WHERE point_value_full IS NOT NULL OR point_value IS NOT NULL
GROUP BY device_id, point_id, bucket
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS device_energy_5min
WITH (timescaledb.continuous) AS
SELECT
    device_id,
    point_id,
    time_bucket('5 minutes', point_time) AS bucket,
    AVG(point_value) AS avg_val,
    MIN(point_value) AS min_val,
    MAX(point_value) AS max_val,
    SUM(point_value) AS sum_val,
    SUM(POWER(point_value, 2)) AS sum_sq,
    COUNT(*) AS cnt
FROM device_energy_info
WHERE point_value IS NOT NULL
GROUP BY device_id, point_id, bucket
WITH NO DATA;

-- 只显式物化最近30天（够特征视图7天用 + 留验证余量），不动更早历史
-- point_time 是 timestamp without time zone，now() 是 timestamptz，
-- refresh_continuous_aggregate 要求窗口参数类型跟 bucket 列一致，需显式转换，
-- 否则报 "invalid time argument type" 中断脚本
CALL refresh_continuous_aggregate('device_alarm_5min', now()::timestamp - INTERVAL '30 days', now()::timestamp);
CALL refresh_continuous_aggregate('device_energy_5min', now()::timestamp - INTERVAL '30 days', now()::timestamp);

-- 近实时刷新：5分钟跑一次；end_offset 10min 缓冲迟到数据。
-- 即使刷新有几分钟delay，TimescaleDB 默认开启的"实时聚合"会对物化窗口外的数据
-- 自动现算兜底，查询到的仍是准实时结果，不会出现"看不到最近几分钟"的空洞。
SELECT add_continuous_aggregate_policy('device_alarm_5min',
    start_offset => INTERVAL '2 hours',
    end_offset => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('device_energy_5min',
    start_offset => INTERVAL '2 hours',
    end_offset => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE);

-- 保留策略：这是"衍生统计"的保留策略，不是删原始数据——device_alarm_info /
-- device_energy_info 原始表完全不受影响。这里只是让分钟级桶不会无限累积：14天
-- 和 Phase 1 的 compress_after 用同一套"7天查询窗口+安全余量"逻辑，超过14天的
-- 分钟级桶反正没人查（长期趋势另有 hourly CAGG / daily_stats 兜底）。
SELECT add_retention_policy('device_alarm_5min', INTERVAL '14 days', if_not_exists => TRUE);
SELECT add_retention_policy('device_energy_5min', INTERVAL '14 days', if_not_exists => TRUE);
