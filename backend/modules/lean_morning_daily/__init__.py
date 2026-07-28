# cython: annotation_typing=False, infer_types=False, language_level=3
"""
精益早会日报模块
提供精益早会日报的生成、批量触发、工厂级报告等功能
"""
from .routes import router as lean_morning_daily_router

__all__ = ["lean_morning_daily_router"]