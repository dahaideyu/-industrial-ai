# cython: annotation_typing=False, infer_types=False, language_level=3
"""PDF 预处理模块 - 分页、转高清图片、base64 编码"""
import base64
from dataclasses import dataclass, field
from typing import List, Optional

import pymupdf

from backend.services.plc_analysis_report.config import settings
from backend.services.plc_analysis_report.utils.image_processor import enhance_image, is_blank_page
from backend.services.plc_analysis_report.utils.logger import get_logger

logger = get_logger("plc.pdf_processor")


@dataclass
class PageMetadata:
    """页面元数据"""
    original_page_number: int
    base64_image: str
    width: int
    height: int
    is_filtered: bool = False
    filter_reason: Optional[str] = None


@dataclass
class PDFProcessingResult:
    """PDF 处理结果"""
    total_pages: int
    valid_pages: int
    pages: List[PageMetadata] = field(default_factory=list)
    filtered_info: List[str] = field(default_factory=list)


def process_pdf(pdf_path: str) -> PDFProcessingResult:
    """处理 PDF 文件。

    Args:
        pdf_path: PDF 文件路径。

    Returns:
        PDFProcessingResult 包含总页数、有效页数、页面元数据列表。

    Raises:
        ValueError: PDF 文件加密或损坏时抛出。
    """
    logger.info("开始处理 PDF: %s", pdf_path)

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:
        if "encrypted" in str(e).lower():
            raise ValueError(f"PDF 文件已加密，无法解析: {pdf_path}") from e
        raise ValueError(f"PDF 文件损坏或无法读取: {pdf_path}") from e

    if doc.is_encrypted:
        doc.authenticate("")
        if doc.is_encrypted:
            raise ValueError(f"PDF 文件已加密，无法解析: {pdf_path}")

    total_pages = len(doc)
    logger.info("PDF 总页数: %d", total_pages)

    result = PDFProcessingResult(total_pages=total_pages, valid_pages=0)
    matrix = pymupdf.Matrix(settings.pdf_dpi / 72, settings.pdf_dpi / 72)

    for page_idx in range(total_pages):
        page_num = page_idx + 1
        logger.info("处理第 %d/%d 页...", page_num, total_pages)

        page = doc[page_idx]
        pix = page.get_pixmap(matrix=matrix)
        png_bytes = pix.tobytes("png")
        enhanced_bytes = enhance_image(png_bytes)

        if is_blank_page(enhanced_bytes):
            logger.info("第 %d 页为空白页，已过滤", page_num)
            result.filtered_info.append(f"第 {page_num} 页：空白页，已过滤")
            continue

        b64_image = base64.b64encode(enhanced_bytes).decode("utf-8")
        metadata = PageMetadata(
            original_page_number=page_num,
            base64_image=b64_image,
            width=pix.width,
            height=pix.height,
        )
        result.pages.append(metadata)
        result.valid_pages += 1

    doc.close()
    logger.info("PDF 处理完成：总页数 %d，有效页数 %d", total_pages, result.valid_pages)
    return result
