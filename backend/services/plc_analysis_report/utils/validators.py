# cython: annotation_typing=False, infer_types=False, language_level=3
"""校验模块 - 内容完整性校验、一致性校验"""
import re
from typing import List

from backend.services.plc_analysis_report.utils.logger import get_logger

logger = get_logger("plc.validators")


def validate_page_completeness(total_valid_pages: int, parsed_pages: int) -> List[str]:
    """校验页面完整性。

    Args:
        total_valid_pages: PDF 预处理后的有效页面数。
        parsed_pages: 实际解析的页面数。

    Returns:
        警告信息列表，空列表表示校验通过。
    """
    warnings = []
    if parsed_pages != total_valid_pages:
        warning = f"页面数量不一致：预期 {total_valid_pages} 页，实际解析 {parsed_pages} 页，可能存在漏页"
        logger.warning(warning)
        warnings.append(warning)
    return warnings


def validate_consistency(macro_text: str, micro_text: str) -> List[str]:
    """校验宏观与微观内容的一致性。

    Args:
        macro_text: 宏观解析文本。
        micro_text: 微观解析文本。

    Returns:
        警告信息列表，空列表表示校验通过。
    """
    warnings = []
    micro_pages = set(re.findall(r"第\s*(\d+)\s*页", micro_text))
    macro_pages = set(re.findall(r"第\s*(\d+)\s*页", macro_text))
    missing_pages = macro_pages - micro_pages
    if missing_pages:
        warning = f"宏观内容中提到的页码在微观中未找到：{', '.join(sorted(missing_pages))}"
        logger.warning(warning)
        warnings.append(warning)
    return warnings
