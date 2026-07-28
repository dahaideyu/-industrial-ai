"""Unit tests for backend/services/knowledge_qa/message_history.py"""
from backend.services.knowledge_qa.message_history import MessageHistoryBuilder


def test_class_exists_with_build_method():
    assert hasattr(MessageHistoryBuilder, "build")
    assert hasattr(MessageHistoryBuilder, "summarize_history")


def test_build_returns_empty_when_no_history():
    b = MessageHistoryBuilder(max_tokens=6000, full_turns=3)
    result = b.build(question="hi", recent_messages=[])
    assert result == [{"role": "user", "content": "hi"}]


def test_build_keeps_recent_n_turns_intact():
    """最近 N 轮（按 turn = 2 messages）保留原文。"""
    msgs = []
    for i in range(5):
        msgs.append({"role": "user", "content": f"Q{i}"})
        msgs.append({"role": "assistant", "content": f"A{i}"})

    b = MessageHistoryBuilder(max_tokens=100000, full_turns=3)
    result = b.build(question="Q5", recent_messages=msgs)
    # 期望：完整保留最近 3 轮 (Q2, A2, Q3, A3, Q4, A4) + 当前问题 = 6 + 1 = 7
    assert len(result) == 7
    assert result[-1] == {"role": "user", "content": "Q5"}


def test_build_uses_summary_for_older_turns():
    """当历史超过 full_turns 时，更早的轮次被压缩为 system 摘要。"""
    msgs = []
    for i in range(10):
        msgs.append({"role": "user", "content": f"Q{i}"})

    b = MessageHistoryBuilder(max_tokens=100000, full_turns=3)
    # 使用固定摘要 stub
    result = b.build(
        question="Q10",
        recent_messages=msgs,
        summary_func=lambda older: f"已压缩 {len(older)} 条历史",
    )
    # full_turns=3 表示保留最近 3 轮（6 条消息）
    # 期望：1 条 system 摘要 + 4 条 older(Q0-Q3) 已压入摘要 + 6 条 keep(Q4-Q9) + Q10
    # summary_func 返回的 older 数量为 4（被压缩掉的部分）
    assert result[0]["role"] == "system"
    assert "已压缩" in result[0]["content"]
    assert "4" in result[0]["content"]
    assert result[-1] == {"role": "user", "content": "Q10"}
    # 验证最近 3 轮（Q4-Q9）保留为原文
    assert result[1] == {"role": "user", "content": "Q4"}
    assert result[-2] == {"role": "user", "content": "Q9"}


def test_summarize_history_returns_string():
    b = MessageHistoryBuilder(max_tokens=6000, full_turns=3)
    older = [
        {"role": "user", "content": "Q1"},
        {"role": "assistant", "content": "A1"},
    ]
    result = b.summarize_history(older, llm_call=lambda p: "历史摘要")
    assert result == "历史摘要"
