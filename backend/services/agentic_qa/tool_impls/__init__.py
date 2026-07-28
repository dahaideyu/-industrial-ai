# cython: annotation_typing=False, infer_types=False, language_level=3
"""Tool implementations — all BaseTool subclasses for agentic QA.

Usage:
    from backend.services.agentic_qa.tool_impls import ALL_TOOLS

    registry = ToolRegistry()
    for tool in ALL_TOOLS:
        registry.register(tool)
"""
from backend.services.agentic_qa.base_tool import BaseTool

# SQL tools
from backend.services.agentic_qa.tool_impls.sql_tools import (
    GenerateSqlTool,
    ExecuteSqlTool,
    DiagnoseSqlErrorTool,
    TypoCheckTool,
)

# Entity tools
from backend.services.agentic_qa.tool_impls.entity_tools import (
    SearchEntitiesTool,
    GetSchemaTool,
)

# Clarification tool
from backend.services.agentic_qa.tool_impls.clarify_tool import AskClarificationTool

# RAG tool
from backend.services.agentic_qa.tool_impls.rag_tool import QueryRagTool

# Analysis tool
from backend.services.agentic_qa.tool_impls.analysis_tool import AnalyzeDataTool

# General tool
from backend.services.agentic_qa.tool_impls.general_tool import AnswerGeneralTool

# Memory tool
from backend.services.agentic_qa.tool_impls.memory_tool import ReadMemoryTool

# Instantiate all tools
ALL_TOOLS: list[BaseTool] = [
    GenerateSqlTool(),
    ExecuteSqlTool(),
    DiagnoseSqlErrorTool(),
    TypoCheckTool(),
    SearchEntitiesTool(),
    GetSchemaTool(),
    AskClarificationTool(),
    QueryRagTool(),
    AnalyzeDataTool(),
    AnswerGeneralTool(),
    ReadMemoryTool(),
]

__all__ = [
    "ALL_TOOLS",
    "GenerateSqlTool",
    "ExecuteSqlTool",
    "DiagnoseSqlErrorTool",
    "TypoCheckTool",
    "SearchEntitiesTool",
    "GetSchemaTool",
    "AskClarificationTool",
    "QueryRagTool",
    "AnalyzeDataTool",
    "AnswerGeneralTool",
    "ReadMemoryTool",
]
