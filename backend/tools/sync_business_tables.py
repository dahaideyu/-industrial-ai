#!/usr/bin/env python3
"""业务库基础表同步脚本 — 从 MySQL(btr) 全量镜像设备基础表到 PostgreSQL(knowledge_base)。

同步范围（只含小体量基础表，时序大表见 migrate_mysql_to_timescale.py）:
    dev_device_param  <- btr.dev_device_param   直接复制（列取交集）
    dev_device_status <- btr.dev_device_status  直接复制（列取交集）
    device_info       <- btr.dev_device         字段映射: assert_no->device_id, name->device_name, id->id

不同步的表及原因:
    point_info                          — 来源是 Excel（见 sync_excel_to_postgres.py），不在 MySQL
    device_param_profile / insight /    — AI 分析系统运行时自己生成的配置/结果表，MySQL 中不存在
    drift_config / stage_state_config /
    system_job_config / analysis_job_config

策略：单表事务内"先清空后插入"，天然幂等，可重复执行、可放 crontab 定时跑。

使用方法:
    python sync_business_tables.py                       # 同步全部 3 张表
    python sync_business_tables.py --tables device_info  # 只同步指定表（逗号分隔）
    python sync_business_tables.py --dry-run             # 只对比行数，不写入

连接信息优先读环境变量（SRC_MYSQL_* / DST_PG_*），未设置时用默认值。
"""
import argparse
import os
import sys
from pathlib import Path
from typing import Any, Optional

# 加载 .env（优先 docker/.env → backend/.env → 项目根 .env）
try:
    from dotenv import load_dotenv
    _proj = Path(__file__).resolve().parent.parent.parent
    _backend = Path(__file__).resolve().parent.parent
    for _p in (_proj / "deploy" / "docker" / ".env", _backend / ".env", _proj / ".env"):
        if _p.exists():
            load_dotenv(_p, override=False)
except ImportError:
    pass

import pymysql
import psycopg2
import psycopg2.extras

# ==================== 连接配置（env 优先，默认值兜底） ====================
MYSQL_CONFIG: dict[str, Any] = {
    "host": os.getenv("SRC_MYSQL_HOST") or os.getenv("AQA_MYSQL_HOST", "CHANGE_ME"),
    "port": int(os.getenv("SRC_MYSQL_PORT") or os.getenv("AQA_MYSQL_PORT", "3306")),
    "user": os.getenv("SRC_MYSQL_USER") or os.getenv("AQA_MYSQL_USER", "readonly_user"),
    "password": os.getenv("SRC_MYSQL_PASSWORD") or os.getenv("AQA_MYSQL_PASSWORD", "CHANGE_ME"),
    "database": os.getenv("SRC_MYSQL_DB") or os.getenv("AQA_MYSQL_DATABASE", "btr"),
    "charset": "utf8mb4",
}

PG_CONFIG: dict[str, Any] = {
    "host": os.getenv("DST_PG_HOST", "CHANGE_ME"),
    "port": os.getenv("DST_PG_PORT", "15432"),
    "dbname": os.getenv("DST_PG_DB", "knowledge_base"),
    "user": os.getenv("DST_PG_USER", "zxzz"),
    "password": os.getenv("DST_PG_PASSWORD", "CHANGE_ME"),
}

BATCH_SIZE = 1000

# ==================== 同步表定义 ====================
# select_sql 为 None 表示同名直拷（列取两边交集）；否则用自定义映射查询，
# 此时 columns 必须与 select_sql 的输出列一一对应。
SYNC_TABLES: dict[str, dict[str, Any]] = {
    "dev_device_param": {"select_sql": None, "columns": None},
    "dev_device_status": {"select_sql": None, "columns": None},
    "device_info": {
        # assert_no 即时序表/前端使用的 device_code；同一编码取 id 最小的一条防重
        "select_sql": """
            SELECT assert_no AS device_id, MIN(name) AS device_name, MIN(id) AS id
            FROM dev_device
            WHERE del_flag = 0 AND assert_no IS NOT NULL AND assert_no != ''
            GROUP BY assert_no
            ORDER BY MIN(id)
        """,
        "columns": ["device_id", "device_name", "id"],
    },
}


def connect_mysql() -> pymysql.connections.Connection:
    """连接源 MySQL，失败直接退出。"""
    try:
        conn = pymysql.connect(**MYSQL_CONFIG, connect_timeout=10)
        print(f"[MySQL] 已连接: {MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}/{MYSQL_CONFIG['database']}")
        return conn
    except Exception as e:
        print(f"[MySQL] 连接失败: {e}")
        sys.exit(1)


def connect_pg() -> psycopg2.extensions.connection:
    """连接目标 PostgreSQL，失败直接退出。"""
    try:
        conn = psycopg2.connect(**PG_CONFIG, connect_timeout=10)
        print(f"[PostgreSQL] 已连接: {PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['dbname']}")
        return conn
    except Exception as e:
        print(f"[PostgreSQL] 连接失败: {e}")
        sys.exit(1)


def get_mysql_columns(conn: pymysql.connections.Connection, table: str) -> list[str]:
    """查询 MySQL 表列名（按定义顺序），表不存在返回空列表。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (MYSQL_CONFIG["database"], table),
        )
        return [row[0] for row in cur.fetchall()]


def get_pg_columns(conn: psycopg2.extensions.connection, table: str) -> list[str]:
    """查询 PG 表列名（按定义顺序），表不存在返回空列表。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [row[0] for row in cur.fetchall()]


