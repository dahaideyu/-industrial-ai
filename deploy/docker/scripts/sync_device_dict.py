#!/usr/bin/env python3
"""
首次部署字典表同步：MySQL(jxcw) → PostgreSQL/TimescaleDB

背景：全新 Docker 部署时 init-sql 只建表结构，PG 里两张字典表是空的：
  - device_info       参数页设备下拉列表（backend /device-params/devices）
  - dev_device_param  参数编码 → 中文名/单位/排序（点位显示名）
它们的数据源头在 MySQL 业务库(jxcw)，本脚本读取后 upsert 到 PG。
幂等：只增改不删，可重复执行；MySQL 侧新增设备/参数后重跑即可增量同步。

设备清单推导（不依赖 dev_device 的编码列名，直接用参数定义表的关联）：
  SELECT DISTINCT p.device_no, d.name, d.id
  FROM dev_device_param p JOIN dev_device d ON d.id = p.device_id
  WHERE d.del_flag = 0
  device_no 即设备编码，与 PG device_alarm_info.device_id 同一套编码。

设备范围：默认只收录在 PG device_alarm_info 里出现过的设备（有实时采集才有
分析价值，现网 device_info 就是这个口径）；--all 收录全部有参数定义的设备。

用法（部署服务器上，容器已启动、MySQL 可达）：
  docker cp deploy/docker/scripts/sync_device_dict.py industrial-ai:/tmp/
  docker exec industrial-ai python /tmp/sync_device_dict.py            # 常规
  docker exec industrial-ai python /tmp/sync_device_dict.py --all      # 不按采集过滤
  docker exec industrial-ai python /tmp/sync_device_dict.py --dry-run  # 只预览不写库

连接参数（容器内环境变量）：
  PG:    POSTGRES_HOST/PORT/DB/USER/PASSWORD（与 backend 一致，PG_DB 兜底）
  MySQL: MYSQL_* 优先，未设置时回退 AQA_MYSQL_*（deploy/docker/.env 已有）
"""
import os
import sys
import argparse

import pymysql
import pymysql.cursors
import psycopg2
from psycopg2.extras import execute_values


def env_first(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


def connect_mysql():
    cfg = dict(
        host=env_first("MYSQL_HOST", "AQA_MYSQL_HOST", default="CHANGE_ME"),
        port=int(env_first("MYSQL_PORT", "AQA_MYSQL_PORT", default="3306")),
        user=env_first("MYSQL_USER", "AQA_MYSQL_USER", default="zxzz"),
        password=env_first("MYSQL_PASSWORD", "AQA_MYSQL_PASSWORD"),
        database=env_first("MYSQL_DATABASE", "AQA_MYSQL_DATABASE", default="jxcw"),
        charset="utf8mb4",
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor,
    )
    print(f"[MySQL] 连接 {cfg['host']}:{cfg['port']}/{cfg['database']} ...")
    return pymysql.connect(**cfg)


def connect_pg():
    kwargs = dict(
        host=os.getenv("POSTGRES_HOST", "CHANGE_ME"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB") or os.getenv("PG_DB") or "postgres",
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
        connect_timeout=int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "10")),
    )
    sslmode = os.getenv("POSTGRES_SSLMODE")
    if sslmode:
        kwargs["sslmode"] = sslmode
    print(f"[PG] 连接 {kwargs['host']}:{kwargs['port']}/{kwargs['dbname']} ...")
    return psycopg2.connect(**kwargs)


