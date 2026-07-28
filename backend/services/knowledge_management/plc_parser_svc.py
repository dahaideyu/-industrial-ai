# cython: annotation_typing=False, infer_types=False, language_level=3
"""图纸解析服务

解析 PLC 梯形图、电气原理图、流程图等 PDF 图纸文件（不是源码解析），
使用 plc_analysis_report 模块进行完整的四步解析流程：
PDF 预处理 -> 微观逐页解析 -> 宏观全局梳理 -> 报告生成

注意：仅支持 PDF 格式的图纸，不支持 .awl/.scl/.stl 等源码文件。
"""
import logging

from backend.services.plc_analysis_report import plc_service

logger = logging.getLogger(__name__)


class DrawingParserService:
    """图纸 PDF 解析：基于 plc_analysis_report 模块的完整解析流程。"""

    def parse_drawing_file(self, file_path: str, progress_callback=None) -> str:
        """解析图纸 PDF 文件，生成 Markdown 格式的分析报告。

        处理流程（委托给 plc_analysis_report 模块）：
        1. PDF 预处理：分页、转高清图片、base64 编码
        2. 微观解析：调用 qwen-vl-plus 视觉模型逐页解析梯形图、功能块、电路图
        3. 宏观解析：调用 qwen3.6-plus 文本模型进行全局架构梳理
        4. 报告生成：整合微观/宏观解析结果，生成标准化 Markdown 报告

        支持的图纸类型：
        - PLC 梯形图/功能块图
        - 电气原理图
        - 流程图/控制逻辑图
        - 设备布局图

        Args:
            file_path: 图纸 PDF 文件路径。
            progress_callback: 可选的进度回调函数，签名为 callback(current, total)。

        Returns:
            Markdown 格式的分析报告内容。

        Raises:
            ValueError: PDF 文件不存在、格式错误或加密时抛出。
            RuntimeError: 解析过程中发生未知错误时抛出。
        """
        logger.info("开始解析图纸 PDF: %s", file_path)

        # 设置进度回调到 plc_service
        plc_service.set_progress_callback(progress_callback)

        # 调用 plc_analysis_report 服务生成报告（不保存本地文件）
        report_content = plc_service.analyze(pdf_path=file_path, save_to_file=False)

        logger.info("图纸解析完成，报告内容长度: %d 字符", len(report_content))
        return report_content


# 模块级单例（保持向后兼容）
plc_parser_svc = DrawingParserService()
