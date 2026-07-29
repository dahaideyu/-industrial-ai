-- device_alarm_info / device_energy_info 只保留 7 天原始数据
--
-- ⚠️ 会删数据且不可逆。migrations/ 目录不被 00_init_databases.sh 自动加载，
--    必须人工执行：
--    docker exec -i postgresql psql -U zxzz -d knowledge_base < 006_raw_retention_7d.sql
--
-- ── 执行前必须确认（原始数据删了补不回来）────────────────────────────────
-- 1) 夜间 rollup 正常：SELECT max(stat_date) FROM device_param_daily_stats;
--    结果应是昨天或今天。长期趋势(RUL/对标/故障前兆/画像学习)全靠这张衍生表，
--    如果 rollup 停了又开了保留策略，历史就真的没了。
-- 2) 没有其它系统直接从 device_alarm_info 拉历史。
--
-- ── 为什么要先改 chunk 大小 ──────────────────────────────────────────────
-- 保留策略是【按 chunk 整块删】的，不是按行删：只有当整个 chunk 的最新一条
-- 都超过阈值才会被丢弃。原来 chunk_time_interval = 7 天，配 7 天保留策略的
-- 实际效果是"保留 7~14 天"（最坏情况多存一整块）。改成 1 天后，删除粒度变细，
-- 实际保留量才接近 7~8 天，空间也更平稳。
-- set_chunk_time_interval 只影响【新建】的 chunk，已存在的老 chunk 不变，
-- 但它们会很快被保留策略清掉，所以无需额外处理。

\echo '=== 执行前现状 ==='
SELECT 'device_alarm_info' AS tbl,
       min(point_time) AS oldest, max(point_time) AS newest,
       pg_size_pretty(pg_total_relation_size('device_alarm_info')) AS size
FROM device_alarm_info
UNION ALL
SELECT 'device_energy_info',
       min(point_time), max(point_time),
       pg_size_pretty(pg_total_relation_size('device_energy_info'))
FROM device_energy_info;

\echo ''
\echo '=== 1) chunk 粒度 7天 -> 1天（只影响新 chunk）==='
SELECT set_chunk_time_interval('device_alarm_info',  INTERVAL '1 day');
SELECT set_chunk_time_interval('device_energy_info', INTERVAL '1 day');

\echo ''
\echo '=== 2) 压缩策略：7天就删，14天才压根本轮不到，去掉省得空转 ==='
-- 004 里 compress_after=14 天是为了"最近7天 raw 查询不碰压缩块"。
-- 现在保留期本身就是 7 天，压缩永远不会触发，留着只是个空跑的后台任务。
-- 数据量已被保留策略压到很小，也不再需要压缩。
SELECT remove_compression_policy('device_alarm_info',  if_exists => TRUE);
SELECT remove_compression_policy('device_energy_info', if_exists => TRUE);

\echo ''
\echo '=== 3) 加 7 天保留策略 ==='
SELECT add_retention_policy('device_alarm_info',  INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('device_energy_info', INTERVAL '7 days', if_not_exists => TRUE);

\echo ''
\echo '=== 生效的保留策略 ==='
SELECT j.hypertable_name,
       j.config ->> 'drop_after' AS drop_after,
       j.schedule_interval,
       s.last_run_status
FROM timescaledb_information.jobs j
LEFT JOIN timescaledb_information.job_stats s ON s.job_id = j.job_id
WHERE j.proc_name = 'policy_retention'
ORDER BY j.hypertable_name;

\echo ''
\echo '提示：保留策略默认每天跑一次，不会立刻释放空间。'
\echo '想马上清掉历史数据可手动执行（同样不可逆）：'
\echo "  SELECT drop_chunks('device_alarm_info',  older_than => INTERVAL '7 days');"
\echo "  SELECT drop_chunks('device_energy_info', older_than => INTERVAL '7 days');"
\echo '删完再跑一次 VACUUM 或等自动 autovacuum 回收。'
\echo ''
\echo '后悔了（停止继续删，已删的回不来）：'
\echo "  SELECT remove_retention_policy('device_alarm_info');"
\echo "  SELECT remove_retention_policy('device_energy_info');"