def ensure_device_info_schema(pg: psycopg2.extensions.connection) -> None:
    """device_info.device_id 建表脚本里是 SERIAL(integer)，但真实设备编码是
    'BTR-QSDLCW-03' 这类字符串（与时序表 device_code、前端下拉框选中值一致），
    integer 存不下会让参数分析页选了设备也查不到数据，这里自动纠正为 VARCHAR。"""
    with pg.cursor() as cur:
        cur.execute(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'device_info' AND column_name = 'device_id'
            """
        )
        row = cur.fetchone()
        if row and row[0] != "character varying":
            print("  [Schema] device_info.device_id 为 integer，改为 VARCHAR(64) 以存放设备编码")
            cur.execute("ALTER TABLE device_info ALTER COLUMN device_id DROP DEFAULT")
            cur.execute("ALTER TABLE device_info ALTER COLUMN device_id TYPE VARCHAR(64) USING device_id::varchar")
    pg.commit()


def sync_table(
    mysql_conn: pymysql.connections.Connection,
    pg: psycopg2.extensions.connection,
    table: str,
    dry_run: bool = False,
) -> bool:
    """全量镜像单张表：目标表清空后从 MySQL 整体复制，单事务保证失败可回滚。

    Args:
        mysql_conn: 源 MySQL 连接。
        pg: 目标 PG 连接。
        table: 目标表名（SYNC_TABLES 的 key）。
        dry_run: 为 True 时只对比行数不写入。

    Returns:
        是否同步成功。
    """
    cfg = SYNC_TABLES[table]
    pg_cols = get_pg_columns(pg, table)
    if not pg_cols:
        print(f"  [跳过] 目标库中不存在表 {table}（请先执行 01_schema_postgres.sql 建表）")
        return False

    if cfg["select_sql"]:
        select_sql: str = cfg["select_sql"]
        cols: list[str] = cfg["columns"]
    else:
        src_cols = get_mysql_columns(mysql_conn, table)
        if not src_cols:
            print(f"  [跳过] MySQL 中不存在表 {table}")
            return False
        # 取交集并保持源表列序，两边 schema 有出入时仍可同步公共列
        cols = [c for c in src_cols if c in set(pg_cols)]
        dropped = set(src_cols) - set(cols)
        if dropped:
            print(f"  [提示] {table} 以下列目标库没有，跳过: {sorted(dropped)}")
        select_sql = "SELECT " + ", ".join(f"`{c}`" for c in cols) + f" FROM `{table}`"

    with mysql_conn.cursor() as src_cur:
        src_cur.execute(select_sql)
        rows = src_cur.fetchall()

    with pg.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        dst_count = cur.fetchone()[0]

    if dry_run:
        print(f"  [dry-run] {table}: 源 {len(rows)} 行 -> 目标当前 {dst_count} 行")
        return True

    col_sql = ", ".join(f'"{c}"' for c in cols)
    with pg.cursor() as cur:
        cur.execute(f'DELETE FROM "{table}"')
        for i in range(0, len(rows), BATCH_SIZE):
            psycopg2.extras.execute_values(
                cur,
                f'INSERT INTO "{table}" ({col_sql}) VALUES %s',
                rows[i : i + BATCH_SIZE],
                page_size=BATCH_SIZE,
            )
    pg.commit()
    print(f"  [完成] {table}: 已写入 {len(rows)} 行（原有 {dst_count} 行已替换）")
    return True


def main() -> None:
    """入口：解析参数并逐表同步。"""
    parser = argparse.ArgumentParser(description="MySQL(btr) 基础表 -> knowledge_base 全量镜像同步")
    parser.add_argument("--tables", help="只同步指定表，逗号分隔（默认全部）")
    parser.add_argument("--dry-run", action="store_true", help="只对比行数，不写入")
    args = parser.parse_args()

    tables = [t.strip() for t in args.tables.split(",")] if args.tables else list(SYNC_TABLES)
    unknown = set(tables) - set(SYNC_TABLES)
    if unknown:
        print(f"[Error] 不在同步清单中: {sorted(unknown)}\n可选: {list(SYNC_TABLES)}")
        sys.exit(1)

    print("=" * 60)
    print("业务库基础表同步: MySQL(btr) -> PostgreSQL(knowledge_base)")
    print("=" * 60)

    mysql_conn = connect_mysql()
    pg = connect_pg()

    ok, failed = 0, 0
    try:
        if "device_info" in tables and not args.dry_run:
            ensure_device_info_schema(pg)
        for table in tables:
            print(f"\n[Sync] {table}")
            try:
                if sync_table(mysql_conn, pg, table, dry_run=args.dry_run):
                    ok += 1
                else:
                    failed += 1
            except Exception as e:
                pg.rollback()  # 单表失败回滚该表事务，不影响已完成的表
                failed += 1
                print(f"  [失败] {table}: {e}")
    finally:
        mysql_conn.close()
        pg.close()

    print("\n" + "=" * 60)
    print(f"[Done] 成功 {ok} 张，失败/跳过 {failed} 张")
    print("=" * 60)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
