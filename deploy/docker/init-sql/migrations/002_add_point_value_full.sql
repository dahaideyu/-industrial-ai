-- 为 device_alarm_info 添加 point_value_full 列（NUMERIC，全精度）
-- 替代 LATERAL JSONB 拆包提取 raw_json->devices[]->points[]->point_value
-- 新增数据由 mqtt_etl 写入时同步填充；历史数据用 backfill_point_value_full.py 回填

ALTER TABLE device_alarm_info ADD COLUMN IF NOT EXISTS point_value_full NUMERIC(14,4);

-- 复合索引：覆盖按设备+时间的查询，包含 point_value_full 避免回表
CREATE INDEX IF NOT EXISTS idx_device_alarm_info_full
    ON device_alarm_info (device_id, point_time DESC, point_id)
    INCLUDE (point_value_full);