def sync_dev_device_param(my, pg, dry_run: bool) -> int:
    """MySQL dev_device_param → PG 同名表，按 id upsert，只搬两边共有的列。"""
    with my.cursor() as cur:
        cur.execute("SHOW TABLES LIKE 'dev_device_param'")
        if not cur.fetchone():
            print("[跳过] MySQL 没有 dev_device_param 表")
            return 0
        cur.execute("SHOW COLUMNS FROM dev_device_param")
        my_cols = {r["Field"] for r in cur.fetchall()}

    with pg.cursor() as cur:
        cur.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema='public' AND table_name='dev_device_param'
               ORDER BY ordinal_position"""
        )
        pg_cols = [r[0] for r in cur.fetchall()]

    cols = [c for c in pg_cols if c in my_cols]
    if "id" not in cols:
        print("[错误] dev_device_param 两侧没有共同的 id 列，无法 upsert")
        return 0

    with my.cursor() as cur:
        cur.execute("SELECT {} FROM dev_device_param".format(
            ", ".join(f"`{c}`" for c in cols)))
        rows = cur.fetchall()
    if not rows:
        print("[跳过] MySQL dev_device_param 无数据")
        return 0

    print(f"[dev_device_param] MySQL 读到 {len(rows)} 行，公共列 {len(cols)} 个")
    if dry_run:
        return len(rows)

    update_cols = [c for c in cols if c != "id"]
    sql = "INSERT INTO dev_device_param ({}) VALUES %s ON CONFLICT (id) DO UPDATE SET {}".format(
        ", ".join(cols),
        ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols),
    )
    with pg.cursor() as cur:
        execute_values(cur, sql,
                       [tuple(r[c] for c in cols) for r in rows], page_size=500)
    pg.commit()
    print(f"[dev_device_param] 已 upsert {len(rows)} 行")
    return len(rows)


# 与现网结构一致：device_id 是 varchar 设备编码（主键），id 是 MySQL dev_device.id
DEVICE_INFO_DDL = """
CREATE TABLE IF NOT EXISTS device_info (
    device_id   VARCHAR(64)  NOT NULL,
    device_name VARCHAR(255) NOT NULL,
    id          INTEGER,
    PRIMARY KEY (device_id)
)
"""


def ensure_device_info_table(pg) -> bool:
    """确认 device_info 存在且 device_id 是 varchar。

    旧版 init-sql 曾把 device_id 误建成 SERIAL（整型），12 位设备编码存不进去：
    空表则原地重建，有数据则中止交给人工。
    """
    with pg.cursor() as cur:
        cur.execute(
            """SELECT data_type FROM information_schema.columns
               WHERE table_schema='public' AND table_name='device_info'
                 AND column_name='device_id'"""
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(DEVICE_INFO_DDL)
            pg.commit()
            print("[device_info] 表不存在，已按现网结构创建")
            return True
        if row[0] == "character varying":
            # ON CONFLICT 需要唯一约束，老库缺了就补
            cur.execute(
                """SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid
                   WHERE c.relname = 'device_info' AND i.indisunique"""
            )
            if not cur.fetchone():
                cur.execute(
                    "CREATE UNIQUE INDEX device_info_device_id_key "
                    "ON device_info (device_id)")
                pg.commit()
                print("[device_info] 补建 device_id 唯一索引")
            return True
        cur.execute("SELECT COUNT(*) FROM device_info")
        cnt = cur.fetchone()[0]
        if cnt == 0:
            cur.execute("DROP TABLE device_info")
            cur.execute(DEVICE_INFO_DDL)
            pg.commit()
            print(f"[device_info] 原表 device_id 是 {row[0]}（旧 init-sql 的错误结构），"
                  "空表已重建为 varchar")
            return True
        print(f"[错误] device_info.device_id 类型是 {row[0]} 且已有 {cnt} 行，请人工处理")
        return False


def fetch_devices_from_mysql(my):
    sql = """
        SELECT p.device_no, d.name AS device_name, d.id
        FROM (SELECT DISTINCT device_no, device_id FROM dev_device_param
              WHERE device_no IS NOT NULL AND device_no <> '') p
        JOIN dev_device d ON d.id = p.device_id
        WHERE d.del_flag = 0
        ORDER BY d.id
    """
    with my.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    seen, devices = set(), []
    for r in rows:
        if r["device_no"] in seen:
            continue
        seen.add(r["device_no"])
        devices.append(r)
    return devices


def fetch_active_codes_from_pg(pg):
    """device_alarm_info（实时点位采集表）里出现过的设备编码；查询失败返回 None。"""
    try:
        with pg.cursor() as cur:
            cur.execute("SELECT DISTINCT device_id FROM device_alarm_info")
            return {r[0] for r in cur.fetchall()}
    except Exception as e:
        pg.rollback()
        print(f"[提示] 查询 device_alarm_info 失败（{e}），无法按采集数据过滤")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="MySQL → PG 设备字典表同步（device_info / dev_device_param）")
    ap.add_argument("--all", action="store_true",
                    help="收录所有有参数定义的设备（默认只收录 device_alarm_info 有采集数据的）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写库")
    args = ap.parse_args()

    my = connect_mysql()
    pg = connect_pg()
    try:
        n_param = sync_dev_device_param(my, pg, args.dry_run)

        devices = fetch_devices_from_mysql(my)
        print(f"[device_info] MySQL 推导出 {len(devices)} 台有参数定义的设备")
        if not args.all:
            active = fetch_active_codes_from_pg(pg)
            if not active:
                print("[中止] device_alarm_info 还没有采集数据，无法确定参数页该展示哪些设备。\n"
                      "       等采集跑起来后重跑本脚本；或用 --all 先收录全部有参数定义的设备。")
                return 0 if n_param else 1
            devices = [d for d in devices if d["device_no"] in active]
            print(f"[device_info] 按采集数据过滤后剩 {len(devices)} 台")

        for d in devices:
            print(f"    {d['device_no']}  {d['device_name']}  (id={d['id']})")

        if args.dry_run:
            print("[dry-run] 未写库")
            return 0
        if not devices:
            print("[跳过] 没有可写入的设备")
            return 0
        if not ensure_device_info_table(pg):
            return 1

        with pg.cursor() as cur:
            execute_values(
                cur,
                """INSERT INTO device_info (device_id, device_name, id) VALUES %s
                   ON CONFLICT (device_id) DO UPDATE
                   SET device_name = EXCLUDED.device_name, id = EXCLUDED.id""",
                [(d["device_no"], d["device_name"], d["id"]) for d in devices],
            )
        pg.commit()
        print(f"[device_info] 已 upsert {len(devices)} 台设备，同步完成")
        return 0
    finally:
        my.close()
        pg.close()


if __name__ == "__main__":
    sys.exit(main())
