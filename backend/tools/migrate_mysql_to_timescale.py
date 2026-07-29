# cython: annotation_typing=False, infer_types=False, language_level=3
"""
MySQL -> PostgreSQL (TimescaleDB) 数据迁移脚本
将以下表从 3 月份至今的数据迁移到 PostgreSQL:
  - dev_device_status (字典表，全量迁移)
  - dev_device_status_record (时序表 → hypertable)
  - dev_device_param_detail_record (时序表 → hypertable)

使用方法:
    cd backend
    python tools/migrate_mysql_to_timescale.py              # 常规迁移
    python tools/migrate_mysql_to_timescale.py --verify     # 逐月复查，发现差异自动补迁移
"""
import io
import os
import sys
import argparse
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# 确保 backend 目录在路径中
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import pymysql
import psycopg2
from psycopg2.extras import RealDictCursor

# 加载环境变量
from dotenv import load_dotenv
project_root = os.path.dirname(backend_dir)
env_path = os.path.join(project_root, ".env")
if os.path.isfile(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

# ============================================================
# 配置
# ============================================================
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "zxzz"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "jxcw"),
    "charset": "utf8mb4",
}

PG_CONFIG = {
    "host": os.getenv("PG_HOST", "127.0.0.1"),
    "port": os.getenv("PG_PORT", "5432"),
    "user": os.getenv("PG_USER", "zxzz"),
    "password": os.getenv("PG_PASSWORD", ""),
}

# 迁移时间范围
START_DATE = "2025-03-01 00:00:00"
BATCH_SIZE = 50000  # 每批读取/写入条数（用 COPY 协议可以很大）

# 逐月复查配置: 指定表名和复查起始月份
# 格式: {"表名": "起始月份(YYYY-MM)"}  为空则不复查
VERIFY_CONFIG = {
    "dev_device_param_detail_record": "2025-03",
}

# ============================================================
# 表定义
# ============================================================
TABLE_CONFIGS = [
    {
        "name": "dev_device_status",
        "is_hypertable": False,
        "columns": [
            "id", "name", "code", "serial_code", "color", "icon",
            "status", "alarm", "close_alarm", "create_time", "update_time",
        ],
        "column_types": [
            "BIGINT NOT NULL",
            "VARCHAR(50) NOT NULL",
            "INTEGER NOT NULL",
            "INTEGER NOT NULL",
            "VARCHAR(20)",
            "VARCHAR(100)",
            "VARCHAR(20) NOT NULL",
            "SMALLINT",
            "SMALLINT",
            "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        ],
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_{name}_code ON {name} (code);",
        ],
        "additional_steps": [],
    },
    {
        "name": "dev_device_status_record",
        "is_hypertable": True,
        "columns": [
            "id", "device_id", "status", "start_time", "end_time",
            "duration", "order_number", "create_time", "update_time",
            "last_start_time", "qualified_count", "unqualified_count",
            "report_qualified_count", "report_unqualified_count",
            "CT_serial_no", "product_id", "report_CT",
        ],
        "partition_column": "start_time",
        "max_time_column": "start_time",
        "column_types": [
            "INTEGER",
            "INTEGER",
            "SMALLINT",
            "TIMESTAMP",
            "TIMESTAMP",
            "BIGINT",
            "VARCHAR(255)",
            "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "TIMESTAMP",
            "INTEGER DEFAULT 0",
            "INTEGER DEFAULT 0",
            "INTEGER DEFAULT 0",
            "INTEGER DEFAULT 0",
            "INTEGER",
            "BIGINT",
            "NUMERIC(10,2)",
        ],
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_{name}_id ON {name} (id);",
            "CREATE INDEX IF NOT EXISTS idx_{name}_device_id ON {name} (device_id);",
            "CREATE INDEX IF NOT EXISTS idx_{name}_start_time ON {name} (start_time DESC);",
            "CREATE INDEX IF NOT EXISTS idx_{name}_device_start ON {name} (device_id, start_time DESC);",
        ],
        "additional_steps": [],
    },
    {
        "name": "dev_device_param_detail_record",
        "is_hypertable": True,
        "columns": [
            "id", "device_code", "device_name", "p_name", "p_value",
            "report_time", "create_time", "gather_time",
        ],
        "partition_column": "gather_time",
        "max_time_column": "gather_time",
        "column_types": [
            "BIGINT",
            "VARCHAR(50)", "VARCHAR(50)", "VARCHAR(50)", "VARCHAR(50)",
            "TIMESTAMP", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP", "TIMESTAMP NOT NULL",
        ],
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_{name}_id ON {name} (id);",
            "CREATE INDEX IF NOT EXISTS idx_{name}_code_time ON {name} (device_code, gather_time DESC);",
            "CREATE INDEX IF NOT EXISTS idx_{name}_code_name_time ON {name} (device_code, p_name, gather_time DESC);",
        ],
        "additional_steps": ["refresh_device_list"],
    },
]


