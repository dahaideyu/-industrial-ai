# cython: annotation_typing=False, infer_types=False, language_level=3
"""WebSocket 端点 — 实时推送 Agentic QA 步骤状态"""
import json
import os
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from typing import Dict
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("api.ws")
router = APIRouter()

_active_connections: Dict[str, WebSocket] = {}


def get_connection(session_id: str):
    return _active_connections.get(session_id)


async def push_step(session_id: str, step: dict):
    ws = _active_connections.get(session_id)
    if ws:
        try:
            await ws.send_json({"type": "step_update", "data": step})
        except Exception:
            _active_connections.pop(session_id, None)


async def push_complete(session_id: str, result: dict):
    ws = _active_connections.get(session_id)
    if ws:
        try:
            await ws.send_json({"type": "complete", "data": result})
        except Exception:
            _active_connections.pop(session_id, None)


def _verify_ws_token(token: str):
    """验证 WebSocket token。统一模式用 HMAC，独立模式用 JWT。"""
    if os.getenv("SQL_QA_UNIFIED_AUTH", "false").lower() == "true":
        from backend.modules.auth.service import verify_token, get_user
        username = verify_token(token)
        if not username:
            return None
        return get_user(username)

    from jose import JWTError, jwt
    from backend.core.agentic_qa.config import settings
    from backend.core.agentic_qa.database import SessionLocal
    from backend.services.agentic_qa.models.user import User

    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, TypeError):
        return None

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            return None
        return user
    finally:
        db.close()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, token: str = Query(...)):
    if not _verify_ws_token(token):
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    _active_connections[session_id] = websocket
    logger.info(f"[ws] connected session={session_id}")
    await websocket.send_json({"type": "connected", "session_id": session_id})
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info(f"[ws] disconnected session={session_id}")
    finally:
        _active_connections.pop(session_id, None)
