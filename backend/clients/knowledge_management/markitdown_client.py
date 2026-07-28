# cython: annotation_typing=False, infer_types=False, language_level=3
"""Microsoft MarkItDown 客户端：文档 → Markdown 转换，含 OCR 流水线"""
import logging
from pathlib import Path

from backend.core.knowledge_management.exceptions import TaskError

logger = logging.getLogger(__name__)


class MarkItDownClient:
    """文档转 Markdown + OCR 流水线。

    提取流水线：
    1. MarkItDown 提取 → Markdown（保留结构：标题/列表/表格）
    2. 如果结果 < 500 字符 → 可能是扫描件 → 触发 RapidOCR
    3. RapidOCR: 直接处理 PDF / 图片，无需外部依赖（无需 tesseract/poppler）
    """

    _OCR_MIN_CHARS = 500    # 低于此字符数触发自动 OCR
    _GARBLED_RATIO = 0.25   # 乱码字符占比超过此值触发 OCR

    def __init__(self):
        # RapidOCR 单例（延迟加载，首次使用时初始化）
        self._rapid_ocr = None

    def _get_rapid_ocr(self):
        """获取 RapidOCR 实例（单例 + 懒加载）。"""
        if self._rapid_ocr is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                self._rapid_ocr = RapidOCR()
                logger.info("RapidOCR 初始化成功")
            except ImportError as e:
                logger.warning("RapidOCR 未安装: %s", e)
                return None
            except Exception as e:
                logger.warning("RapidOCR 初始化失败: %s", e)
                return None
        return self._rapid_ocr

    def convert(self, file_path: str) -> str:
        """将文档转换为 Markdown 文本。"""
        try:
            from markitdown import MarkItDown
            md = MarkItDown()
            result = md.convert(file_path)
            text = result.text_content.strip()
            logger.info("MarkItDown 提取完成: %s, len=%d", Path(file_path).name, len(text))
            return text
        except Exception as e:
            logger.warning("MarkItDown 提取失败: %s", e)
            raise TaskError(f"MarkItDown 转换失败: {e}")

    def convert_with_ocr(self, file_path: str, force_ocr: bool = False) -> str:
        """提取文档内容，低文本量或乱码时自动触发 OCR。

        自动触发条件（任一满足）：
        1. force_ocr=True（手动开启）
        2. 文本 < OCR_MIN_CHARS（500字）
        3. 乱码字符占比 > GARBLED_RATIO（25%）
        """
        markdown_text = ""
        try:
            markdown_text = self.convert(file_path)
        except TaskError:
            logger.warning("MarkItDown 失败，尝试 OCR")
            force_ocr = True

        # 判断是否需要 OCR
        need_ocr = force_ocr
        if not need_ocr and len(markdown_text) < self._OCR_MIN_CHARS:
            logger.info("文本量不足 (%d < %d)，自动触发 OCR",
                         len(markdown_text), self._OCR_MIN_CHARS)
            need_ocr = True
        if not need_ocr and self._is_garbled(markdown_text):
            logger.info("检测到乱码文本，自动触发 OCR")
            need_ocr = True

        if not need_ocr:
            return markdown_text

        ocr_text = self._ocr_with_rapid(file_path)
        if ocr_text:
            if markdown_text and not force_ocr:
                return markdown_text + "\n\n--- OCR 识别内容 ---\n\n" + ocr_text
            return ocr_text

        # OCR 失败时返回原 MarkItDown 结果（如果有）
        return markdown_text

    @staticmethod
    def _is_garbled(text: str) -> bool:
        """检测文本是否有大量乱码/不可读字符。"""
        if not text:
            return False
        garbled = 0
        for ch in text[:2000]:  # 采样前2000字
            code = ord(ch)
            # 排除：控制字符、私有区、替换字符
            if code < 32 and code not in (9, 10, 13):
                garbled += 1
            elif 0xFFF0 <= code <= 0xFFFF:
                garbled += 1
            elif 0xE000 <= code <= 0xF8FF:
                garbled += 1
        ratio = garbled / min(len(text), 2000)
        return ratio > MarkItDownClient._GARBLED_RATIO

    def _ocr_with_rapid(self, file_path: str) -> str:
        """使用 RapidOCR 识别 PDF/图片中的文字。

        RapidOCR 内部用 PyMuPDF 渲染 PDF 页 + ONNX 推理文字识别，
        无需外部 poppler/tesseract 依赖。

        Args:
            file_path: PDF 或图片文件路径。

        Returns:
            识别出的文字内容。失败时返回空字符串。
        """
        rapid = self._get_rapid_ocr()
        if rapid is None:
            return ""

        ext = Path(file_path).suffix.lower()

        try:
            if ext == ".pdf":
                return self._ocr_pdf_pages(file_path, rapid)
            else:
                # 图片直接 OCR
                return self._ocr_single(file_path, rapid)
        except Exception as e:
            logger.warning("RapidOCR 处理失败: %s", e)
            return ""

    def _ocr_pdf_pages(self, pdf_path: str, rapid) -> str:
        """PDF 逐页 OCR（用 PyMuPDF 拆页，RapidOCR 识别）。"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.warning("PyMuPDF 未安装，无法 PDF OCR")
            return ""

        texts = []
        try:
            doc_pdf = fitz.open(pdf_path)
            for i, page in enumerate(doc_pdf, 1):
                mat = fitz.Matrix(150 / 72, 150 / 72)
                pix = page.get_pixmap(matrix=mat)
                # RapidOCR 接受 numpy array 或文件路径
                import numpy as np
                img_array = np.frombuffer(pix.tobytes("png"), dtype=np.uint8)
                import cv2
                img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if img is None:
                    continue
                result, _ = rapid(img)
                if result:
                    page_text = "\n".join([line[1] for line in result if line and len(line) > 1])
                    if page_text.strip():
                        texts.append(f"--- 第{i}页 (OCR) ---\n{page_text.strip()}")
            doc_pdf.close()
        except Exception as e:
            logger.warning("PDF OCR 失败: %s", e)
            return ""

        logger.info("RapidOCR PDF 完成: %d 页", len(texts))
        return "\n\n".join(texts)

    def _ocr_single(self, file_path: str, rapid) -> str:
        """单张图片 OCR。"""
        try:
            import cv2
            img = cv2.imread(str(file_path))
            if img is None:
                logger.warning("图片读取失败: %s", file_path)
                return ""
            result, _ = rapid(img)
            if not result:
                return ""
            return "\n".join([line[1] for line in result if line and len(line) > 1])
        except Exception as e:
            logger.warning("图片 OCR 失败: %s", e)
            return ""


# 模块级单例
markitdown_client = MarkItDownClient()
