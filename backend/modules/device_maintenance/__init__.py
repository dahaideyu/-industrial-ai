# cython: annotation_typing=False, infer_types=False, language_level=3
"""
设备运维报告模块
提供设备运维周报/月报的AI生成能力
"""
from .routes import router as device_maintenance_router

__all__ = ["device_maintenance_router"]
