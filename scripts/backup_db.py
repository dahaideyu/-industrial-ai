#!/usr/bin/env python
"""
PostgreSQL 数据库备份脚本
- 所有表结构完整导出
- 普通表全量数据
- 时序表（device_alarm_info, device_energy_info）只保留最近3天

用法:
    python scripts/backup_db.py
    python scripts/backup_db.py --output-dir D:/backup
    python scripts/backup_db.py --host 192.168.50.224 --port 15432

输出:
    backup_YYYYMMDD_HHMMSS/
    |-- 00_schema.sql           # 所有表结构（含索引、约束、TimescaleDB 配置）
    |-- 01_small_tables_data.sql # 普通表数据（INSERT 语句）
    |-- 02_device_alarm_info_3d.csv   # 告警表最近3天CSV
    |-- 02_device_energy_info_3d.csv  # 能耗表最近3天CSV
"""

import argparse
import csv
import io
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import psycopg2

# ========== 配置 ==========
DB_CONFIG = {
    "host": "192.168.50.224",
    "port": 15432,
    "user": "zxzz",
    "password": "CHANGE_ME@Zxzz",
    "dbname": "knowledge_base",
}

# 只需要最近 N 天数据的 Hypertable
HYPERTABLE_3D = ["device_alarm_info", "device_energy_info"]

# TimescaleDB 内部 schema，不导出
EXCLUDED_SCHEMAS = [
    "_timescaledb_internal",
    "_timescaledb_catalog",
    "_timescaledb_cache",
    "_timescaledb_config",
    "timescaledb_information",
]


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def run_pg_dump(args: list, output_path: str) -> bool:
    """尝试用 pg_dump 导出，失败返回 False"""
    cmd = [
        "pg_dump",
        "-h", DB_CONFIG["host"],
        "-p", str(DB_CONFIG["port"]),
        "-U", DB_CONFIG["user"],
        "-d", DB_CONFIG["dbname"],
        "--no-owner",
        "--no-privileges",
    ] + args

    env = os.environ.copy()
    env["PGPASSWORD"] = DB_CONFIG["password"]

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.PIPE, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"  [WARN] pg_dump 不可用: {e}")
        return False


def backup_schema(output_dir: str) -> str:
    """导出所有表结构"""
    path = os.path.join(output_dir, "00_schema.sql")
    print("\n[1/4] 导出表结构...")

    # 排除 TimescaleDB 内部 schema
    exclude_args = []
    for s in EXCLUDED_SCHEMAS:
        exclude_args.extend(["--exclude-schema", s])

    if run_pg_dump(["--schema-only"] + exclude_args, path):
        size = os.path.getsize(path)
        print(f"  [OK] pg_dump 导出成功: {path} ({size:,} 字节)")
        return path

    # pg_dump 不可用，用 Python 手动导出
    print("  [WARN] pg_dump 不可用，用 Python 手动导出...")
    return _python_schema_backup(output_dir)


def _python_schema_backup(output_dir: str) -> str:
    """Python 手动导出 DDL（降级方案）"""
    path = os.path.join(output_dir, "00_schema.sql")
    conn = get_conn()
    cur = conn.cursor()

    with open(path, "w", encoding="utf-8") as f:
        f.write("-- Schema backup (Python fallback - 仅含基础结构)\n")
        f.write(f"-- 导出时间: {datetime.now()}\n\n")

        # 获取所有用户表
        cur.execute("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name
        """)
        tables = cur.fetchall()

        for schema, table in tables:
            if any(schema.startswith(ex) for ex in EXCLUDED_SCHEMAS):
                continue
            f.write(f"\n-- ====== {schema}.{table} ======\n")

            # CREATE TABLE
            cur.execute("""
                SELECT column_name, data_type, is_nullable, column_default,
                       character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (schema, table))
            columns = cur.fetchall()

            col_defs = []
            for col, dtype, nullable, default, maxlen in columns:
                type_str = dtype
                if maxlen and dtype in ('character varying', 'varchar'):
                    type_str = f"varchar({maxlen})"
                null_str = "" if nullable == "YES" else " NOT NULL"
                default_str = f" DEFAULT {default}" if default else ""
                col_defs.append(f"    {col} {type_str}{null_str}{default_str}")

            f.write(f"CREATE TABLE {schema}.{table} (\n")
            f.write(",\n".join(col_defs))
            f.write("\n);\n\n")

    cur.close()
    conn.close()
    print(f"  [OK] Python 备份完成: {path}")
    return path


