# cython: annotation_typing=False, infer_types=False, language_level=3
"""
单例工厂模块
管理各个客户端和服务的单例实例
"""
from clients.upstream_client import UpstreamClient
from clients.ragflow_client import get_ragflow_client
from services.report_generator import get_report_generator


# 全局单例实例
_upstream_client = None
_ragflow_client = None
_report_generator = None


def get_upstream_client() -> UpstreamClient:
    """获取上游客户端单例"""
    global _upstream_client
    if _upstream_client is None:
        _upstream_client = UpstreamClient()
    return _upstream_client


def get_ragflow_client_singleton():
    """获取 RAGFlow 客户端单例"""
    global _ragflow_client
    if _ragflow_client is None:
        _ragflow_client = get_ragflow_client()
    return _ragflow_client


def get_report_generator_singleton():
    """获取报告生成器单例"""
    global _report_generator
    if _report_generator is None:
        _report_generator = get_report_generator()
    return _report_generator