# cython: annotation_typing=False, infer_types=False, language_level=3
"""
作业级日志管理器
为每个批量作业创建独立的日志文件，按作业类型和日期组织
"""
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from typing import Optional, Dict


class JobLogger:
    """作业日志管理器

    每个批量作业对应一个 JobLogger 实例，日志同时输出到控制台和文件
    文件名格式：{job_type}_{report_date}_w{workshop_id}_p{procedure_id}_{time}.log
    """

    def __init__(
        self,
        job_type: str,
        report_date: str = None,
        params: Dict = None,
        log_dir: str = "logs/jobs",
    ):
        """初始化作业日志器

        Args:
            job_type: 作业类型（如 leanMorningDailyReport, qualityWeekReport）
            report_date: 报告日期（YYYY-MM-DD 格式），默认使用今日
            params: 关键参数字典（如 workshop_id, procedure_id）
            log_dir: 日志根目录，默认 logs/jobs/
        """
        self.job_type = job_type
        self.report_date = report_date or datetime.now().strftime("%Y-%m-%d")
        self.params = params or {}
        self.log_dir = log_dir

        # 提取关键参数
        self.workshop_id = self.params.get("workshop_id", "0")
        self.procedure_id = self.params.get("procedure_id", "0")

        # 生成时间戳（精确到秒）
        self.timestamp = datetime.now().strftime("%H%M%S")

        # 构建日志文件路径
        self.log_file_path = self._build_log_file_path()

        # 创建日志器
        self.logger = self._setup_logger()

    def _build_log_file_path(self) -> str:
        """构建日志文件路径

        Returns:
            完整的日志文件路径
        """
        # 目录结构：logs/jobs/{job_type}/{YYYY-MM-DD}/
        date_dir = os.path.join(self.log_dir, self.job_type, self.report_date)
        os.makedirs(date_dir, exist_ok=True)

        # 文件名：{job_type}_{report_date}_w{workshop_id}_p{procedure_id}_{time}.log
        filename = (
            f"{self.job_type}_{self.report_date}"
            f"_w{self.workshop_id}_p{self.procedure_id}"
            f"_{self.timestamp}.log"
        )

        return os.path.join(date_dir, filename)

    def _setup_logger(self) -> logging.Logger:
        """设置日志器

        Returns:
            配置好的 logging.Logger 实例
        """
        # 创建唯一的日志器名称，避免冲突
        logger_name = f"job_{self.job_type}_{self.timestamp}_{id(self)}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)

        # 避免重复添加处理器
        if logger.handlers:
            return logger

        # 设置日志格式（去掉 logger name 标记）
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 控制台输出处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # 文件输出处理器（按天轮转，保留 7 天日志）
        file_handler = TimedRotatingFileHandler(
            self.log_file_path,
            when='midnight',
            interval=1,
            backupCount=7,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        return logger

    def info(self, msg: str, *args, **kwargs):
        """记录 INFO 级别日志"""
        self.logger.info(msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        """记录 DEBUG 级别日志"""
        self.logger.debug(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """记录 WARNING 级别日志"""
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """记录 ERROR 级别日志"""
        self.logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        """记录异常信息（包含堆栈）"""
        self.logger.exception(msg, *args, **kwargs)

    def get_log_file_path(self) -> str:
        """获取日志文件路径"""
        return self.log_file_path

    def print_separator(self, char: str = "=", length: int = 70):
        """打印分隔线"""
        self.info(char * length)


def cleanup_old_logs(log_dir: str = "logs/jobs", keep_days: int = 7):
    """清理超过指定天数的日志目录

    Args:
        log_dir: 日志根目录
        keep_days: 保留天数，默认 7 天
    """
    import shutil
    from pathlib import Path

    if not os.path.exists(log_dir):
        return

    cutoff = datetime.now().timestamp() - (keep_days * 86400)
    cleaned = 0

    for job_type_dir in Path(log_dir).iterdir():
        if not job_type_dir.is_dir():
            continue
        for date_dir in job_type_dir.iterdir():
            if not date_dir.is_dir():
                continue
            # 目录名是日期格式 YYYY-MM-DD
            try:
                dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                if dir_date.timestamp() < cutoff:
                    shutil.rmtree(date_dir)
                    cleaned += 1
            except ValueError:
                continue

    if cleaned > 0:
        print(f"[日志清理] 已删除 {cleaned} 个超过 {keep_days} 天的日志目录")


# 单例日志器（用于无需独立日志文件的场景）
_default_logger = None


def get_default_logger() -> logging.Logger:
    """获取默认的全局日志器

    Returns:
        配置好的默认日志器
    """
    global _default_logger
    if _default_logger is None:
        _default_logger = logging.getLogger("report_agent")
        _default_logger.setLevel(logging.INFO)

        if not _default_logger.handlers:
            formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            _default_logger.addHandler(console_handler)

    return _default_logger
