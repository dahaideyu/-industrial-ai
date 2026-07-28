#!/usr/bin/env python
# cython: annotation_typing=False, infer_types=False, language_level=3
"""
SQLite → PostgreSQL 报告数据迁移脚本

用法:
    python backend/tools/migrate_sqlite_to_pg.py                        # 直接迁移
    python backend/tools/migrate_sqlite_to_pg.py --dry-run              # 预览不写入
    python backend/tools/migrate_sqlite_to_pg.py --sqlite-path /path/reports.db  # 指定 SQLite 路径

环境变量:
    PG_HOST   — PostgreSQL 地址（默认 127.0.0.1）
    PG_PORT   — PostgreSQL 端口（默认 5432）
    PG_DB     — 数据库名（默认 knowledge_base）
    PG_USER   — 用户名（默认 postgres）
    PG_PASSWORD — 密码
"""
import argparse
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, List, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 默认 SQLite 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "backend" / "data" / "reports.db"

# 批次大小
BATCH_SIZE = 100


def get_pg_connection():
    """创建 PostgreSQL 连接"""
    host = os.getenv("PG_HOST", "127.0.0.1")
    port = os.getenv("PG_PORT", "5432")
    dbname = os.getenv("PG_DB", "knowledge_base")
    user = os.getenv("PG_USER", "postgres")
    password = os.getenv("PG_PASSWORD", "")

    logger.info("连接 PostgreSQL: %s:%s/%s", host, port, dbname)
    return psycopg2.connect(
        host=host, port=int(port), dbname=dbname,
        user=user, password=password,
    )


def read_sqlite(sqlite_path: str) -> List[Tuple]:
    """读取 SQLite 全部数据"""
    logger.info("读取 SQLite: %s", sqlite_path)
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM ai_analysis_report ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    logger.info("共 %d 条记录", len(rows))
    return rows


def parse_create_time(raw: Any) -> str:
    """将 SQLite create_time 文本转为兼容 PG TIMESTAMPTZ 的格式"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # 常见格式: "2025-06-01 08:30:00" 或 "2025-06-01T08:30:00"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.isoformat()  # ISO 8601, PG 自动解析
        except ValueError:
            continue
    logger.warning("无法解析 create_time: %s，跳过该字段", text)
    return None


def ensure_table(pg_conn) -> None:
    """在 PG 中创建目标表（幂等）"""
    cur = pg_conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_analysis_report (
            id                      SERIAL PRIMARY KEY,
            report_code             TEXT        NOT NULL,
            title                   TEXT,
            period_label            TEXT,
            request_payload         TEXT,
            agent_response_raw      TEXT,
            agent_response_processed TEXT,
            markdown_content        TEXT,
            summary_markdown        TEXT,
            kb_report_markdown      TEXT,
            knowledge_base_payload  TEXT,
            status                  INTEGER     NOT NULL DEFAULT 0,
            error_message           TEXT,
            create_time             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            workshop_id             INTEGER     NOT NULL DEFAULT 0,
            date_type               TEXT        NOT NULL DEFAULT '',
            once_qualified_flag     INTEGER     NOT NULL DEFAULT 0,
            class_id                INTEGER     NOT NULL DEFAULT 0,
            procedure_id            INTEGER     NOT NULL DEFAULT 0,
            report_date             TEXT        NOT NULL DEFAULT '',
            CONSTRAINT uq_ai_analysis_report UNIQUE (
                report_code, workshop_id, date_type,
                once_qualified_flag, class_id, procedure_id, report_date
            )
        )
    """)
    pg_conn.commit()
    cur.close()


def migrate(sqlite_path: str, pg_conn, dry_run: bool = False) -> dict:
    """执行迁移，返回统计信息"""
    rows = read_sqlite(sqlite_path)
    if not rows:
        logger.info("SQLite 中无数据，无需迁移")
        return {"total": 0, "inserted": 0, "skipped": 0, "errors": 0}

    stats = {"total": len(rows), "inserted": 0, "skipped": 0, "errors": 0}

    cur = pg_conn.cursor()
    insert_sql = """
        INSERT INTO ai_analysis_report (
            report_code, title, period_label,
            request_payload, agent_response_raw, agent_response_processed,
            markdown_content, summary_markdown, kb_report_markdown, knowledge_base_payload,
            status, error_message, create_time,
            workshop_id, date_type, once_qualified_flag, class_id, procedure_id, report_date
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (report_code, workshop_id, date_type, once_qualified_flag, class_id, procedure_id, report_date)
        DO NOTHING
    """

    if dry_run:
        logger.info("=== 预览模式，不写入数据 ===")

    for i, row in enumerate(rows):
        try:
            create_time = parse_create_time(row["create_time"])
            # NULL → 默认值
            workshop_id = row["workshop_id"] or 0
            date_type = row["date_type"] or ""
            once_qualified_flag = row["once_qualified_flag"] or 0
            class_id = row["class_id"] or 0
            procedure_id = row["procedure_id"] or 0
            report_date = row["report_date"] or ""

            params = (
                row["report_code"], row["title"], row["period_label"],
                row["request_payload"], row["agent_response_raw"], row["agent_response_processed"],
                row["markdown_content"], row["summary_markdown"], row["kb_report_markdown"],
                row["knowledge_base_payload"],
                row["status"], row["error_message"], create_time,
                workshop_id, date_type, once_qualified_flag, class_id, procedure_id, report_date,
            )

            if dry_run:
                stats["inserted"] += 1
            else:
                cur.execute(insert_sql, params)
                stats["inserted"] += 1

        except Exception as e:
            logger.error("第 %d 行迁移失败: %s", i + 1, e)
            stats["errors"] += 1

        # 每 BATCH_SIZE 行提交一次
        if not dry_run and (i + 1) % BATCH_SIZE == 0:
            pg_conn.commit()
            logger.info("已提交 %d/%d 条", i + 1, len(rows))

    if not dry_run:
        pg_conn.commit()
        # 查询实际插入数（通过序列增长量判断）
        cur.execute("SELECT COUNT(*) as cnt FROM ai_analysis_report")
        actual_count = cur.fetchone()[0]
        stats["actual_table_count"] = actual_count

    cur.close()
    return stats


def main():
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 报告数据迁移")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不写入数据")
    parser.add_argument("--sqlite-path", type=str, default=str(DEFAULT_SQLITE_PATH),
                        help=f"SQLite 文件路径（默认: {DEFAULT_SQLITE_PATH}）")
    args = parser.parse_args()

    if not os.path.isfile(args.sqlite_path):
        logger.error("SQLite 文件不存在: %s", args.sqlite_path)
        sys.exit(1)

    pg_conn = get_pg_connection()
    try:
        ensure_table(pg_conn)
        stats = migrate(args.sqlite_path, pg_conn, dry_run=args.dry_run)
        logger.info("=" * 50)
        logger.info("迁移完成!")
        logger.info("  总记录数:   %d", stats["total"])
        logger.info("  已处理:     %d", stats["inserted"])
        logger.info("  跳过/冲突:  %d", stats["skipped"])
        logger.info("  错误:       %d", stats["errors"])
        if stats.get("actual_table_count") is not None:
            logger.info("  表内总数:   %d", stats["actual_table_count"])
        if args.dry_run:
            logger.info("  (预览模式，未实际写入)")
        logger.info("=" * 50)
    finally:
        pg_conn.close()


if __name__ == "__main__":
    main()
