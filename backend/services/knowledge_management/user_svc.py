# cython: annotation_typing=False, infer_types=False, language_level=3
"""用户服务 — 对接 AQA sys_user 表"""
import pymysql
from pymysql.cursors import DictCursor
from backend.core.knowledge_management.config import settings


class UserService:

    def get_user_from_aqa(self, username: str) -> dict | None:
        conn = pymysql.connect(
            host=settings.aqa_mysql_host, port=settings.aqa_mysql_port,
            user=settings.aqa_mysql_user, password=settings.aqa_mysql_password,
            database=settings.aqa_mysql_database, charset='utf8mb4',
        )
        try:
            with conn.cursor(DictCursor) as cursor:
                cursor.execute(
                    "SELECT id, username, real_name, dept_id FROM sys_user WHERE username=%s",
                    (username,))
                return cursor.fetchone()
        finally:
            conn.close()


user_svc = UserService()
