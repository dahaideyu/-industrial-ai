# cython: annotation_typing=False, infer_types=False, language_level=3
"""图像处理工具 - 图片增强、空白页检测"""
from io import BytesIO

from PIL import Image, ImageEnhance

from backend.services.plc_analysis_report.utils.logger import get_logger

logger = get_logger("plc.image_processor")


def enhance_image(image_bytes: bytes, contrast: float = 1.5, sharpness: float = 1.2) -> bytes:
    """增强图片对比度和清晰度。

    Args:
        image_bytes: 原始图片字节。
        contrast: 对比度增强倍数，默认 1.5。
        sharpness: 锐度增强倍数，默认 1.2。

    Returns:
        增强后的 PNG 图片字节。
    """
    image = Image.open(BytesIO(image_bytes))

    # 增强对比度
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(contrast)

    # 增强锐度
    enhancer = ImageEnhance.Sharpness(image)
    image = enhancer.enhance(sharpness)

    # 转为 RGB 模式
    if image.mode != "RGB":
        image = image.convert("RGB")

    # 输出为 PNG
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def is_blank_page(image_bytes: bytes, threshold: float = 0.95) -> bool:
    """检测是否为空白页（已禁用）。

    Args:
        image_bytes: 图片字节。
        threshold: 空白阈值（当前未使用）。

    Returns:
        始终返回 False，空白页检测已禁用。
    """
    logger.debug("空白页检测已禁用，所有页面都将被处理")
    return False
