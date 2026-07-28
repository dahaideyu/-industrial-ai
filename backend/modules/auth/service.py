# cython: annotation_typing=False, infer_types=False, language_level=3
"""
认证服务：用户表管理、密码哈希、签名令牌

依赖仅使用 Python 标准库（hashlib / hmac / secrets / base64），
不引入额外第三方包（venv 内无 PyJWT / passlib），便于在公司网络（cntlm 代理）下部署。

- 密码哈希：pbkdf2_hmac(sha256)，存储格式 `pbkdf2_sha256$iterations$salt_hex$hash_hex`
- 登录令牌：HMAC-SHA256 签名的无状态 token，格式 `base64(payload).base64(sig)`
- 用户表：public.sys_user（与业务时序表区分，sys_ 前缀表示系统/账号表）
"""

import os
import time
import json
import hmac
import base64
import hashlib
import secrets
import logging

from psycopg2.extras import RealDictCursor

from modules.device_warning.ai_analysis.postgres_loader import PostgresPool

logger = logging.getLogger(__name__)

# 令牌签名密钥：优先读环境变量，未配置则用默认值（生产请在 .env 设置 AUTH_SECRET）
AUTH_SECRET = os.getenv("AUTH_SECRET", "chaowei-agent-default-secret-change-me")
# 令牌有效期（秒），默认 7 天
TOKEN_TTL = int(os.getenv("AUTH_TOKEN_TTL", str(7 * 24 * 3600)))
# 初始管理员账号（仅在用户表为空时种入）
DEFAULT_ADMIN_USERNAME = os.getenv("AUTH_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("AUTH_ADMIN_PASSWORD", "adminchaowei123")

PBKDF2_ITERATIONS = 200_000


# ============================================================
# 密码哈希
# ============================================================
def hash_password(password: str) -> str:
    """生成 pbkdf2_sha256 密码哈希字符串"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验明文密码是否匹配存储的哈希"""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ============================================================
# 签名令牌（无状态）
# ============================================================
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(body: str) -> str:
    return _b64e(hmac.new(AUTH_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())


def create_token(username: str) -> str:
    """生成登录令牌"""
    payload = {"sub": username, "exp": int(time.time()) + TOKEN_TTL}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body)}"


def verify_token(token: str):
    """校验令牌，返回用户名（失败/过期返回 None）"""
    if not token:
        return None
    try:
        body, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        payload = json.loads(_b64d(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload.get("sub")
    except Exception:
        return None


# ============================================================
# 用户表（public.sys_user）
# ============================================================
def ensure_user_table() -> None:
    """创建用户表（若不存在）并种入默认管理员账号"""
    pool = PostgresPool()
    conn = pool.get_connection()
    if not conn:
        raise RuntimeError("数据库连接失败，无法初始化用户表")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sys_user (
                    id            SERIAL PRIMARY KEY,
                    username      VARCHAR(64)  UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    display_name  VARCHAR(128),
                    role          VARCHAR(32)  NOT NULL DEFAULT 'admin',
                    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
                    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
                    last_login_at TIMESTAMPTZ
                );
                """
            )
            conn.commit()

            cur.execute("SELECT 1 FROM sys_user WHERE username = %s", (DEFAULT_ADMIN_USERNAME,))
            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO sys_user (username, password_hash, display_name, role)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        DEFAULT_ADMIN_USERNAME,
                        hash_password(DEFAULT_ADMIN_PASSWORD),
                        "管理员",
                        "admin",
                    ),
                )
                conn.commit()
                logger.info(f"[auth] 已种入默认管理员账号: {DEFAULT_ADMIN_USERNAME}")
    finally:
        pool.release_connection(conn)


def _row_to_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
    }


def authenticate(username: str, password: str):
    """校验用户名/密码，成功返回用户信息 dict，失败返回 None"""
    pool = PostgresPool()
    conn = pool.get_connection()
    if not conn:
        raise RuntimeError("数据库连接失败")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM sys_user WHERE username = %s AND is_active = TRUE",
                (username,),
            )
            row = cur.fetchone()
            if not row or not verify_password(password, row["password_hash"]):
                return None
            cur.execute("UPDATE sys_user SET last_login_at = now() WHERE id = %s", (row["id"],))
            conn.commit()
            return _row_to_user(row)
    finally:
        pool.release_connection(conn)


def get_user(username: str):
    """按用户名查询用户信息（用于 /me）"""
    pool = PostgresPool()
    conn = pool.get_connection()
    if not conn:
        raise RuntimeError("数据库连接失败")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM sys_user WHERE username = %s AND is_active = TRUE",
                (username,),
            )
            row = cur.fetchone()
            return _row_to_user(row) if row else None
    finally:
        pool.release_connection(conn)
