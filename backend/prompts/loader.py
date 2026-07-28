# cython: annotation_typing=False, infer_types=False, language_level=3
"""兼容层：保留旧导入路径 prompts.loader。"""

from modules.daily_report.prompts.loader import get_prompt_template, list_available_templates

__all__ = ["get_prompt_template", "list_available_templates"]
