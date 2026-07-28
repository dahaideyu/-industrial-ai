# cython: annotation_typing=False, infer_types=False, language_level=3
"""FastAPI 认证依赖

统一模式（SQL_QA_UNIFIED_AUTH=true）：使用主 Agent 的 HMAC 令牌 + PostgreSQL sys_user
独立模式（默认）：使用 JWT 令牌 + SQLite users 表
"""
import os
import datetime
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from backend.core.agentic_qa.config import settings
from backend.core.agentic_qa.database import get_db
from backend.services.agentic_qa.models.user import User

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

security = HTTPBearer()


def create_token(user_id: int, username: str) -> str:
    """生成 JWT token（独立模式使用）"""
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "username": username, "exp": expire}
    return jwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)


def _is_unified_mode() -> bool:
    return os.getenv("SQL_QA_UNIFIED_AUTH", "false").lower() == "true"


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """获取当前用户

    统一模式：验证主 Agent HMAC 令牌，从 PostgreSQL sys_user 加载用户信息，返回 SimpleNamespace
    独立模式：验证 JWT，从 SQLite users 表加载 User ORM 对象
    """
    token = credentials.credentials

    if _is_unified_mode():
        # ---- 统一模式：HMAC 令牌 + PostgreSQL sys_user ----
        from backend.modules.auth.service import verify_token, get_user as get_pg_user

        username = verify_token(token)
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")

        user = get_pg_user(username)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")

        from types import SimpleNamespace
        return SimpleNamespace(**user)

    # ---- 独立模式：JWT 令牌 + SQLite users 表 ----
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证凭证")

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    return user
