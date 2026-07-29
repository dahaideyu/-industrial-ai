# cython: annotation_typing=False, infer_types=False, language_level=3
"""
PostgreSQL 数据库模块
封装报告记录的建表、Upsert、查询操作

环境变量：统一使用 PG_*（旧名兼容见 core/pg_env.py）
"""
import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# 兼容旧调用者仍传 db_path 参数（PG 下忽略，仅保留默认值供引用）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "backend", "data", "reports.db")

# 连接池（惰性初始化）
_pg_pool: Optional[pool.ThreadedConnectionPool] = None
_pool_lock = threading.Lock()


def _get_pg_config() -> Dict[str, str]:
    """读取 PG 连接参数（默认值统一在 core.pg_env 定义，此处不再各写一套）"""
    from core.pg_env import pg_env
    host = pg_env("PG_HOST")
    port = pg_env("PG_PORT")
    dbname = pg_env("PG_DB")
    user = pg_env("PG_USER")
    password = pg_env("PG_PASSWORD")
    return {
        "host": host,
        "port": int(port),
        "dbname": dbname,
        "user": user,
        "password": password,
    }


def _get_pool() -> pool.ThreadedConnectionPool:
    """获取连接池（惰性初始化，线程安全）"""
    global _pg_pool
    if _pg_pool is None:
        with _pool_lock:
            if _pg_pool is None:
                cfg = _get_pg_config()
                logger.info("[数据库] 初始化 PG 连接池: %s:%s/%s", cfg["host"], cfg["port"], cfg["dbname"])
                _pg_pool = pool.ThreadedConnectionPool(minconn=2, maxconn=20, **cfg)
    return _pg_pool


def _get_conn() -> psycopg2.extensions.connection:
    """从连接池获取连接"""
    return _get_pool().getconn()


def _put_conn(conn: psycopg2.extensions.connection) -> None:
    """归还连接到池（忽略异常）"""
    if conn is not None:
        try:
            _get_pool().putconn(conn)
        except Exception:
            pass


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    初始化数据库连接并建表/建索引

    Args:
        db_path: 兼容旧参数，PG 下忽略
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            # 建表（幂等）
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

            # 建索引（幂等）
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_report_code_time
                ON ai_analysis_report(report_code, create_time)
            """)

            # 迁移：为旧表补充 agent_response_processed 列（幂等）
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'ai_analysis_report'
                          AND column_name = 'agent_response_processed'
                    ) THEN
                        ALTER TABLE ai_analysis_report
                        ADD COLUMN agent_response_processed TEXT;
                    END IF;
                END $$;
            """)

        conn.commit()
        logger.info("[数据库] ai_analysis_report 表初始化完成")
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_conn(conn)


