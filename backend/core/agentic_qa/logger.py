# cython: annotation_typing=False, infer_types=False, language_level=3
"""统一日志系统 — 按天轮转，输出到 /logs 目录"""
import logging
import logging.handlers
import os
import sys
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "logs", "agentic-qa")
os.makedirs(LOG_DIR, exist_ok=True)

_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    """获取或创建指定名称的 logger，自动配置每日轮转文件 + 控制台输出"""
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        # 格式
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # 控制台 handler (INFO 以上)
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(fmt)
        logger.addHandler(console)

        # 每日文件 handler (DEBUG 以上)
        today = datetime.now().strftime("%Y-%m-%d")
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=os.path.join(LOG_DIR, f"{today}.log"),
            when="midnight",
            interval=1,
            backupCount=30,  # 保留 30 天
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        # 自定义 namer: 将轮转后的文件重命名为日期格式
        file_handler.namer = lambda name: name.replace(".log.", "-") + ".log"
        file_handler.suffix = "%Y-%m-%d"
        logger.addHandler(file_handler)

        # 错误日志单独文件
        error_handler = logging.handlers.TimedRotatingFileHandler(
            filename=os.path.join(LOG_DIR, f"error-{today}.log"),
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8"
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(fmt)
        logger.addHandler(error_handler)

    _loggers[name] = logger
    return logger


def setup_root_logger():
    """配置根 logger"""
    root = get_logger("app")
    root.info("=" * 50)
    root.info("日志系统初始化完成")
    root.info(f"日志目录: {LOG_DIR}")
    root.info("=" * 50)
    return root
