# cython: annotation_typing=False, infer_types=False, language_level=3
"""
质量概览报告模块
提供质量日/周/月报告的生成功能
"""
from .routes import router as quality_overview_router

__all__ = ["quality_overview_router"]