def backup_small_tables_data(output_dir: str) -> str:
    """导出普通表的所有数据"""
    path = os.path.join(output_dir, "01_small_tables_data.sql")
    print("\n[2/4] 导出普通表数据...")

    # 排除 hypertable + TimescaleDB 内部 schema
    exclude_tables = HYPERTABLE_3D
    exclude_args = []
    for t in exclude_tables:
        exclude_args.extend(["--exclude-table-data", f"public.{t}"])
    for s in EXCLUDED_SCHEMAS:
        exclude_args.extend(["--exclude-schema", s])

    if run_pg_dump(["--data-only", "--inserts", "--rows-per-insert=50"] + exclude_args, path):
        size = os.path.getsize(path)
        print(f"  [OK] pg_dump 导出成功: {path} ({size:,} 字节)")
        return path

    # Python fallback
    print("  [WARN] pg_dump 不可用，用 Python 手动导出...")
    return _python_data_backup(output_dir, exclude_tables)


def _python_data_backup(output_dir: str, exclude_tables: list) -> str:
    """Python 手动导出数据为 INSERT 语句"""
    path = os.path.join(output_dir, "01_small_tables_data.sql")
    conn = get_conn()
    cur = conn.cursor()

    # 获取所有用户表
    cur.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema = 'public'
          AND table_name NOT IN %s
        ORDER BY table_name
    """, (tuple(exclude_tables),))
    tables = cur.fetchall()

    with open(path, "w", encoding="utf-8") as f:
        f.write("-- Small tables data backup (Python fallback)\n")
        f.write(f"-- 导出时间: {datetime.now()}\n\n")

        for schema, table in tables:
            # 先看有多少行
            cur.execute(f'SELECT count(*) FROM "{schema}"."{table}"')
            count = cur.fetchone()[0]
            if count == 0:
                print(f"  [SKIP] {schema}.{table}: 空表，跳过")
                continue

            f.write(f"\n-- {schema}.{table} ({count} rows)\n")

            cur.execute(f'SELECT * FROM "{schema}"."{table}"')
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

            for row in rows:
                values = []
                for val in row:
                    if val is None:
                        values.append("NULL")
                    elif isinstance(val, (int, float)):
                        values.append(str(val))
                    elif isinstance(val, bool):
                        values.append("TRUE" if val else "FALSE")
                    elif isinstance(val, datetime):
                        values.append(f"'{val.isoformat()}'")
                    else:
                        # 字符串类型，需要转义
                        escaped = str(val).replace("'", "''")
                        values.append(f"'{escaped}'")
                f.write(f"INSERT INTO {schema}.{table} ({', '.join(columns)}) VALUES ({', '.join(values)});\n")

            print(f"  [OK] {schema}.{table}: {count} 行")

    cur.close()
    conn.close()
    size = os.path.getsize(path)
    print(f"  [OK] Python 备份完成: {path} ({size:,} 字节)")
    return path


def backup_hypertable_csv(output_dir: str) -> list:
    """导出两个 hypertable 最近3天数据为 CSV"""
    print("\n[3/4] 导出时序表最近3天数据...")

    conn = get_conn()
    cur = conn.cursor()
    files = []

    cutoff = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")

    for table in HYPERTABLE_3D:
        path = os.path.join(output_dir, f"02_{table}_3d.csv")
        print(f"\n   {table}...")

        # 先看符合条件的行数
        cur.execute(f"""
            SELECT count(*) FROM {table}
            WHERE "time" >= %s
        """, (cutoff,))
        count = cur.fetchone()[0]
        print(f"     最近3天数据: {count:,} 行")

        # 导出为 CSV
        cur.execute(f"""
            SELECT * FROM {table}
            WHERE "time" >= %s
            ORDER BY "time"
        """, (cutoff,))

        columns = [desc[0] for desc in cur.description]

        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)  # header
            batch = []
            for row in cur:
                batch.append(list(row))
                if len(batch) >= 10000:
                    writer.writerows(batch)
                    batch = []
            if batch:
                writer.writerows(batch)

        size = os.path.getsize(path)
        print(f"  [OK] 导出完成: {path} ({size:,} 字节)")
        files.append(path)

    cur.close()
    conn.close()
    return files


def generate_restore_script(output_dir: str, schema_file: str, data_file: str, csv_files: list):
    """生成恢复脚本"""
    path = os.path.join(output_dir, "restore.sh")
    csv_list = "\n".join(f"#   {os.path.basename(f)}" for f in csv_files)

    script = f"""#!/bin/bash
