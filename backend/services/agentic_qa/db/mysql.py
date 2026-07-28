# cython: annotation_typing=False, infer_types=False, language_level=3
import pymysql
from pymysql.cursors import DictCursor
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from backend.core.agentic_qa.config import settings
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("db.mysql")


class MySQLPool:
    def __init__(self):
        self.host = settings.mysql_host
        self.port = settings.mysql_port
        self.user = settings.mysql_user
        self.password = settings.mysql_password
        self.database = settings.mysql_database

    @contextmanager
    def get_connection(self):
        conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset='utf8mb4',
            cursorclass=DictCursor
        )
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def get_cursor(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()

    def execute_query(self, sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """执行查询"""
        logger.debug(f"[db] executing: {sql[:200]}")
        with self.get_cursor() as cursor:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            rows = cursor.fetchall()
            logger.debug(f"[db] returned {len(rows)} rows")
            return rows

    def execute_one(self, sql: str, params: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
        with self.get_cursor() as cursor:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            return cursor.fetchone()


db = MySQLPool()


def get_table_schema(table_name: str) -> Dict[str, Any]:
    """获取表结构信息"""
    sql = f"DESCRIBE {table_name}"
    columns = db.execute_query(sql)
    return {
        "table_name": table_name,
        "columns": [
            {
                "name": col["Field"],
                "type": col["Type"],
                "null": col["Null"],
                "key": col["Key"],
                "default": col["Default"],
                "extra": col["Extra"]
            }
            for col in columns
        ]
    }


def get_all_tables() -> List[str]:
    """获取所有表名"""
    sql = "SHOW TABLES"
    rows = db.execute_query(sql)
    return [list(row.values())[0] for row in rows]
