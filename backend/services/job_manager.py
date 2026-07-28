# cython: annotation_typing=False, infer_types=False, language_level=3
"""兼容层：保留旧导入路径 services.job_manager。"""

from modules.device_warning.services.job_manager import get_jobs, get_summary, get_job_history

__all__ = ["get_jobs", "get_summary", "get_job_history"]
