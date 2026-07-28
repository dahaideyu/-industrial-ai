# cython: annotation_typing=False, infer_types=False, language_level=3
"""认证 API"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from backend.core.agentic_qa.database import get_db
from backend.services.agentic_qa.models.user import User
from backend.routes.agentic_qa.dependencies import create_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: dict


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not pwd_context.verify(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用")
    token = create_token(user.id, user.username)
    return LoginResponse(token=token, user=user.to_dict())


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {"user": current_user.to_dict()}
