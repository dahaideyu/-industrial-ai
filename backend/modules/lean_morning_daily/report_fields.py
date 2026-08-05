"""精益早会日报报告字段映射。"""

from __future__ import annotations

import json
from typing import Any


EVENING_SKIP_MESSAGE = "傍晚版仅生成基础日报（此报告无需生成）"


def map_reports_to_fields(
    reports: list[dict[str, Any]],
    template_limit: int | None = None,
) -> dict[str, str]:
    """将四份精益早会日报映射到内部字段。

    第四份报告映射到本地数据库及上游回调共用的字段。

    Args:
        reports: 按模板顺序生成的报告列表。
        template_limit: 模板数量限制；傍晚版通常为1。

    Returns:
        报告内容及第三份报告引用字段。
    """

    def get_content(index: int, fallback_message: str) -> str:
        """安全读取指定报告内容。"""
        if index < len(reports):
            return str(reports[index].get("content", fallback_message))
        return fallback_message

    def get_citations_json(index: int) -> str:
        """安全序列化指定报告引用。"""
        if index >= len(reports):
            return ""
        citations = reports[index].get("citations", [])
        return json.dumps(citations, ensure_ascii=False) if citations else ""

    if template_limit is not None and template_limit <= 1:
        return {
            "markdownContent": get_content(0, "日会早报生成失败"),
            "summaryMarkdown": get_content(1, EVENING_SKIP_MESSAGE),
            "kbReportMarkdown": get_content(2, EVENING_SKIP_MESSAGE),
            "teamCompareMarkdown": get_content(3, EVENING_SKIP_MESSAGE),
            "knowledgeBasePayload": get_citations_json(2),
        }

    return {
        "markdownContent": get_content(0, "日会早报生成失败"),
        "summaryMarkdown": get_content(1, "日会早报趋势分析生成失败"),
        "kbReportMarkdown": get_content(2, "日会早报改善建议生成失败"),
        "teamCompareMarkdown": get_content(3, "班次/班组绩效对比报告生成失败"),
        "knowledgeBasePayload": get_citations_json(2),
    }
