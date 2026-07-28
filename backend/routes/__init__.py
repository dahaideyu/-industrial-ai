# cython: annotation_typing=False, infer_types=False, language_level=3
try:
    from .health import router as health_router
    from .report import router as report_router
    from .analysis import router as analysis_router
    from .jobs import router as jobs_router
    from .document import router as document_router
    from .alarms import router as alarms_router
    from .system_jobs import router as system_jobs_router

    __all__ = ["health_router", "report_router", "analysis_router", "jobs_router", "document_router", "alarms_router", "system_jobs_router"]
except ImportError as e:
    # Agent 路由模块不可用时静默跳过（SQL-QA 子项目不需要这些）
    import logging
    logging.getLogger(__name__).warning(f"部分路由模块加载失败，已跳过: {e}")
    pass
