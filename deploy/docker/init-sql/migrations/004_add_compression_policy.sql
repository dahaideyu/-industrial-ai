-- 为 device_alarm_info / device_energy_info 开启 TimescaleDB 原生压缩策略
-- 目的：原始表无边界增长（raw_json 全量上报体尤其占空间），压缩后 10-20x 空间收益，
-- 不改变任何查询结果，只是老 chunk 的逐行扫描会稍慢
--
-- compress_after 定 14 天而不是 chunk 大小本身的 7 天：
-- chunk 是按固定 7 天窗口从纪元切分，不是"以当前时刻往回滚动"的 7 天；
-- 前端 raw 现算路径(特征视图)最长回溯 7 天，最坏情况下需要触达上一个 chunk 的最早一端，
-- 那一端可能已经是 14 天前。留 14 天余量保证"最近7天 raw 查询"不会碰到压缩过的 chunk。

-- device_alarm_info：工艺点位原始表
ALTER TABLE device_alarm_info SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id, point_id',
    timescaledb.compress_orderby = 'point_time DESC'
);
SELECT add_compression_policy('device_alarm_info', INTERVAL '14 days', if_not_exists => TRUE);

-- device_energy_info：能耗点位表，结构同构，同样处理
ALTER TABLE device_energy_info SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id, point_id',
    timescaledb.compress_orderby = 'point_time DESC'
);
SELECT add_compression_policy('device_energy_info', INTERVAL '14 days', if_not_exists => TRUE);
