# cython: annotation_typing=False, infer_types=False, language_level=3
"""KB 路由：基于问题+历史+手动选择，用 LLM 判断本次检索的 KB 列表。"""

import json
import re
from typing import Callable, List, Optional, Sequence


PROMPT_TEMPLATE = """你是知识库路由助手。基于用户问题、历史对话、用户手动选定的知识库，判断本次检索应使用哪些知识库。

## 可用知识库列表
{available_kbs_text}

## 用户手动选定的知识库（必须保留）
{manual_kb_ids_text}

## 用户问题
{question}

## 历史对话摘要
{history_text}

## 输出要求
- 用户手动选定的知识库必须包含在结果中
- 可补充 AI 认为需要的知识库
- 仅输出 JSON 数组，不要其他说明，例如：["kb-1", "kb-3"]
"""


class KbRouter:
    """调用 LLM 判断本次问题应使用的 KB 列表。

    用于多知识库场景下，根据用户问题、历史对话与用户手动选择，
    由 LLM 决策本次检索应激活哪些知识库。
    """

    def __init__(self, llm_call: Optional[Callable[[str], str]] = None):
        self._llm_call = llm_call

    def route(
        self,
        question: str,
        history: Sequence[dict],
        manual_kb_ids: List[str],
        available_kbs: List[dict],
        llm_call: Optional[Callable[[str], str]] = None,
    ) -> List[str]:
        """返回本次应使用的 KB id 列表。

        Args:
            question: 用户问题
            history: 历史消息列表
            manual_kb_ids: 用户手动选择的 KB id 列表（会强制包含在结果中）
            available_kbs: 所有可用的 KB 元数据
            llm_call: LLM 调用函数（接收 prompt，返回文本响应）

        Returns:
            KB id 列表；失败时返回空列表
        """
        llm = llm_call or self._llm_call
        if llm is None:
            return []

        kb_lines = []
        for kb in available_kbs:
            kb_lines.append(
                f"- id={kb['id']} name={kb.get('name', '')} desc={kb.get('description', '')}"
            )
        available_kbs_text = "\n".join(kb_lines) or "（无）"
        manual_kb_ids_text = ", ".join(manual_kb_ids) or "（无）"

        history_lines = []
        for m in history[-6:]:
            prefix = "用户" if m["role"] == "user" else "助手"
            history_lines.append(f"{prefix}：{m['content'][:200]}")
        history_text = "\n".join(history_lines) or "（无历史）"

        prompt = PROMPT_TEMPLATE.format(
            available_kbs_text=available_kbs_text,
            manual_kb_ids_text=manual_kb_ids_text,
            question=question,
            history_text=history_text,
        )

        try:
            response = llm(prompt)
        except Exception:
            return []

        valid_ids = {kb["id"] for kb in available_kbs}
        parsed = self._parse_ids(response, valid_ids)

        # 强制保留手动选择的 KB（若仍在 available 列表中）
        for kid in manual_kb_ids:
            if kid in valid_ids and kid not in parsed:
                parsed.append(kid)

        return parsed

    @staticmethod
    def _parse_ids(response: str, valid_ids: set) -> List[str]:
        """从 LLM 响应中提取 kb id 列表。

        支持：
        - 纯 JSON 数组：[\"kb-1\", \"kb-3\"]
        - 文本中嵌入的 JSON 数组：reasoning ... [\"kb-1\"]
        """
        match = re.search(r"\[([^\]]*)\]", response)
        if not match:
            return []
        try:
            ids = json.loads("[" + match.group(1) + "]")
        except json.JSONDecodeError:
            try:
                ids = json.loads(response)
            except json.JSONDecodeError:
                return []
        return [i for i in ids if isinstance(i, str) and i in valid_ids]