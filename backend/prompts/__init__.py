# cython: annotation_typing=False, infer_types=False, language_level=3
# 提示词模板模块（兼容旧导入路径）
from modules.daily_report.prompts.loader import get_prompt_template, list_available_templates

__all__ = ["get_prompt_template", "list_available_templates"]
