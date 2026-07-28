# cython: annotation_typing=False, infer_types=False, language_level=3
"""
提示词模板加载器
根据报告类型加载对应的提示词模板（支持加密）
"""

from typing import Dict, Optional

from backend.utils.prompt_loader import prompt_loader

# 报告类型到模板文件的映射
TEMPLATE_MAPPING = {
    "qualityWeekReport": "quality_weekly_report.txt",
    "leanQualityWeekReport": "lean_quality_weekly_report01.txt",
    "leanQualityWeekReport01": "lean_quality_weekly_report01.txt",
    "leanQualityWeekReport02": "lean_quality_weekly_report02.txt",
    "leanQualityWeekReport03": "lean_quality_weekly_report03.txt",
    "leanMorningDailyReport": "lean_morning_daily_report.txt",
    # 设备效率报告 - 工厂级日报
    "deviceFactoryDailyReport01": "device_factory_daily_report01.txt",
    "deviceFactoryDailyReport02": "device_factory_daily_report02.txt",
    "deviceFactoryDailyReport03": "device_factory_daily_report03.txt",
    # 设备效率报告 - 工厂级周报
    "deviceFactoryWeeklyReport01": "device_factory_weekly_report01.txt",
    "deviceFactoryWeeklyReport02": "device_factory_weekly_report02.txt",
    "deviceFactoryWeeklyReport03": "device_factory_weekly_report03.txt",
    # 设备效率报告 - 工厂级月报
    "deviceFactoryMonthlyReport01": "device_factory_monthly_report01.txt",
    "deviceFactoryMonthlyReport02": "device_factory_monthly_report02.txt",
    "deviceFactoryMonthlyReport03": "device_factory_monthly_report03.txt",
    # 设备效率报告 - 车间级日报
    "deviceWorkshopDailyReport01": "device_workshop_daily_report01.txt",
    "deviceWorkshopDailyReport02": "device_workshop_daily_report02.txt",
    "deviceWorkshopDailyReport03": "device_workshop_daily_report03.txt",
    # 设备效率报告 - 车间级周报
    "deviceWorkshopWeeklyReport01": "device_workshop_weekly_report01.txt",
    "deviceWorkshopWeeklyReport02": "device_workshop_weekly_report02.txt",
    "deviceWorkshopWeeklyReport03": "device_workshop_weekly_report03.txt",
    # 设备效率报告 - 车间级月报
    "deviceWorkshopMonthlyReport01": "device_workshop_monthly_report01.txt",
    "deviceWorkshopMonthlyReport02": "device_workshop_monthly_report02.txt",
    "deviceWorkshopMonthlyReport03": "device_workshop_monthly_report03.txt",
}


def get_prompt_template(report_type: str) -> Optional[str]:
    """
    根据报告类型获取对应的提示词模板

    Args:
        report_type: 报告类型，如 "qualityWeekReport"

    Returns:
        提示词模板字符串，如果找不到则返回 None
    """
    template_file = TEMPLATE_MAPPING.get(report_type)
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
