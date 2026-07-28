# cython: annotation_typing=False, infer_types=False, language_level=3
"""
认证 API 路由

- POST /api/auth/login   登录，返回签名令牌 + 用户信息
- GET  /api/auth/me      校验令牌并返回当前用户
- POST /api/auth/logout  退出（无状态令牌，仅供前端清理，统一返回成功）
"""

import logging

from fastapi import APIRouter, Header
from pydantic import BaseModel

from core.response import success_response, error_response
from . import service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def _token_from_header(authorization: str | None) -> str:
    if not authorization:
        return ""
    return authorization.replace("Bearer ", "").replace("bearer ", "").strip()


@router.post("/login")
def login(data: LoginRequest):
    """用户名/密码登录"""
    try:
        user = service.authenticate(data.username.strip(), data.password)
    except Exception as e:
        logger.error(f"[auth] 登录异常: {e}", exc_info=True)
        return error_response(msg=f"登录失败: {e}", code=500)

    if not user:
        return error_response(msg="用户名或密码错误", code=401, status_code=401)

    token = service.create_token(user["username"])
    return success_response(data={"token": token, "user": user}, msg="登录成功")


@router.get("/me")
def me(authorization: str | None = Header(default=None)):
    """根据令牌返回当前用户信息"""
    username = service.verify_token(_token_from_header(authorization))
    if not username:
        return error_response(msg="未登录或登录已过期", code=401, status_code=401)
    try:
        user = service.get_user(username)
    except Exception as e:
        return error_response(msg=f"查询用户失败: {e}", code=500)
    if not user:
        return error_response(msg="用户不存在或已禁用", code=401, status_code=401)
    return success_response(data=user)


@router.post("/logout")
def logout():
    """退出登录（无状态令牌，前端清理本地存储即可）"""
    return success_response(msg="已退出登录")
