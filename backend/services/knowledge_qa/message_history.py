# cython: annotation_typing=False, infer_types=False, language_level=3
"""构造 messages 上下文：含 token 截断 + 摘要压缩。"""

from typing import Callable, List, Sequence


# 粗略估算：1 个中文字符 ≈ 1.5 token，1 个英文单词 ≈ 1.3 token
def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    chinese = sum(1 for c in text if "一" <= c <= "鿿")
    other = len(text) - chinese
    return int(chinese * 1.5 + other * 0.5)


class MessageHistoryBuilder:
    """构造多轮 messages，包含 token 截断 + 摘要压缩策略。

    策略：
    - 优先保留最近 N 轮（full_turns）的原文
    - 更早的轮次用 LLM 摘要压缩为 1 条 system 消息
    - 总 token 数控制在 max_tokens 以内
    """

    def __init__(self, max_tokens: int = 6000, full_turns: int = 3):
        self.max_tokens = max_tokens
        self.full_turns = full_turns

    def build(
        self,
        question: str,
        recent_messages: Sequence[dict],
        summary_func: Callable[[List[dict]], str] = None,
    ) -> List[dict]:
        """构造 messages 列表。

        Args:
            question: 当前用户问题
            recent_messages: 历史消息（按时间正序），每个含 role/content
            summary_func: 用于压缩历史的函数（接收 older 消息列表，返回摘要文本）

        Returns:
            messages 列表
        """
        # 1. 划分：更早轮次 vs 最近 N 轮
        if len(recent_messages) <= self.full_turns * 2:
            older = []
            keep = list(recent_messages)
        else:
            split_idx = len(recent_messages) - self.full_turns * 2
            older = list(recent_messages[:split_idx])
            keep = list(recent_messages[split_idx:])

        # 2. 构造结果
        result: List[dict] = []
        if older and summary_func is not None:
            summary_text = summary_func(older)
            result.append(
                {
                    "role": "system",
                    "content": f"以下是历史对话摘要：\n{summary_text}",
                }
            )
        for m in keep:
            result.append({"role": m["role"], "content": m["content"]})
        result.append({"role": "user", "content": question})

        # 3. token 截断
        total = sum(_estimate_tokens(m["content"]) for m in result)
        if total <= self.max_tokens:
            return result

        # 超限：从最早非 system 消息开始丢
        first_non_system = next(
            (i for i, m in enumerate(result) if m["role"] != "system"),
            0,
        )
        while total > self.max_tokens and first_non_system < len(result) - 2:
            dropped = result.pop(first_non_system)
            total -= _estimate_tokens(dropped["content"])

        return result

    def summarize_history(
        self,
        older_messages: List[dict],
        llm_call: Callable[[str], str],
    ) -> str:
        """调用 LLM 摘要历史问答。"""
        lines = []
        for m in older_messages:
            prefix = "用户" if m["role"] == "user" else "助手"
            lines.append(f"{prefix}：{m['content']}")
        conversation = "\n".join(lines)

        prompt = (
            "请将以下历史对话压缩为简洁的摘要，保留关键信息（不超过 300 字）：\n\n"
            f"{conversation}\n\n"
            "摘要："
        )
        return llm_call(prompt)