def upsert_report(
    report_code: str,
    title: str,
    period_label: str,
    request_payload: dict,
    agent_response_raw: Any,
    status: int,
    error_message: str,
    workshop_id: Optional[int] = None,
    date_type: Optional[str] = None,
    once_qualified_flag: Optional[int] = None,
    class_id: Optional[int] = None,
    procedure_id: Optional[int] = None,
    report_date: Optional[str] = None,
    markdown_content: str = "",
    summary_markdown: str = "",
    kb_report_markdown: str = "",
    knowledge_base_payload: str = "",
    agent_response_processed: str = "",
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """
    插入或更新报告记录。
    唯一键冲突时覆盖旧记录，返回受影响行的 id。

    Args:
        report_code: 报告类型编码
        title: 标题
        period_label: 账期标签
        request_payload: 原始请求 JSON
        agent_response_raw: Agent 原始响应（字符串或字典）
        status: 0 成功 1 失败
        error_message: 失败原因
        workshop_id: 车间 ID
        date_type: 日期类型
        once_qualified_flag: 一次合格标志
        class_id: 班次 ID
        procedure_id: 工序 ID
        report_date: 报告日期 YYYY-MM-DD
        markdown_content: 第一份报告 Markdown 内容
        summary_markdown: 第二份报告 Markdown 内容
        kb_report_markdown: 第三份报告 Markdown 内容
        knowledge_base_payload: 知识库信息 JSON
        agent_response_processed: 预处理后的数据 JSON
        db_path: 兼容旧参数，PG 下忽略

    Returns:
        受影响记录的主键 id
    """
    # NULL → 默认值：PG UNIQUE 约束中 NULL ≠ NULL，统一用 0/'' 确保匹配
    if workshop_id is None:
        workshop_id = 0
    if date_type is None:
        date_type = ""
    if once_qualified_flag is None:
        once_qualified_flag = 0
    if class_id is None:
        class_id = 0
    if procedure_id is None:
        procedure_id = 0
    if report_date is None:
        report_date = ""

    request_payload_str = json.dumps(request_payload, ensure_ascii=False) if isinstance(request_payload, dict) else str(request_payload)
    if isinstance(agent_response_raw, dict):
        agent_response_raw_str = json.dumps(agent_response_raw, ensure_ascii=False)
    else:
        agent_response_raw_str = str(agent_response_raw)

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO ai_analysis_report (
                    report_code, title, period_label,
                    request_payload, agent_response_raw, agent_response_processed,
                    markdown_content, summary_markdown, kb_report_markdown, knowledge_base_payload,
                    status, error_message,
                    workshop_id, date_type, once_qualified_flag, class_id, procedure_id, report_date
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (report_code, workshop_id, date_type, once_qualified_flag, class_id, procedure_id, report_date)
                DO UPDATE SET
                    title                = EXCLUDED.title,
                    period_label         = EXCLUDED.period_label,
                    request_payload      = EXCLUDED.request_payload,
                    agent_response_raw   = EXCLUDED.agent_response_raw,
                    agent_response_processed = EXCLUDED.agent_response_processed,
                    markdown_content     = EXCLUDED.markdown_content,
                    summary_markdown     = EXCLUDED.summary_markdown,
                    kb_report_markdown   = EXCLUDED.kb_report_markdown,
                    knowledge_base_payload = EXCLUDED.knowledge_base_payload,
                    status               = EXCLUDED.status,
                    error_message        = EXCLUDED.error_message,
                    create_time          = NOW()
                RETURNING id
            """, (
                report_code, title, period_label,
                request_payload_str, agent_response_raw_str, agent_response_processed,
                markdown_content, summary_markdown, kb_report_markdown, knowledge_base_payload,
                status, error_message,
                workshop_id, date_type, once_qualified_flag, class_id, procedure_id, report_date
            ))
            row = cur.fetchone()
            row_id = row["id"] if row else 0
        conn.commit()
        return row_id
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_conn(conn)


def query_reports(
    report_code: Optional[str] = None,
    workshop_id: Optional[int] = None,
    date_type: Optional[str] = None,
    once_qualified_flag: Optional[int] = None,
    class_id: Optional[int] = None,
    procedure_id: Optional[int] = None,
    report_date: Optional[str] = None,
    report_date_from: Optional[str] = None,
    report_date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    分页查询报告列表（不含大字段 agent_response_raw 和 request_payload）

    Returns:
        {"list": [...], "total": int, "page": int, "page_size": int}
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 20
    if page_size > 100:
        page_size = 100

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 构建查询条件
            conditions = []
            params = []

            if report_code is not None:
                conditions.append("report_code = %s")
                params.append(report_code)
            if workshop_id is not None:
                conditions.append("workshop_id = %s")
                params.append(workshop_id)
            if date_type is not None:
                conditions.append("date_type = %s")
                params.append(date_type)
            if once_qualified_flag is not None:
                conditions.append("once_qualified_flag = %s")
                params.append(once_qualified_flag)
            if class_id is not None:
                conditions.append("class_id = %s")
                params.append(class_id)
            if procedure_id is not None:
                conditions.append("procedure_id = %s")
                params.append(procedure_id)
            if report_date is not None:
                conditions.append("report_date = %s")
                params.append(report_date)
            if report_date_from is not None:
                conditions.append("report_date >= %s")
                params.append(report_date_from)
            if report_date_to is not None:
                conditions.append("report_date < %s")
                params.append(report_date_to)

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            # 查询总数
            count_sql = f"SELECT COUNT(*) as cnt FROM ai_analysis_report WHERE {where_clause}"
            cur.execute(count_sql, params)
            total = cur.fetchone()["cnt"]

            # 分页查询
            offset = (page - 1) * page_size
            query_sql = """
                SELECT id, report_code, title, period_label, status, error_message,
                       workshop_id, date_type, once_qualified_flag, class_id, procedure_id,
                       report_date, create_time
                FROM ai_analysis_report
                WHERE {}
                ORDER BY create_time DESC
                LIMIT %s OFFSET %s
            """.format(where_clause)
            cur.execute(query_sql, params + [page_size, offset])
            rows = cur.fetchall()

        return {
            "total": total,
            "list": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
        }
    finally:
        _put_conn(conn)


def get_report_by_business_key(
    report_code: str,
    workshop_id: Optional[int] = None,
    date_type: Optional[str] = None,
    once_qualified_flag: Optional[int] = None,
    class_id: Optional[int] = None,
    procedure_id: Optional[int] = None,
    report_date: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """
    按业务字段查询单条报告详情（含所有大字段）
    参数为 None 的字段不参与 WHERE 条件
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = ["report_code = %s"]
            params: List[Any] = [report_code]

            if workshop_id is not None:
                conditions.append("workshop_id = %s")
                params.append(workshop_id)
            if date_type is not None:
                conditions.append("date_type = %s")
                params.append(date_type)
            if once_qualified_flag is not None:
                conditions.append("once_qualified_flag = %s")
                params.append(once_qualified_flag)
            if class_id is not None:
                conditions.append("class_id = %s")
                params.append(class_id)
            if procedure_id is not None:
                conditions.append("procedure_id = %s")
                params.append(procedure_id)
            if report_date is not None:
                conditions.append("report_date = %s")
                params.append(report_date)

            where_clause = " AND ".join(conditions)
            cur.execute(
                f"SELECT * FROM ai_analysis_report WHERE {where_clause}",
                params
            )
            row = cur.fetchone()

        return dict(row) if row else None
    finally:
        _put_conn(conn)


def get_report_detail(
    report_code: str,
    report_date: str,
    db_path: str = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """
    根据 report_code + report_date 查询详情
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM ai_analysis_report
                WHERE report_code = %s AND report_date = %s
                ORDER BY create_time DESC
                LIMIT 1
            """, (report_code, report_date))
            row = cur.fetchone()

        return dict(row) if row else None
    finally:
        _put_conn(conn)


def query_quality_historical_reports(
    report_code: str,
    period_label: str = "",
    periods: int = 5,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """
    查询质量报告历史（按 period_label 降序，排除当前账期）
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if period_label:
                cur.execute("""
                    SELECT * FROM ai_analysis_report
                    WHERE report_code = %s AND status = 0 AND period_label != %s
                    ORDER BY period_label DESC
                    LIMIT %s
                """, (report_code, period_label, periods))
            else:
                cur.execute("""
                    SELECT * FROM ai_analysis_report
                    WHERE report_code = %s AND status = 0
                    ORDER BY period_label DESC
                    LIMIT %s
                """, (report_code, periods))
            rows = cur.fetchall()

        return [dict(row) for row in rows]
    finally:
        _put_conn(conn)


def query_workshop_reports_by_date(
    report_date: str,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """
    按日期查询所有车间报告（用于工厂级报告生成）
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM ai_analysis_report
                WHERE report_date = %s AND status = 0
                ORDER BY workshop_id, procedure_id
            """, (report_date,))
            rows = cur.fetchall()

        return [dict(row) for row in rows]
    finally:
        _put_conn(conn)


def query_device_efficiency_historical_reports(
    report_code: str,
    workshop_id: Optional[int] = None,
    limit: int = 5,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """
    查询设备效率报告历史
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if workshop_id is not None:
                cur.execute("""
                    SELECT * FROM ai_analysis_report
                    WHERE report_code = %s AND workshop_id = %s AND status = 0
                    ORDER BY report_date DESC
                    LIMIT %s
                """, (report_code, workshop_id, limit))
            else:
                cur.execute("""
                    SELECT * FROM ai_analysis_report
                    WHERE report_code = %s AND status = 0
                    ORDER BY report_date DESC
                    LIMIT %s
                """, (report_code, limit))
            rows = cur.fetchall()

        return [dict(row) for row in rows]
    finally:
        _put_conn(conn)


def query_reports_distinct_by_date(
    report_code: str,
    workshop_id: Optional[int] = None,
    procedure_id: Optional[int] = None,
    report_date_from: Optional[str] = None,
    report_date_to: Optional[str] = None,
    status: Optional[int] = 0,
    limit: int = 6,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """
    按 report_date 去重查询报告，每个日期只取最新一条（按 create_time）
    用于精益早会日报、设备效率报告的历史加载

    Args:
        report_code: 报告类型编码
        workshop_id: 车间 ID（可选）
        procedure_id: 工序 ID（可选）
        report_date_from: 报告日期范围起点（>=）
        report_date_to: 报告日期范围终点（<）
        status: 报告状态过滤，默认 0（成功），传 None 不过滤
        limit: 返回的最大日期数

    Returns:
        去重后的报告列表，每个 report_date 最多一条，按 report_date DESC 排序
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = ["report_code = %s"]
            params: List[Any] = [report_code]

            if status is not None:
                conditions.append("status = %s")
                params.append(status)
            if workshop_id is not None:
                conditions.append("workshop_id = %s")
                params.append(workshop_id)
            if procedure_id is not None:
                conditions.append("procedure_id = %s")
                params.append(procedure_id)
            if report_date_from is not None:
                conditions.append("report_date >= %s")
                params.append(report_date_from)
            if report_date_to is not None:
                conditions.append("report_date < %s")
                params.append(report_date_to)

            where_clause = " AND ".join(conditions)

            sql = """
                SELECT a.* FROM ai_analysis_report a
                INNER JOIN (
                    SELECT report_date, MAX(create_time) as max_ct
                    FROM ai_analysis_report
                    WHERE {}
                    GROUP BY report_date
                    ORDER BY report_date DESC
                    LIMIT %s
                ) b ON a.report_date = b.report_date AND a.create_time = b.max_ct
                WHERE a.report_code = %s
                ORDER BY a.report_date DESC
            """.format(where_clause)
            all_params = params + [limit, report_code]
            cur.execute(sql, all_params)
            rows = cur.fetchall()

        return [dict(row) for row in rows]
    finally:
        _put_conn(conn)


def query_reports_distinct_by_period_label(
    report_code: str,
    period_label_exclude: str = "",
    workshop_id: Optional[int] = None,
    status: Optional[int] = 0,
    limit: int = 6,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """
    按 period_label 去重查询报告，每个账期只取最新一条（按 create_time）
    用于质量概览报告、设备效率报告的历史加载

    Args:
        report_code: 报告类型编码
        period_label_exclude: 排除的账期标签
        workshop_id: 车间 ID（可选）
        status: 报告状态过滤，默认 0（成功），传 None 不过滤
        limit: 返回的最大账期数

    Returns:
        去重后的报告列表，每个 period_label 最多一条，按 period_label DESC 排序
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = ["report_code = %s"]
            params: List[Any] = [report_code]

            if status is not None:
                conditions.append("status = %s")
                params.append(status)
            if workshop_id is not None:
                conditions.append("workshop_id = %s")
                params.append(workshop_id)
            if period_label_exclude:
                conditions.append("period_label != %s")
                params.append(period_label_exclude)

            where_clause = " AND ".join(conditions)

            sql = """
                SELECT a.* FROM ai_analysis_report a
                INNER JOIN (
                    SELECT period_label, MAX(create_time) as max_ct
                    FROM ai_analysis_report
                    WHERE {}
                    GROUP BY period_label
                    ORDER BY period_label DESC
                    LIMIT %s
                ) b ON a.period_label = b.period_label AND a.create_time = b.max_ct
                WHERE a.report_code = %s
                ORDER BY a.period_label DESC
            """.format(where_clause)
            all_params = params + [limit, report_code]
            cur.execute(sql, all_params)
            rows = cur.fetchall()

        return [dict(row) for row in rows]
    finally:
        _put_conn(conn)
