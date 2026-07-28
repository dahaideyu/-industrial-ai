# cython: annotation_typing=False, infer_types=False, language_level=3
"""微观解析模块 - 调用 Qwen3-VL-Plus 逐页解析"""
from typing import List

from openai import OpenAI
from openai._exceptions import APIError, APITimeoutError, APIConnectionError

from backend.services.plc_analysis_report.config import settings
from backend.services.plc_analysis_report.pdf_processor import PageMetadata
from backend.services.plc_analysis_report.utils.prompts import MICRO_PARSE_PROMPT
from backend.services.plc_analysis_report.utils.logger import get_logger

logger = get_logger("plc.micro_parser")


def parse_single_page(page: PageMetadata, client: OpenAI) -> str:
    """解析单页图纸。

    Args:
        page: 页面元数据，包含 base64 图片。
        client: OpenAI 客户端实例。

    Returns:
        解析结果文本。

    Raises:
        APIError: API 调用失败且重试耗尽时抛出。
    """
    page_num = page.original_page_number
    logger.info("开始解析第 %d 页...", page_num)

    content = [
        {"type": "text", "text": MICRO_PARSE_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{page.base64_image}"}},
    ]

    for attempt in range(settings.max_retries):
        try:
            response = client.chat.completions.create(
                model=settings.vision_model,
                messages=[{"role": "user", "content": content}],
                timeout=settings.vision_timeout,
            )
            result = response.choices[0].message.content
            logger.info("第 %d 页解析完成", page_num)
            return result
        except (APITimeoutError, APIConnectionError) as e:
            logger.warning("第 %d 页解析失败（尝试 %d/%d）: %s", page_num, attempt + 1, settings.max_retries, e)
            if attempt == settings.max_retries - 1:
                raise
        except APIError as e:
            logger.error("第 %d 页 API 错误: %s", page_num, e)
            raise

    raise APIError("解析失败：重试次数已用尽")


def parse_all_pages(pages: List[PageMetadata], progress_callback=None) -> str:
    """解析所有页面并汇总。

    Args:
        pages: 页面元数据列表。
        progress_callback: 可选的进度回调函数，签名为 callback(current, total)。

    Returns:
        按页码顺序拼接的全量微观解析文本，页间用 --- 分隔。
    """
    logger.info("开始批量解析 %d 个页面...", len(pages))

    client = OpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        max_retries=0,
    )

    results = []
    total_pages = len(pages)
    for i, page in enumerate(pages):
        page_result = parse_single_page(page, client)
        results.append(f"## 第 {page.original_page_number} 页解析\n\n{page_result}")

        # 调用进度回调
        if progress_callback:
            progress_callback(i + 1, total_pages)

    summary = "\n\n---\n\n".join(results)
    logger.info("批量解析完成，共 %d 页", len(results))
    return summary
