#!/usr/bin/env python3
"""
设备类型同步脚本 — 从 MySQL 拉取设备类型到 PostgreSQL
使用方法: python sync_device_types.py

注意: 此脚本为临时脚本，数据库地址已写死在代码中，用完可删除
"""
import sys
import pymysql
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone


# ==================== 数据库配置（写死）====================
MYSQL_CONFIG = {
    "host": "192.168.50.213",
    "port": 3306,
    "user": "readonly_user",
    "password": "read@2026",
    "database": "btr",
    "charset": "utf8mb4",
}

PG_CONFIG = {
    "host": "192.168.50.224",
    "port": 15432,
    "user": "zxzz",
    "password": "Admin@Zxzz",
    "database": "knowledge_base",
}


def get_mysql_connection():
    try:
        conn = pymysql.connect(**MYSQL_CONFIG)
        print(f"[MySQL] 已连接: {MYSQL_CONFIG['host']}/{MYSQL_CONFIG['database']}")
        return conn
    except Exception as e:
        print(f"[MySQL] 连接失败: {e}")
        sys.exit(1)


def get_pg_connection():
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        print(f"[PostgreSQL] 已连接: {PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['database']}")
        return conn
    except Exception as e:
        print(f"[PostgreSQL] 连接失败: {e}")
        sys.exit(1)


def get_device_types_from_mysql(mysql_conn):
    """从 MySQL 获取设备类型和车间信息"""
    sql = """
    SELECT DISTINCT t.name AS device_type, sw.name AS workshop
    FROM dev_device_type t
    LEFT JOIN dev_device d ON t.id = d.type_id
    LEFT JOIN sys_line l ON d.line_id = l.id
    LEFT JOIN sys_workshop sw ON l.dept_id = sw.id
    WHERE t.del_flag=0 AND d.del_flag=0 AND l.del_flag=0 AND sw.del_flag=0
      AND t.name != '其他'
    """
    with mysql_conn.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


def sync_device_types(mysql_conn, pg_conn):
    """同步设备类型到 PostgreSQL"""
    aqa_devices = get_device_types_from_mysql(mysql_conn)
    if not aqa_devices:
        print("[Sync] MySQL 中没有设备类型数据")
        return

    print(f"[Sync] 从 MySQL 获取到 {len(aqa_devices)} 个设备类型")
    for d in aqa_devices:
        print(f"  - {d['device_type']} ({d['workshop']})")

    aqa_names = {d['device_type'] for d in aqa_devices}

    # 检查 PostgreSQL 中已存在的设备类型
    with pg_conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT device_type FROM knowledge_base 
            WHERE kb_type IN ('device', 'device_doc', 'sop_doc', 'history') 
              AND device_type IS NOT NULL
        """)
        existing = cur.fetchall()
        existing_names = {row['device_type'] for row in existing}

    print(f"\n[Sync] PostgreSQL 中已存在 {len(existing_names)} 个设备类型")

    # 找出需要新增的设备类型
    new_types = aqa_names - existing_names
    if new_types:
        print(f"\n[Sync] 需要新增 {len(new_types)} 个设备类型:")
        for name in sorted(new_types):
            print(f"  + {name}")
    else:
        print("\n[Sync] 没有需要新增的设备类型")

    # 找出需要停用的设备类型（MySQL中已删除但PG中仍存在）
    obsolete_types = existing_names - aqa_names
    if obsolete_types:
        print(f"\n[Sync] 需要停用 {len(obsolete_types)} 个设备类型:")
        for name in sorted(obsolete_types):
            print(f"  - {name}")
    else:
        print("\n[Sync] 没有需要停用的设备类型")

    # 执行插入
    if new_types:
        with pg_conn.cursor() as cur:
            now = datetime.now(timezone.utc)
            for d in aqa_devices:
                if d['device_type'] in new_types:
                    cur.execute("""
                        INSERT INTO knowledge_base (name, device_type, kb_type, tags, sync_type, status, synced_at)
                        VALUES (%s, %s, 'device', %s, 'auto', 'active', %s)
                    """, (d['device_type'], d['device_type'], {'base': '江西基地', 'workshop': d['workshop']}, now))
                    print(f"[Insert] 已创建: {d['device_type']}")
            pg_conn.commit()
        print(f"[Sync] 已成功创建 {len(new_types)} 个设备类型")

    # 执行停用
    if obsolete_types:
        with pg_conn.cursor() as cur:
            for name in obsolete_types:
                cur.execute("""
                    UPDATE knowledge_base SET status = 'disabled' 
                    WHERE device_type = %s AND kb_type IN ('device', 'device_doc', 'sop_doc', 'history')
                """, (name,))
                print(f"[Update] 已停用: {name}")
            pg_conn.commit()
        print(f"[Sync] 已成功停用 {len(obsolete_types)} 个设备类型")

    print("\n[Done] 设备类型同步完成!")


def main():
    print("=" * 60)
    print("设备类型同步脚本 — MySQL -> PostgreSQL")
    print("=" * 60)

    mysql_conn = get_mysql_connection()
    pg_conn = get_pg_connection()

    try:
        sync_device_types(mysql_conn, pg_conn)
    except Exception as e:
        print(f"\n[Error] 同步失败: {e}")
        import traceback
        traceback.print_exc()
        pg_conn.rollback()
    finally:
        mysql_conn.close()
        pg_conn.close()
        print("\n[Cleanup] 数据库连接已关闭")


if __name__ == "__main__":
    main()
