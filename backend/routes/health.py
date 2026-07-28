# cython: annotation_typing=False, infer_types=False, language_level=3
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health_check():
    """健康检查端点"""
    return {"status": "ok"}
