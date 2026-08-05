# cython: annotation_typing=False, infer_types=False, language_level=3
"""集中式日志配置。

用法：
    # 在应用入口（app.py）调用一次即可
    from core.logging_config import setup_logging
    setup_logging()

    # 在各模块中直接用标准库
    import logging
    logger = logging.getLogger(__name__)

设计要点：
  - 统一格式：时间 + 模块名 + 级别 + 消息，便于 grep 和日志聚合
  - 级别由 LOG_LEVEL 环境变量控制（默认 INFO）
  - 可选 JSON 结构化输出（LOG_FORMAT=json），适配 ELK/Loki 等日志平台
  - 噪音库降级：urllib3/connectionpool 等第三方库默认 WARNING
"""
import os
import json
import logging
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """JSON 行格式，每条日志一个 JSON 对象，方便日志平台解析。"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        if record.__dict__.get("extra_fields"):
            log_entry.update(record.__dict__["extra_fields"])
        return json.dumps(log_entry, ensure_ascii=False)


_NOISY_LOGGERS = [
    "urllib3",
    "urllib3.connectionpool",
    "requests",
    "requests.packages.urllib3",
    "httpx",
    "httpcore",
    "openai",
    "chromadb",
    "sentence_transformers",
    "apscheduler",
    "psycopg2",
]


def setup_logging() -> None:
    """初始化全局日志配置。应在应用启动时调用一次。"""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = os.getenv("LOG_FORMAT", "text").lower()

    if log_format == "json":
        formatter: logging.Formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # 噪音第三方库统一降到 WARNING，避免淹没业务日志
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
