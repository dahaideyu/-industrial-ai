# cython: annotation_typing=False, infer_types=False, language_level=3
"""BaseTool plugin architecture -- core abstractions for agentic QA tools."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from backend.core.agentic_qa.logger import get_logger

logger = get_logger("agentic_qa.base_tool")

# ── Chinese title mapping for each tool ──

TOOL_TITLES: Dict[str, str] = {
    "preprocess": "信息提取",
    "entity_resolve": "实体检索",
    "search_entities": "实体搜索",
    "get_schema": "获取表结构",
    "generate_sql": "生成SQL查询",
    "execute_sql": "执行SQL查询",
    "diagnose_sql_error": "诊断SQL错误",
    "typo_check": "错别字检测",
    "analyze_data": "数据分析",
    "query_rag": "文档检索",
    "answer_general": "直接回答",
    "read_memory": "读取记忆",
    "ask_clarification": "请求澄清",
}


# ── ToolContext ──

@dataclass
class ToolContext:
    """Runtime context passed to every tool invocation."""

    session_id: str
    memory_hub: Any  # MemoryHub instance
    step_callback: Optional[Callable] = None
    confirmed_entities: List[Dict] = field(default_factory=list)
    entity_candidates: Dict = field(default_factory=dict)


# ── BaseTool (ABC) ──

class BaseTool(ABC):
    """Abstract base class for all agentic QA tools.

    Subclasses must define:
        - name (str): unique tool identifier
        - description (str): what the tool does
        - schema (dict): JSON Schema for the tool's parameters
        - run(ctx, **kwargs) -> dict: async execution logic

    Optional:
        - when_to_use (str): guidance for the planner on when to pick this tool
        - when_not_to_use (str): guidance on when NOT to use this tool
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier, e.g. 'search_entities'."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description of what the tool does."""

    @property
    @abstractmethod
    def schema(self) -> dict:
        """JSON Schema for the tool's input parameters."""

    @property
    def when_to_use(self) -> str:
        """When the planner should pick this tool."""
        return ""

    @property
    def when_not_to_use(self) -> str:
        """When the planner should NOT pick this tool."""
        return ""

    @abstractmethod
    async def run(self, ctx: ToolContext, **kwargs) -> dict:
        """Execute the tool and return a result dict."""

    def to_openai_schema(self) -> dict:
        """Auto-generate an OpenAI function-calling schema from this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }


# ── ToolRegistry ──

class ToolRegistry:
    """Registry that holds all registered BaseTool instances.

    Usage:
        registry = ToolRegistry()
        registry.register(my_tool)
        schema_list = registry.all_schemas()
        prompt = registry.prompt_section()
    """

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance. Overwrites if name already exists."""
        self._tools[tool.name] = tool
        logger.debug(f"[registry] registered tool: {tool.name}")

    def get(self, name: str) -> BaseTool:
        """Get a tool by name. Raises KeyError if not found."""
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        return self._tools[name]

    def all_schemas(self, exclude: set = None) -> list:
        """Return OpenAI function-calling schemas, optionally excluding some tools."""
        exclude = exclude or set()
        return [tool.to_openai_schema() for name, tool in self._tools.items() if name not in exclude]

    def prompt_section(self, exclude: set = None) -> str:
        """Auto-generate a system-prompt section listing all tools with usage guidance."""
        exclude = exclude or set()
        lines = ["## 可用工具\n"]
        for name, tool in self._tools.items():
            if name in exclude:
                continue
            title = TOOL_TITLES.get(tool.name, tool.name)
            lines.append(f"### {title} (`{tool.name}`)")
            lines.append(f"- 描述: {tool.description}")
            if tool.when_to_use:
                lines.append(f"- 何时使用: {tool.when_to_use}")
            if tool.when_not_to_use:
                lines.append(f"- 何时不使用: {tool.when_not_to_use}")
            lines.append("")
        return "\n".join(lines)

    @property
    def tools(self) -> Dict[str, BaseTool]:
        """Return the internal tools dict."""
        return self._tools


# ── StepBuilder ──

class StepBuilder:
    """Helper for building step records that appear in the master loop."""

    @staticmethod
    def build(
        tool_name: str,
        status: str,
        detail: str,
        elapsed_ms: int = 0,
        attempt: int = 1,
        error: Optional[str] = None,
    ) -> dict:
        """Build a step dict for the step log.

        Args:
            tool_name: identifier of the tool
            status: "running" | "success" | "error"
            detail: human-readable detail text
            elapsed_ms: execution time in milliseconds
            attempt: retry attempt number (1-based)
            error: error message if status == "error"
        """
        title = TOOL_TITLES.get(tool_name, tool_name)
        step: Dict[str, Any] = {
            "tool": tool_name,
            "title": title,
            "status": status,
            "detail": detail,
            "elapsed_ms": elapsed_ms,
            "attempt": attempt,
        }
        if error:
            step["error"] = error
        return step

    @staticmethod
    def detail_for_result(tool_name: str, result: dict) -> str:
        """Generate a detail string from a tool result dict.

        Tries common keys: 'answer', 'sql', 'insights', 'diagnosis', 'message',
        falls back to a generic summary.
        """
        for key in ("answer", "sql", "insights", "diagnosis", "message"):
            if key in result and result[key]:
                val = result[key]
                return str(val)[:200]
        # Fallback: summarize top-level keys
        if result.get("success") is False and result.get("error"):
            return f"错误: {result['error']}"
        if "row_count" in result:
            return f"返回 {result['row_count']} 行数据"
        return f"工具 {tool_name} 执行完成"

    @staticmethod
    def running_detail(tool_name: str) -> str:
        """Return a 'running' status detail for the given tool."""
        title = TOOL_TITLES.get(tool_name, tool_name)
        return f"正在执行{title}..."
