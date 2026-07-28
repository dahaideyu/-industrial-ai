# cython: annotation_typing=False, infer_types=False, language_level=3
"""兼容层：保留旧导入路径 services.device_analyzer。"""

from modules.device_warning.services.device_analyzer import analyze_device

__all__ = ["analyze_device"]
