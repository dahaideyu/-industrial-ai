# cython: annotation_typing=False, infer_types=False, language_level=3
"""PLC 图纸解析服务

基于视觉模型和文本模型的工业 PLC 程序图纸/电气原理图智能解析工具。
流程：PDF 预处理 -> 微观逐页解析 -> 宏观全局梳理 -> 报告生成
"""
from backend.services.plc_analysis_report.main import PLCAnalysisService

# 模块级单例
plc_service = PLCAnalysisService()

__all__ = ["plc_service", "PLCAnalysisService"]
