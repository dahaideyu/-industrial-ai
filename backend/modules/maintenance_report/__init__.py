# cython: annotation_typing=False, infer_types=False, language_level=3
"""
预测性维护报告模块

功能：
- 日报：每日凌晨自动生成，基于过去24小时数据
- 周报：每周一自动生成，基于过去7天数据
- 月报：每月1日自动生成，基于过去30天数据

每份报告包含：
- 报警统计分析
- 健康评估
- 故障预测
- 预测性维护建议
"""

from .routes import router as maintenance_report_router

__all__ = ["maintenance_report_router"]
