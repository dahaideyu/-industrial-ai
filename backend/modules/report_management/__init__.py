# cython: annotation_typing=False, infer_types=False, language_level=3
"""
报告管理模块
提供报告查询、下载、调试等功能
"""
from .routes import router as report_management_router

__all__ = ["report_management_router"]