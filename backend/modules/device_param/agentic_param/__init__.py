# cython: annotation_typing=False, infer_types=False, language_level=3
"""agentic_param —— 设备参数自主诊断 agent（独立模块，不依赖质量域 agentic_qa）。

ReAct + function-calling：给定一台设备，自主决定调用哪些参数分析工具
（画像/趋势总览/Cpk/RUL/对标/前兆/告警），多轮取证后产出结构化诊断。
LLM 客户端从 core.config.CONFIG 自建，与 agentic_qa 完全解耦。
"""
from .loop import run_diagnosis

__all__ = ["run_diagnosis"]
