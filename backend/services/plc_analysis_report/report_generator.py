# cython: annotation_typing=False, infer_types=False, language_level=3
"""报告生成模块 - 整合微观和宏观解析结果，生成标准化 Markdown 报告"""
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.services.plc_analysis_report.pdf_processor import PDFProcessingResult
from backend.services.plc_analysis_report.utils.logger import get_logger

logger = get_logger("plc.report_generator")


def extract_equipment_name(pdf_path: str) -> str:
    """从 PDF 路径中提取设备/图纸名称。

    Args:
        pdf_path: PDF 文件路径。

    Returns:
        设备名称，去除 _PLC 后缀。
    """
    filename = Path(pdf_path).stem
    filename = re.sub(r'_PLC.*$', '', filename)
    return filename or "未知设备"


def generate_report(
    pdf_path: str,
    process_result: PDFProcessingResult,
    micro_summary: str,
    macro_summary: str,
    output_dir: Optional[str] = None,
    save_to_file: bool = False,
) -> str:
    """生成解析报告。

    Args:
        pdf_path: 原始 PDF 文件路径。
        process_result: PDF 预处理结果。
        micro_summary: 微观解析汇总文本。
        macro_summary: 宏观解析汇总文本。
        output_dir: 输出目录，None 时使用当前目录下的 reports/（仅 save_to_file=True 时有效）。
        save_to_file: 是否保存到本地文件，默认 False 只返回内容。

    Returns:
        如果 save_to_file=True，返回文件路径；否则返回报告内容。
    """
    logger.info("开始生成报告...")

    equipment_name = extract_equipment_name(pdf_path)
    date_str = datetime.now().strftime("%Y%m%d")

    filtered_info_text = ""
    if process_result.filtered_info:
        filtered_info_text = "\n".join(f"- {info}" for info in process_result.filtered_info)

    report_content = """# 《{} PLC程序/电气原理图 智能解析报告》

> 解析时间：{}

---

## 一、图纸基础信息

| 项目 | 内容 |
|------|------|
| 图纸名称 | {} |
| 总有效页数 | {} / {} |
| 解析范围 | 全量解析 |
| 解析时间 | {} |

{}

---

## 二、宏观系统架构总览

{}

---

## 三、逐模块/逐页微观详细解析

{}

---

## 四、跨模块信号与关联关系说明

> 基于微观解析结果，以下为跨页、跨模块的信号与关联关系汇总：

{}

---

## 五、系统设计分析与运维建议

> 基于全量解析信息，以下为系统保护逻辑分析、故障排查流程与运维建议：

{}

---

## 六、解析总结

本报告对《{}》的 PLC 程序/电气原理图进行了全量智能解析，覆盖：

- **系统架构**：{} 个核心功能模块
- **微观解析**：{} 页详细解析
- **跨页关联**：{} 处跨页信号关联

报告内容可直接用于设备调试、运维、故障排查与技术归档。
""".format(equipment_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), equipment_name, process_result.valid_pages, process_result.total_pages, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), filtered_info_text, macro_summary, micro_summary, extract_cross_references(micro_summary), extract_maintenance_suggestions(macro_summary), equipment_name, count_sections(macro_summary), process_result.valid_pages, count_cross_references(micro_summary))

    if save_to_file:
        if output_dir is None:
            output_dir = os.path.join(os.getcwd(), "reports")
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{equipment_name}_PLC图纸解析报告_{date_str}.md"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report_content)
        logger.info("报告已保存至：%s", filepath)
        return filepath

    logger.info("报告生成完成（内容长度: %d 字符）", len(report_content))
    return report_content


def extract_cross_references(micro_summary: str) -> str:
    """提取跨模块信号与关联关系。

    Args:
        micro_summary: 微观解析文本。

    Returns:
        跨页关联信息文本。
    """
    lines = micro_summary.split("\n")
    cross_refs = [line for line in lines if any(kw in line for kw in ["跨页", "跳转", "关联", "接口"])]
    if cross_refs:
        return "\n".join(cross_refs[:20])
    return "未检测到明显的跨页信号关联信息，请结合宏观架构总览进行综合分析。"


def extract_maintenance_suggestions(macro_summary: str) -> str:
    """提取运维建议。

    Args:
        macro_summary: 宏观解析文本。

    Returns:
        运维建议文本。
    """
    lines = macro_summary.split("\n")
    suggestions = [line for line in lines if any(kw in line for kw in ["运维", "故障", "检修", "排查", "注意"])]
    if suggestions:
        return "\n".join(suggestions[:20])
    return "未检测到明显的运维建议信息，请参考宏观架构总览中的系统设计特点部分。"


def count_sections(text: str) -> int:
    """粗略统计功能模块数量。

    Args:
        text: 宏观解析文本。

    Returns:
        模块数量（至少为 1）。
    """
    return max(1, text.count("## 【"))


def count_cross_references(text: str) -> int:
    """粗略统计跨页关联数量。

    Args:
        text: 微观解析文本。

    Returns:
        跨页关联数量。
    """
    return max(0, text.count("跨页") + text.count("跳转"))
