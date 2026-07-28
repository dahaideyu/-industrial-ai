# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库管理模块自定义异常"""


class KnowledgeBaseError(Exception):
    """知识库管理模块基础异常"""
    pass


class NotFoundError(KnowledgeBaseError):
    """资源未找到"""
    pass


class ValidationError(KnowledgeBaseError):
    """数据校验失败"""
    pass


class RAGFlowError(KnowledgeBaseError):
    """RAGFlow API 调用异常"""
    pass


class TaskError(KnowledgeBaseError):
    """后台任务异常"""
    pass
