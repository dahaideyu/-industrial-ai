# cython: annotation_typing=False, infer_types=False, language_level=3
"""
提示词模板加载器
根据报告类型加载对应的提示词模板（支持加密）
"""

from typing import Dict, Optional

from backend.utils.prompt_loader import prompt_loader

# 报告类型到模板文件的映射
TEMPLATE_MAPPING = {
    # 设备级别报告
    "device_daily_report": "device_daily_report.txt",
    "device_weekly_report": "device_weekly_report.txt",
    "device_monthly_report": "device_monthly_report.txt",
    # 车间汇总报告
    "workshop_daily_summary": "workshop_daily_summary.txt",
    "workshop_weekly_summary": "workshop_weekly_summary.txt",
    "workshop_monthly_summary": "workshop_monthly_summary.txt",
}

# 简化的映射（支持 daily/weekly/monthly 格式）
SIMPLE_MAPPING = {
    "daily": "device_daily_report.txt",
    "weekly": "device_weekly_report.txt",
    "monthly": "device_monthly_report.txt",
}


def get_prompt_template(report_type: str) -> Optional[str]:
    """
    根据报告类型获取对应的提示词模板

    Args:
        report_type: 报告类型，如 "daily", "device_daily_report"

    Returns:
        提示词模板字符串，如果找不到则返回 None
    """
    # 尝试完整映射
    template_file = TEMPLATE_MAPPING.get(report_type)

    # 如果没找到，尝试简化映射
    if not template_file:
        template_file = SIMPLE_MAPPING.get(report_type)

    if not template_file:
        return None

    try:
        # 使用加密加载器，会自动尝试明文和解密
        return prompt_loader.get_prompt(template_file)
    except FileNotFoundError:
        return None


def list_available_templates() -> Dict[str, str]:
    """
    列出所有可用的报告类型及其模板文件

    Returns:
        字典，key 为报告类型，value 为模板文件名
    """
    return TEMPLATE_MAPPING.copy()


def get_template_info(report_type: str) -> Optional[Dict]:
    """
    获取模板信息

    Returns:
        包含模板路径和是否存在的字典
    """
    template_file = TEMPLATE_MAPPING.get(report_type) or SIMPLE_MAPPING.get(report_type)
    if not template_file:
        return None

    return {
        "report_type": report_type,
        "template_file": template_file,
        "exists": prompt_loader.has_prompt(template_file),
    }
