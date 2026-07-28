# cython: annotation_typing=False, infer_types=False, language_level=3
"""
设备效率报告模块
提供设备效率日/周/月报告的生成功能
"""
from .routes import router as device_efficiency_router

__all__ = ["device_efficiency_router"]