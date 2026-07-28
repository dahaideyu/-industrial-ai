# cython: annotation_typing=False, infer_types=False, language_level=3
"""PLC 解析服务主流程入口

提供 PLCAnalysisService 类，供 Celery 任务或其他模块调用。
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.services.plc_analysis_report.config import settings
from backend.services.plc_analysis_report.pdf_processor import process_pdf, PDFProcessingResult
from backend.services.plc_analysis_report.micro_parser import parse_all_pages
from backend.services.plc_analysis_report.macro_parser import parse_macro
from backend.services.plc_analysis_report.report_generator import generate_report
from backend.services.plc_analysis_report.utils.validators import validate_page_completeness, validate_consistency
from backend.services.plc_analysis_report.utils.logger import get_logger

logger = get_logger("plc.main")


class PLCAnalysisService:
    """PLC 图纸解析服务。

    流程：PDF 预处理 -> 微观逐页解析 -> 宏观全局梳理 -> 报告生成

    使用示例：
        service = PLCAnalysisService()
        report_path = service.analyze("/path/to/plc_drawing.pdf")
    """

    def __init__(self):
        self._progress_callback = None

    def set_progress_callback(self, callback):
        """设置进度回调函数。

        Args:
            callback: 回调函数，签名为 callback(current, total)。
        """
        self._progress_callback = callback

    def analyze(
        self,
        pdf_path: str,
        output_dir: Optional[str] = None,
        save_to_file: bool = False,
    ) -> str:
        """解析 PLC 图纸 PDF 并生成报告。

        Args:
            pdf_path: PDF 文件路径。
            output_dir: 报告输出目录，None 时使用当前工作目录下的 reports/（仅 save_to_file=True 时有效）。
            save_to_file: 是否保存到本地文件，默认 False 只返回内容。

        Returns:
            如果 save_to_file=True，返回文件路径；否则返回报告内容。

        Raises:
            ValueError: PDF 文件不存在、格式错误或加密时抛出。
            RuntimeError: 解析过程中发生未知错误时抛出。
        """
        # 参数校验
        pdf_path_obj = Path(pdf_path)
        if not pdf_path_obj.exists():
            raise ValueError(f"文件不存在：{pdf_path}")

        if not pdf_path.lower().endswith(".pdf"):
            raise ValueError("输入文件不是 PDF 格式")

        try:
            # 步骤 1：PDF 预处理
            logger.info("=" * 60)
            logger.info("步骤 1/4：PDF 预处理与 base64 编码转换")
            logger.info("=" * 60)
            process_result = process_pdf(pdf_path)
            logger.info("有效页面数量：%d", process_result.valid_pages)

            if process_result.valid_pages == 0:
                raise ValueError("未检测到有效页面，无法继续解析")

            # 步骤 2：微观解析
            logger.info("=" * 60)
            logger.info("步骤 2/4：逐页微观解析（%s）", settings.vision_model)
            logger.info("=" * 60)
            micro_summary = parse_all_pages(process_result.pages, self._progress_callback)

            # 步骤 3：宏观解析
            logger.info("=" * 60)
            logger.info("步骤 3/4：宏观系统架构梳理（%s）", settings.text_model)
            logger.info("=" * 60)
            macro_summary = parse_macro(micro_summary)

            # 步骤 4：生成报告
            logger.info("=" * 60)
            logger.info("步骤 4/4：生成标准化 Markdown 报告")
            logger.info("=" * 60)
            report_result = generate_report(
                pdf_path=pdf_path,
                process_result=process_result,
                micro_summary=micro_summary,
                macro_summary=macro_summary,
                output_dir=output_dir,
                save_to_file=save_to_file,
            )

            # 校验
            logger.info("执行内容校验...")
            parsed_page_count = micro_summary.count("## 第")
            page_warnings = validate_page_completeness(process_result.valid_pages, parsed_page_count)
            consistency_warnings = validate_consistency(macro_summary, micro_summary)

            if page_warnings:
                for w in page_warnings:
                    logger.warning("页面校验：%s", w)
            if consistency_warnings:
                for w in consistency_warnings:
                    logger.warning("一致性校验：%s", w)

            logger.info("=" * 60)
            if save_to_file:
                logger.info("解析完成！报告已保存至：%s", report_result)
            else:
                logger.info("解析完成！报告内容长度：%d 字符", len(report_result))
            logger.info("=" * 60)

            return report_result

        except ValueError:
            raise
        except Exception as e:
            logger.error("解析过程中发生错误：%s", e)
            raise RuntimeError(f"PLC 解析失败：{e}") from e


# 模块级单例
plc_service = PLCAnalysisService()