# 数据库恢复脚本
# 生成时间: {datetime.now()}
#
# 用法:
#   bash restore.sh <PG_HOST> <PG_PORT> <PG_DB> <PG_USER>
# 示例:
#   bash restore.sh 192.168.50.224 15432 knowledge_base zxzz

HOST=${{1:-localhost}}
PORT=${{2:-5432}}
DB=${{3:-knowledge_base}}
USER=${{4:-zxzz}}

echo "请输入密码:"
read -s PGPASSWORD
export PGPASSWORD

echo ""
echo "=== 步骤 1/3: 恢复表结构 ==="
psql -h $HOST -p $PORT -U $USER -d $DB -f {os.path.basename(schema_file)}
echo "[OK] 表结构恢复完成"

echo ""
echo "=== 步骤 2/3: 恢复普通表数据 ==="
psql -h $HOST -p $PORT -U $USER -d $DB -f {os.path.basename(data_file)}
echo "[OK] 普通表数据恢复完成"

echo ""
echo "=== 步骤 3/3: 恢复时序表数据 ==="
echo "时序表 CSV 文件:"
{csv_list}
echo ""
echo "请手动执行:"
for table in device_alarm_info device_energy_info; do
    csv_file="02_${{table}}_3d.csv"
    if [ -f "$csv_file" ]; then
        echo "  psql -h $HOST -p $PORT -U $USER -d $DB -c \"\\\\COPY $table FROM '$csv_file' CSV HEADER\""
    fi
done
echo "[OK] 恢复完成"
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    print(f"\n   恢复脚本: {path}")


def main():
    parser = argparse.ArgumentParser(description="数据库备份脚本")
    parser.add_argument("--output-dir", default=None, help="输出目录（默认 backup_YYYYMMDD_HHMMSS）")
    parser.add_argument("--host", default=DB_CONFIG["host"])
    parser.add_argument("--port", type=int, default=DB_CONFIG["port"])
    args = parser.parse_args()

    DB_CONFIG["host"] = args.host
    DB_CONFIG["port"] = args.port

    # 创建输出目录
    if args.output_dir:
        output_dir = args.output_dir
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backup_" + ts)
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print(f"数据库备份: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}")
    print(f"输出目录: {output_dir}")
    print(f"时序表 ({', '.join(HYPERTABLE_3D)}) -> 只保留最近3天")
    print("=" * 60)

    # 1. 表结构
    schema_file = backup_schema(output_dir)

    # 2. 普通表全量数据
    data_file = backup_small_tables_data(output_dir)

    # 3. 时序表最近3天 CSV
    csv_files = backup_hypertable_csv(output_dir)

    # 4. 生成恢复脚本
    print("\n[4/4] 生成恢复脚本...")
    generate_restore_script(output_dir, schema_file, data_file, csv_files)

    # 汇总
    print("\n" + "=" * 60)
    print("备份完成！")
    print("=" * 60)
    total_size = sum(
        os.path.getsize(os.path.join(output_dir, f))
        for f in os.listdir(output_dir)
    )
    print(f"输出目录: {output_dir}")
    print(f"总大小: {total_size:,} 字节 ({total_size/1024/1024:.1f} MB)")
    print()
    for f in sorted(os.listdir(output_dir)):
        size = os.path.getsize(os.path.join(output_dir, f))
        print(f"  {size:>12,}  {f}")


if __name__ == "__main__":
    main()
