# cython: annotation_typing=False, infer_types=False, language_level=3
# services package

try:
    from backend.services.report_generator import get_report_generator
    __all__ = ["get_report_generator"]
except ImportError:
    # Agent 服务模块不可用时静默跳过（SQL-QA 子项目不需要这些）
    pass
