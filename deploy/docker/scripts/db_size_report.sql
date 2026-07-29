-- 数据库容量体检：决定"要不要加盘、加多大"之前先跑这个，拿到真实数字再决策。
--
-- 用法：
--   docker exec -i postgresql psql -U zxzz -d knowledge_base -f - < db_size_report.sql
--   或： docker exec -it postgresql psql -U zxzz -d knowledge_base
--        然后 \i /path/db_size_report.sql
--
-- 关注三件事：① 总量多大 ② 传感器原始表占比多少 ③ 压缩到底生效没有

\echo '===== 1. 数据库总体积 ====='
SELECT pg_size_pretty(pg_database_size(current_database())) AS db_total;

\echo ''
\echo '===== 2. 最占空间的 15 张表（含索引/TOAST）====='
SELECT
    schemaname || '.' || relname                              AS table_name,
    pg_size_pretty(pg_total_relation_size(relid))             AS total,
    pg_size_pretty(pg_relation_size(relid))                   AS data_only,
    pg_size_pretty(pg_total_relation_size(relid)
                   - pg_relation_size(relid))                 AS index_toast
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 15;

\echo ''
\echo '===== 3. Hypertable 体积（TimescaleDB 视角，含所有 chunk）====='
SELECT
    hypertable_name,
    pg_size_pretty(total_bytes)  AS total,
    pg_size_pretty(table_bytes)  AS heap,
    pg_size_pretty(index_bytes)  AS indexes,
    pg_size_pretty(toast_bytes)  AS toast
FROM timescaledb_information.hypertables h
CROSS JOIN LATERAL hypertable_detailed_size(
    format('%I.%I', h.hypertable_schema, h.hypertable_name)::regclass)
ORDER BY total_bytes DESC NULLS LAST;

\echo ''
\echo '===== 4. 压缩策略是否存在、是否真的在跑 ====='
SELECT hypertable_name, compression_enabled
FROM timescaledb_information.hypertables
ORDER BY hypertable_name;

\echo '-- 压缩任务执行情况（last_run_status 应为 Success）--'
SELECT j.hypertable_name, j.schedule_interval, s.last_run_status,
       s.last_successful_finish, s.total_failures
FROM timescaledb_information.jobs j
LEFT JOIN timescaledb_information.job_stats s ON s.job_id = j.job_id
WHERE j.proc_name IN ('policy_compression', 'policy_retention')
ORDER BY j.proc_name, j.hypertable_name;

\echo ''
\echo '-- 已压缩 / 未压缩 chunk 数量与实际压缩比 --'
SELECT
    hypertable_name,
    count(*) FILTER (WHERE is_compressed)                       AS compressed_chunks,
    count(*) FILTER (WHERE NOT is_compressed)                   AS uncompressed_chunks,
    pg_size_pretty(sum(before_compression_total_bytes))         AS before,
    pg_size_pretty(sum(after_compression_total_bytes))          AS after,
    round(sum(before_compression_total_bytes)::numeric
          / NULLIF(sum(after_compression_total_bytes), 0), 1)   AS ratio_x
FROM timescaledb_information.chunks c
LEFT JOIN chunk_compression_stats('device_alarm_info') s
       ON s.chunk_name = c.chunk_name
GROUP BY hypertable_name
ORDER BY hypertable_name;

\echo ''
\echo '===== 5. 传感器原始表增长速度（最近 14 天每天新增行数）====='
\echo '-- 用最近一天的行数 x 单行平均字节，可外推每月增量 --'
SELECT
    date_trunc('day', point_time)::date AS day,
    count(*)                            AS rows_per_day,
    pg_size_pretty((count(*) * (
        SELECT pg_total_relation_size('device_alarm_info')::numeric
             / NULLIF((SELECT count(*) FROM device_alarm_info), 0)
    ))::bigint)                         AS est_size_per_day
FROM device_alarm_info
WHERE point_time >= now() - INTERVAL '14 days'
GROUP BY 1
ORDER BY 1 DESC;

\echo ''
\echo '===== 6. 最老的数据是什么时候（判断已积累多久）====='
SELECT
    min(point_time) AS oldest,
    max(point_time) AS newest,
    (max(point_time)::date - min(point_time)::date) AS days_span
FROM device_alarm_info;
