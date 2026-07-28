# cython: annotation_typing=False, infer_types=False, language_level=3
"""PLC 解析服务日志模块

采用与 Agentic QA 一致的日志架构：
- 日志目录：logs/plc-analysis/
- 三级输出：控制台(INFO) + 常规日志文件(DEBUG, 按天轮转30天) + 错误日志文件(ERROR)
- 格式：%(asctime)s | %(levelname)-5s | %(name)s | %(message)s
- propagate = False 隔离于全局根 logger
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[4]
LOG_DIR = PROJECT_ROOT / "logs" / "plc-analysis"

# 日志格式
LOG_FORMAT = "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 缓存已创建的 logger
_loggers: dict[str, logging.Logger] = {}


def _setup_log_dir() -> None:
    """确保日志目录存在"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Windows兼容的TimedRotatingFileHandler，处理文件占用问题"""

    def doRollover(self):
        """执行日志轮转，处理Windows文件占用问题"""
        try:
            super().doRollover()
        except PermissionError:
            # Windows上文件被占用时，跳过轮转，继续写入当前文件
            pass
        except OSError:
            # 其他文件系统错误
            pass


def get_logger(name: str = "plc_analysis") -> logging.Logger:
    """获取或创建 PLC 解析服务 logger。

    Args:
        name: logger 名称，推荐使用层次化点分名称，如：
              - plc.pdf_processor
              - plc.micro_parser
              - plc.macro_parser
              - plc.report_generator

    Returns:
        配置好的 logger 实例。
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # 隔离于全局根 logger

    # 避免重复添加 handler
    if logger.handlers:
        _loggers[name] = logger
        return logger

    _setup_log_dir()

    # 日志格式
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # 1. 控制台输出 - INFO 及以上
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 2. 常规日志文件 - DEBUG 及以上，按天轮转，保留 30 天
    log_file = LOG_DIR / "plc_analysis.log"
    file_handler = SafeTimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y%m%d"
    logger.addHandler(file_handler)

    # 3. 错误日志文件 - ERROR 及以上，按天轮转，保留 30 天
    error_log_file = LOG_DIR / "error.log"
    error_handler = SafeTimedRotatingFileHandler(
        error_log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    error_handler.suffix = "%Y%m%d"
    logger.addHandler(error_handler)

    _loggers[name] = logger
    return logger
