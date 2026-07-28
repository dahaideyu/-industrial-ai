# cython: annotation_typing=False, infer_types=False, language_level=3
"""宏观解析模块 - 调用 Qwen3.6 进行全局架构梳理"""
from openai import OpenAI
from openai._exceptions import APIError, APITimeoutError, APIConnectionError

from backend.services.plc_analysis_report.config import settings
from backend.services.plc_analysis_report.utils.prompts import MACRO_PARSE_PROMPT
from backend.services.plc_analysis_report.utils.logger import get_logger

logger = get_logger("plc.macro_parser")


def parse_macro(micro_summary: str) -> str:
    """执行宏观架构梳理。

    Args:
        micro_summary: 微观解析全量汇总文本。

    Returns:
        宏观系统架构梳理文本。

    Raises:
        APIError: API 调用失败且重试耗尽时抛出。
    """
    logger.info("开始宏观架构梳理...")

    client = OpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        max_retries=0,
    )

    full_prompt = """基于以下逐页微观解析结果，请进行宏观系统架构梳理。

【微观解析结果】
{}

【宏观梳理要求】
{}
""".format(micro_summary, MACRO_PARSE_PROMPT)

    for attempt in range(settings.max_retries):
        try:
            response = client.chat.completions.create(
                model=settings.text_model,
                messages=[{"role": "user", "content": full_prompt}],
                timeout=settings.text_timeout,
            )
            result = response.choices[0].message.content
            logger.info("宏观架构梳理完成")
            return result
        except (APITimeoutError, APIConnectionError) as e:
            logger.warning("宏观解析失败（尝试 %d/%d）: %s", attempt + 1, settings.max_retries, e)
            if attempt == settings.max_retries - 1:
                raise
        except APIError as e:
            logger.error("宏观解析 API 错误: %s", e)
            raise

    raise APIError("宏观解析失败：重试次数已用尽")
