#!/usr/bin/env python3
"""回填 device_alarm_info.point_value_full：从 raw_json 提取全精度值。

用法：
  python backfill_point_value_full.py [--chunk-hours 1] [--start "2026-01-01"] [--end "2026-08-01"]

按小时分片逐批 UPDATE，避免单条 SQL 超时。历史数据只处理 point_value_full IS NULL 的行。
新 mqtt_etl 写入已同步填充，此脚本用于存量数据回填。
"""
import os
import sys
import argparse
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import execute_values


def connect():
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "127.0.0.1"),
        port=os.getenv("PG_PORT", "5432"),
        dbname=os.getenv("PG_DB", "knowledge_base"),
        user=os.getenv("PG_USER", "zxzz"),
        password=os.getenv("PG_PASSWORD", ""),
    )


SQL_UPDATE = """
    UPDATE device_alarm_info a
    SET point_value_full = sub.pv::numeric
    FROM (
        SELECT
            a2.ctid AS row_ctid,
            (pts_elem->>'point_value')::numeric AS pv
        FROM device_alarm_info a2
        CROSS JOIN LATERAL jsonb_array_elements(a2.raw_json->'devices') dev_elem
        CROSS JOIN LATERAL jsonb_array_elements(dev_elem->'points') pts_elem
        WHERE a2.point_value_full IS NULL
          AND a2.point_time >= %s AND a2.point_time < %s
          AND dev_elem->>'device_id' = a2.device_id
          AND pts_elem->>'point_id' = a2.point_id
        LIMIT 100000
    ) sub
    WHERE a.ctid = sub.row_ctid
"""


def backfill(conn, start: datetime, end: datetime):
    cursor = conn.cursor()
    chunk = timedelta(hours=1)
    t = start
    total_updated = 0

    while t < end:
        t_next = min(t + chunk, end)
        cursor.execute(SQL_UPDATE, (t, t_next))
        updated = cursor.rowcount
        conn.commit()
        total_updated += updated
        if updated:
            print(f"  [{t} ~ {t_next}] updated {updated} rows")
        t = t_next

    cursor.close()
    return total_updated


def main():
    parser = argparse.ArgumentParser(description="回填 device_alarm_info.point_value_full")
    parser.add_argument("--start", default="2026-01-01", help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-08-01", help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--chunk-hours", type=int, default=1, help="每批处理小时数")
    parser.add_argument("--dry-run", action="store_true", help="只统计待回填行数，不执行")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM device_alarm_info WHERE point_value_full IS NULL"
            )
            total_null = cur.fetchone()[0]
            print(f"待回填行数: {total_null}")

        if args.dry_run:
            print("Dry run，不执行更新。")
            return

        if total_null == 0:
            print("无需回填。")
            return

        print(f"开始回填: {start} ~ {end}，每批 {args.chunk_hours}h")
        updated = backfill(conn, start, end)
        print(f"完成。共更新 {updated} 行。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
