# cython: annotation_typing=False, infer_types=False, language_level=3
"""
单例工厂模块
管理各个客户端和服务的单例实例
"""
import threading

from clients.upstream_client import UpstreamClient
from clients.ragflow_client import get_ragflow_client
from services.report_generator import get_report_generator


# 全局单例实例
_upstream_client = None
_ragflow_client = None
_report_generator = None

# Celery worker 用 --pool=threads，FastAPI 同步路由也会被丢进线程池并发调用这些
# getter；无锁的话首次调用有概率并发触发多次构造，多开出用不上的连接池。双重检查锁：
# 已初始化后不再进锁，不影响热路径性能。
_lock = threading.Lock()


def get_upstream_client() -> UpstreamClient:
    """获取上游客户端单例"""
    global _upstream_client
    if _upstream_client is None:
        with _lock:
            if _upstream_client is None:
                _upstream_client = UpstreamClient()
    return _upstream_client


def get_ragflow_client_singleton():
    """获取 RAGFlow 客户端单例"""
    global _ragflow_client
    if _ragflow_client is None:
        with _lock:
            if _ragflow_client is None:
                _ragflow_client = get_ragflow_client()
    return _ragflow_client


def get_report_generator_singleton():
    """获取报告生成器单例"""
    global _report_generator
    if _report_generator is None:
        with _lock:
            if _report_generator is None:
                _report_generator = get_report_generator()
    return _report_generator