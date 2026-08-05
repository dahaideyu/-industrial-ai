"""精益早会日报第四份报告的基地级开关配置。"""

from __future__ import annotations

import os


FOURTH_REPORT_ENABLED_ENV = "LEAN_MORNING_DAILY_FOURTH_REPORT_ENABLED"
THIRD_REPORT_TEMPLATE_LIMIT = 3


def is_fourth_report_enabled(value: str | None = None) -> bool:
    """读取第四份报告开关。

    Args:
        value: 用于测试或显式覆盖的配置值；未传入时读取环境变量。

    Returns:
        是否生成第四份班次/班组绩效对比报告。
    """
    configured_value = value if value is not None else os.getenv(FOURTH_REPORT_ENABLED_ENV, "false")
    return configured_value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_template_limit(template_limit: int | None, fourth_report_enabled: bool) -> int | None:
    """根据第四份报告开关计算实际模板数量限制。

    Args:
        template_limit: 调用方指定的模板数量限制；None 表示不限制。
        fourth_report_enabled: 第四份报告是否已启用。

    Returns:
        供报告生成器使用的实际模板数量限制。
    """
    if fourth_report_enabled:
        return template_limit
    if template_limit is None:
        return THIRD_REPORT_TEMPLATE_LIMIT
    return min(template_limit, THIRD_REPORT_TEMPLATE_LIMIT)