def get_mysql_connection():
    """获取 MySQL 连接"""
    try:
        conn = pymysql.connect(**MYSQL_CONFIG)
        print(f"[MySQL] 已连接: {MYSQL_CONFIG['host']}/{MYSQL_CONFIG['database']}")
        return conn
    except Exception as e:
        print(f"[MySQL] 连接失败: {e}")
        sys.exit(1)


def get_pg_connection():
    """获取 PostgreSQL 连接"""
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        print(f"[PostgreSQL] 已连接: {PG_CONFIG['host']}")
        return conn
    except Exception as e:
        print(f"[PostgreSQL] 连接失败: {e}")
        sys.exit(1)


def ensure_timescale_extension(pg_conn):
    """确保 TimescaleDB 扩展已启用"""
    with pg_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
        pg_conn.commit()
        print("[TimescaleDB] 扩展已确保启用")


def create_pg_table(pg_conn, cfg):
    """在 PostgreSQL 中创建目标表，时序表会转换为 hypertable"""
    table = cfg["name"]
    columns = cfg["columns"]
    column_types = cfg["column_types"]
    is_hypertable = cfg.get("is_hypertable", True)

    # 构建列定义：非 hypertable 的表用 id 做 PRIMARY KEY
    col_defs_parts = []
    for col, typ in zip(columns, column_types):
        if not is_hypertable and col == "id":
            col_defs_parts.append(f"{col} {typ} PRIMARY KEY")
        else:
            col_defs_parts.append(f"{col} {typ}")
    col_defs = ", ".join(col_defs_parts)

    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = %s
            );
        """, (table,))
        exists = cur.fetchone()[0]

        if exists:
            print(f"[PostgreSQL] 表 {table} 已存在，跳过创建")
            if is_hypertable:
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{table}_id
                    ON {table} (id);
                """)
                pg_conn.commit()
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM timescaledb_information.hypertables
                        WHERE hypertable_name = %s
                    );
                """, (table,))
                is_hyper = cur.fetchone()[0]
                if not is_hyper:
                    print(f"[TimescaleDB] 表存在但不是 hypertable，尝试转换...")
                    try:
                        cur.execute(f"""
                            SELECT create_hypertable('{table}', '{cfg["partition_column"]}', if_not_exists => TRUE);
                        """)
                        pg_conn.commit()
                        print(f"[TimescaleDB] 已转换为 hypertable")
                    except Exception as e:
                        print(f"[TimescaleDB] 转换失败: {e}")
                        pg_conn.rollback()
            return

        create_sql = """
        CREATE TABLE {} (
            {}
        );
        """.format(table, col_defs)
        cur.execute(create_sql)
        pg_conn.commit()
        print(f"[PostgreSQL] 表 {table} 创建成功")

        if is_hypertable:
            cur.execute(f"""
                SELECT create_hypertable('{table}', '{cfg["partition_column"]}', if_not_exists => TRUE);
            """)
            pg_conn.commit()
            print(f"[TimescaleDB] hypertable 创建成功 (分区键: {cfg['partition_column']})")

        # 创建索引
        for idx_sql in cfg.get("indexes", []):
            cur.execute(idx_sql.format(name=table))
        pg_conn.commit()
        print(f"[PostgreSQL] 索引创建完成")


def get_pg_resume_point(pg_conn, cfg):
    """获取 PostgreSQL 中已迁移的最大 id 和时间，用于断点续传"""
    table = cfg["name"]
    max_time_col = cfg["max_time_column"]

    with pg_conn.cursor() as cur:
        print(f"[Resume] 正在检查 {table} 的已迁移进度...")
        cur.execute(f"SELECT MAX(id), MAX({max_time_col}) FROM {table};")
        row = cur.fetchone()
        max_id = row[0] if row[0] is not None else 0
        max_time = row[1]

        if max_id == 0:
            print(f"[Resume] {table} PostgreSQL 表为空，从头开始迁移")
            return 0, None

        print(f"[Resume] {table} 已迁移: max_id={max_id}, max_{max_time_col}={max_time}")
        return max_id, max_time


def count_mysql_data(mysql_conn, cfg, min_id, start_date=START_DATE):
    """统计需要迁移的数据总量"""
    table = cfg["name"]
    partition_col = cfg["partition_column"]

    with mysql_conn.cursor() as cur:
        sql = """
            SELECT COUNT(*) as cnt
            FROM {}
            WHERE {} >= %s AND id > %s
        """.format(table, partition_col)
        cur.execute(sql, (start_date, min_id))
        row = cur.fetchone()
        return row[0]


def count_mysql_data_by_range(mysql_conn, cfg, range_start, range_end):
    """统计 MySQL 中某时间范围内的数据量（注意：大表上较慢）"""
    table = cfg["name"]
    partition_col = cfg["partition_column"]

    print(f"  [Count] 统计 MySQL {range_start[:7]} 数据量...", end="", flush=True)
    with mysql_conn.cursor() as cur:
        sql = """
            SELECT COUNT(*) as cnt
            FROM {}
            WHERE {} >= %s AND {} < %s
        """.format(table, partition_col, partition_col)
        cur.execute(sql, (range_start, range_end))
        row = cur.fetchone()
    print(f" {row[0]:,}")
    return row[0]


def count_pg_data_by_range(pg_conn, cfg, range_start, range_end):
    """统计 PostgreSQL 中某时间范围内的数据量"""
    table = cfg["name"]
    partition_col = cfg["partition_column"]

    print(f"  [Count] 统计 PG   {range_start[:7]} 数据量...", end="", flush=True)
    with pg_conn.cursor() as cur:
        sql = """
            SELECT COUNT(*) as cnt
            FROM {}
            WHERE {} >= %s AND {} < %s
        """.format(table, partition_col, partition_col)
        cur.execute(sql, (range_start, range_end))
        row = cur.fetchone()
    print(f" {row[0]:,}")
    return row[0]


def migrate_batch(mysql_conn, pg_conn, cfg, last_id, start_date=START_DATE):
    """
    使用 PostgreSQL COPY 协议批量导入数据（比 INSERT VALUES 快 5~10 倍）
    返回 (写入条数, 新的 last_id)
    """
    table = cfg["name"]
    columns = cfg["columns"]
    partition_col = cfg["partition_column"]

    col_list = ", ".join(columns)

    with mysql_conn.cursor() as cur:
        sql = """
            SELECT {}
            FROM {}
            WHERE {} >= %s AND id > %s
            ORDER BY id ASC
            LIMIT %s
        """.format(col_list, table, partition_col)
        cur.execute(sql, (start_date, last_id, BATCH_SIZE))
        rows = cur.fetchall()

    if not rows:
        return 0, last_id

    buffer = io.StringIO()
    new_last_id = last_id
    for row in rows:
        fields = []
        for val in row:
            if val is None:
                fields.append("\\N")
            else:
                s = str(val)
                s = s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
                fields.append(s)
        buffer.write("\t".join(fields) + "\n")

        rid = row[0]
        if rid is not None and rid > new_last_id:
            new_last_id = rid

    buffer.seek(0)
    with pg_conn.cursor() as cur:
        cur.copy_expert(
            f"""COPY {table}
                ({col_list})
                FROM STDIN WITH (FORMAT text, NULL '\\N')""",
            buffer
        )
        pg_conn.commit()

    return len(rows), new_last_id


def migrate_batch_by_range(mysql_conn, pg_conn, cfg, last_id, range_start, range_end):
    """
    按时间范围批量导入数据，用于逐月复查时的重迁移
    返回 (写入条数, 新的 last_id)
    """
    table = cfg["name"]
    columns = cfg["columns"]
    partition_col = cfg["partition_column"]

    col_list = ", ".join(columns)

    with mysql_conn.cursor() as cur:
        sql = """
            SELECT {}
            FROM {}
            WHERE {} >= %s AND {} < %s AND id > %s
            ORDER BY id ASC
            LIMIT %s
        """.format(col_list, table, partition_col, partition_col)
        cur.execute(sql, (range_start, range_end, last_id, BATCH_SIZE))
        rows = cur.fetchall()

    if not rows:
        return 0, last_id

    buffer = io.StringIO()
    new_last_id = last_id
    for row in rows:
        fields = []
        for val in row:
            if val is None:
                fields.append("\\N")
            else:
                s = str(val)
                s = s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
                fields.append(s)
        buffer.write("\t".join(fields) + "\n")

        rid = row[0]
        if rid is not None and rid > new_last_id:
            new_last_id = rid

    buffer.seek(0)
    with pg_conn.cursor() as cur:
        cur.copy_expert(
            f"""COPY {table}
                ({col_list})
                FROM STDIN WITH (FORMAT text, NULL '\\N')""",
            buffer
        )
        pg_conn.commit()

    return len(rows), new_last_id


def refresh_device_list(pg_conn):
    """从 hypertable 刷新 device_list 小表（逐 chunk 扫描去重）"""
    with pg_conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_list (
                device_code VARCHAR(50) PRIMARY KEY,
                device_name VARCHAR(50)
            )
        """)
        pg_conn.commit()

    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT chunk_schema, chunk_name
            FROM timescaledb_information.chunks
            WHERE hypertable_name = 'dev_device_param_detail_record'
            ORDER BY range_start
        """)
        chunks = cur.fetchall()

    total = 0
    for schema, chunk in chunks:
        full_name = f'"{schema}"."{chunk}"'
        try:
            with pg_conn.cursor() as cur:
                cur.execute(f"""
                    SELECT DISTINCT device_code, device_name
                    FROM {full_name}
                    WHERE device_code IS NOT NULL AND device_code != ''
                """)
                for code, name in cur.fetchall():
                    cur.execute(
                        "INSERT INTO device_list (device_code, device_name) VALUES (%s, %s) ON CONFLICT (device_code) DO UPDATE SET device_name = EXCLUDED.device_name",
                        (code, name)
                    )
                    total += 1
                pg_conn.commit()
        except Exception as e:
            pg_conn.rollback()
            print(f"  [WARN] chunk {chunk} 刷新失败: {e}")

    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM device_list")
        cnt = cur.fetchone()[0]
    print(f"[PostProcess] device_list 刷新完成，共 {cnt} 个设备")


def migrate_table(mysql_conn, pg_conn, cfg):
    """迁移单个表"""
    table = cfg["name"]
    is_hypertable = cfg.get("is_hypertable", True)

    print(f"\n{'=' * 60}")
    print(f"开始迁移表: {table}")
    if is_hypertable:
        print(f"类型: TimescaleDB hypertable | 时间范围: {START_DATE} 至今")
    else:
        print(f"类型: 普通表 (全量迁移)")
    print(f"{'=' * 60}")

    # 创建目标表
    create_pg_table(pg_conn, cfg)

    if is_hypertable:
        # === 时序表：批量迁移 + 断点续传 ===
        pg_max_id, pg_max_time = get_pg_resume_point(pg_conn, cfg)
        if pg_max_id > 0:
            print(f"[Resume] {table} PostgreSQL 中已有数据，最大 id={pg_max_id}")
        else:
            print(f"[Resume] {table} PostgreSQL 表为空，从头开始迁移")

        total = count_mysql_data(mysql_conn, cfg, pg_max_id)
        if total == 0:
            print(f"[MySQL] {table} 没有需要迁移的数据")
            return

        print(f"[MySQL] {table} 待迁移数据总量: {total:,} 条")
        print("-" * 60)

        last_id = pg_max_id
        migrated = 0
        start_ts = datetime.now()

        while True:
            count, last_id = migrate_batch(mysql_conn, pg_conn, cfg, last_id)
            if count == 0:
                break

            migrated += count
            elapsed = (datetime.now() - start_ts).total_seconds()
            speed = migrated / elapsed if elapsed > 0 else 0
            percent = migrated / total * 100

            print(
                f"[Migrate] {table} 已迁移 {migrated:,} / {total:,} ({percent:.1f}%) "
                f"| 本批 {count:,} 条 | 最新 id={last_id} | 速度 {speed:.0f} 条/秒"
            )

        print("-" * 60)
        print(f"[Done] {table} 迁移完成，本次共写入 {migrated:,} 条数据")
        print(f"[Time] 总耗时: {(datetime.now() - start_ts).total_seconds():.1f} 秒")
    else:
        # === 字典表：全量单批 COPY ===
        columns = cfg["columns"]
        col_list = ", ".join(columns)

        with mysql_conn.cursor() as cur:
            cur.execute(f"SELECT {col_list} FROM {table} ORDER BY id")
            rows = cur.fetchall()

        if not rows:
            print(f"[MySQL] {table} 没有数据")
            return

        buffer = io.StringIO()
        for row in rows:
            fields = []
            for val in row:
                if val is None:
                    fields.append("\\N")
                else:
                    s = str(val)
                    s = s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
                    fields.append(s)
            buffer.write("\t".join(fields) + "\n")

        buffer.seek(0)
        with pg_conn.cursor() as cur:
            cur.execute(f"TRUNCATE {table}")
            cur.copy_expert(
                f"""COPY {table}
                    ({col_list})
                    FROM STDIN WITH (FORMAT text, NULL '\\N')""",
                buffer
            )
            pg_conn.commit()

        print(f"[Done] {table} 全量迁移完成，共 {len(rows):,} 条")

    # 执行额外步骤
    for step in cfg.get("additional_steps", []):
        if step == "refresh_device_list":
            refresh_device_list(pg_conn)


def verify_and_fix_monthly(mysql_conn, pg_conn, cfg, verify_start_month, force=False):
    """
    逐月复查数据完整性：
    force=True:  直接删除 PG 每月数据并重新迁移（跳过慢的 COUNT 对比）
    force=False: 先 COUNT 对比，只补迁移有差异的月份
    """
    table = cfg["name"]
    partition_col = cfg["partition_column"]

    print(f"\n{'=' * 60}")
    print(f"逐月复查: {table}")
    print(f"复查起始月份: {verify_start_month}")
    print(f"模式: {'强制重迁移（删除后重新导入）' if force else '对比后补迁移'}")
    print(f"{'=' * 60}")

    # 计算需要复查的月份列表
    start_dt = datetime.strptime(verify_start_month, "%Y-%m")
    now = datetime.now()
    months = []
    current = start_dt
    while current <= now:
        months.append(current)
        current = current + relativedelta(months=1)

    print(f"[Verify] 共需处理 {len(months)} 个月份: {', '.join(m.strftime('%Y-%m') for m in months)}")

    if force:
        # === 强制模式：直接删了重迁移，不需要先 COUNT ===
        for month_dt in months:
            range_start = month_dt.strftime("%Y-%m-01 00:00:00")
            next_month = month_dt + relativedelta(months=1)
            range_end = next_month.strftime("%Y-%m-01 00:00:00")
            month_label = month_dt.strftime("%Y-%m")

            print(f"\n--- 强制重迁移 {month_label} ---")

            # 1. 删除 PG 中该月的数据
            print(f"[Fix] 删除 PG 中 {month_label} 数据...", end="", flush=True)
            with pg_conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {table} WHERE {partition_col} >= %s AND {partition_col} < %s",
                    (range_start, range_end)
                )
                deleted = cur.rowcount
                pg_conn.commit()
            print(f" {deleted:,} 条")

            # 2. 从 MySQL 重新迁移该月数据
            last_id = 0
            migrated = 0
            start_ts = datetime.now()

            while True:
                count, last_id = migrate_batch_by_range(
                    mysql_conn, pg_conn, cfg, last_id, range_start, range_end
                )
                if count == 0:
                    break
                migrated += count
                elapsed = (datetime.now() - start_ts).total_seconds()
                speed = migrated / elapsed if elapsed > 0 else 0
                print(
                    f"[Fix] {month_label} 已导入 {migrated:,} 条"
                    f" | 本批 {count:,} 条 | 速度 {speed:.0f} 条/秒"
                )

            print(f"[Fix] {month_label} 完成，写入 {migrated:,} 条 (原 {deleted:,} 条)")

    else:
        # === 对比模式：先 COUNT 对比，只补迁移有差异的月份 ===
        problem_months = []

        for month_dt in months:
            range_start = month_dt.strftime("%Y-%m-01 00:00:00")
            next_month = month_dt + relativedelta(months=1)
            range_end = next_month.strftime("%Y-%m-01 00:00:00")
            month_label = month_dt.strftime("%Y-%m")

            print(f"\n--- 检查 {month_label} ---")
            mysql_count = count_mysql_data_by_range(mysql_conn, cfg, range_start, range_end)
            pg_count = count_pg_data_by_range(pg_conn, cfg, range_start, range_end)

            status = "OK" if mysql_count == pg_count else "MISMATCH"
            diff = mysql_count - pg_count
            diff_str = f" (缺 {diff:,})" if diff > 0 else (f" (多 {-diff:,})" if diff < 0 else "")
            print(f"[Verify] {month_label}: MySQL={mysql_count:,}  PG={pg_count:,}  {status}{diff_str}")

            if diff > 0:
                problem_months.append((month_dt, range_start, range_end, mysql_count, pg_count, diff))

        if not problem_months:
            print(f"\n[Verify] {table} 所有月份数据完整，无需补迁移")
            return

        print(f"\n[Verify] 发现 {len(problem_months)} 个月份存在数据缺失，开始补迁移...")
        print("=" * 60)

        for month_dt, range_start, range_end, mysql_count, pg_count, diff in problem_months:
            month_label = month_dt.strftime("%Y-%m")
            print(f"\n--- 补迁移 {month_label} (缺 {diff:,} 条) ---")

            # 1. 删除 PG 中该月的数据
            with pg_conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {table} WHERE {partition_col} >= %s AND {partition_col} < %s",
                    (range_start, range_end)
                )
                deleted = cur.rowcount
                pg_conn.commit()
                print(f"[Fix] 已删除 {month_label} PG 数据 {deleted:,} 条")

            # 2. 从 MySQL 重新迁移该月数据
            last_id = 0
            migrated = 0
            start_ts = datetime.now()

            while True:
                count, last_id = migrate_batch_by_range(
                    mysql_conn, pg_conn, cfg, last_id, range_start, range_end
                )
                if count == 0:
                    break
                migrated += count
                elapsed = (datetime.now() - start_ts).total_seconds()
                speed = migrated / elapsed if elapsed > 0 else 0
                percent = migrated / diff * 100 if diff > 0 else 100
                print(
                    f"[Fix] {month_label} 已补迁移 {migrated:,} / ~{mysql_count:,} ({percent:.1f}%) "
                    f"| 本批 {count:,} 条 | 速度 {speed:.0f} 条/秒"
                )

            print(f"[Fix] {month_label} 补迁移完成，写入 {migrated:,} 条")

    # 迁移后验证
    print(f"\n{'=' * 60}")
    print(f"[Verify] 迁移后验证（统计行数对比）...")
    print(f"{'=' * 60}")

    all_ok = True
    for month_dt in months:
        range_start = month_dt.strftime("%Y-%m-01 00:00:00")
        next_month = month_dt + relativedelta(months=1)
        range_end = next_month.strftime("%Y-%m-01 00:00:00")
        month_label = month_dt.strftime("%Y-%m")

        print(f"\n--- 验证 {month_label} ---")
        mysql_count = count_mysql_data_by_range(mysql_conn, cfg, range_start, range_end)
        pg_count = count_pg_data_by_range(pg_conn, cfg, range_start, range_end)
        status = "OK" if mysql_count == pg_count else "MISMATCH"
        diff = mysql_count - pg_count
        diff_str = f" (差 {diff:,})" if diff != 0 else ""
        print(f"[Verify] {month_label}: MySQL={mysql_count:,}  PG={pg_count:,}  {status}{diff_str}")
        if diff != 0:
            all_ok = False

    if all_ok:
        print(f"\n[Verify] {table} 所有月份验证通过，数据完整")
    else:
        print(f"\n[Verify] {table} 仍有月份不一致，可能需要手动检查")

    # 刷新 device_list
    for step in cfg.get("additional_steps", []):
        if step == "refresh_device_list":
            refresh_device_list(pg_conn)


def main():
    parser = argparse.ArgumentParser(description="MySQL -> PostgreSQL (TimescaleDB) 数据迁移")
    parser.add_argument("--verify", action="store_true",
                        help="逐月复查数据完整性，发现差异自动补迁移")
    parser.add_argument("--force", action="store_true",
                        help="配合 --verify 使用：跳过慢的 COUNT 对比，直接删除 PG 每月数据并重新迁移")
    args = parser.parse_args()

    print("=" * 60)
    if args.verify:
        print("MySQL -> PostgreSQL 逐月复查模式")
        verify_tables = [t["name"] for t in TABLE_CONFIGS if t["name"] in VERIFY_CONFIG]
        print(f"复查表: {', '.join(verify_tables) if verify_tables else '无'}")
        if args.force:
            print("模式: 强制重迁移（删除后重新导入，跳过 COUNT 对比）")
    else:
        print("MySQL -> PostgreSQL (TimescaleDB) 数据迁移")
        print(f"时间范围: {START_DATE} 至今")
        print(f"迁移表: {', '.join(c['name'] for c in TABLE_CONFIGS)}")
    print("=" * 60)

    mysql_conn = get_mysql_connection()
    pg_conn = get_pg_connection()

    try:
        ensure_timescale_extension(pg_conn)

        if args.verify:
            # 逐月复查模式
            for cfg in TABLE_CONFIGS:
                if cfg["name"] in VERIFY_CONFIG:
                    try:
                        verify_and_fix_monthly(
                            mysql_conn, pg_conn, cfg,
                            VERIFY_CONFIG[cfg["name"]],
                            force=args.force
                        )
                    except Exception as e:
                        print(f"[Error] 表 {cfg['name']} 复查失败: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    print(f"\n[Skip] {cfg['name']} 未配置复查，跳过")
        else:
            # 常规迁移模式
            for cfg in TABLE_CONFIGS:
                try:
                    migrate_table(mysql_conn, pg_conn, cfg)
                except Exception as e:
                    print(f"[Error] 表 {cfg['name']} 迁移失败: {e}")
                    import traceback
                    traceback.print_exc()

    except KeyboardInterrupt:
        print("\n[Abort] 用户中断，下次运行会自动继续")
    except Exception as e:
        print(f"[Error] 出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        mysql_conn.close()
        pg_conn.close()
        print("[Cleanup] 连接已关闭")


if __name__ == "__main__":
    main()
