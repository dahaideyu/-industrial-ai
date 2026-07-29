#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RAGFlow 流式输出诊断测试脚本

用法:
    # 设置环境变量后运行
    set RAGFLOW_TEST_URL=http://your-ragflow:9380
    set RAGFLOW_TEST_KEY=ragflow-xxxxxx
    python tests/test_ragflow_stream.py

    # 或者直接修改下面的 DEFAULTS 字典后运行
    python tests/test_ragflow_stream.py

测试内容:
    1. SSE 流式解析是否完整 (最终帧文本是否丢失)
    2. 增量 delta 计算是否正确
    3. 思维链/正文分离是否正确
    4. references 引用数据是否完整
    5. 网络连通性和响应延迟
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# 修复 Windows 系统代理导致 httpx 超时的问题
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,::1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1,::1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

# ============================================================
# 配置加载
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    # 优先加载根目录 .env (测试环境), 再加载 deploy/docker/.env (生产环境)
    for env_path in [
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / ".env.local",
        PROJECT_ROOT / "deploy" / "docker" / ".env",
    ]:
        if env_path.exists():
            load_dotenv(env_path, override=False)
except ImportError:
    pass

# 优先级: 命令行环境变量 > .env 文件 > 默认值
RAGFLOW_URL = (
    os.getenv("RAGFLOW_TEST_URL") or os.getenv("RAGFLOW_BASE_URL") or ""
).rstrip("/")
RAGFLOW_KEY = os.getenv("RAGFLOW_TEST_KEY") or os.getenv("RAGFLOW_API_KEY") or ""
RAGFLOW_CHAT_ID = os.getenv("RAGFLOW_TEST_CHAT_ID") or os.getenv("RAGFLOW_CHAT_ID") or ""
RAGFLOW_LLM_ID = os.getenv("RAGFLOW_LLM_ID") or os.getenv("RAGFLOW_MODEL") or None

# 硬编码默认值 (方便本地快速测试, 匹配 .env 中的测试环境配置)
if not RAGFLOW_URL:
    RAGFLOW_URL = "http://localhost:9380"
if not RAGFLOW_KEY:
    # 从 .env 加载后应该已经有了; 如果还没有, 使用测试环境 key
    RAGFLOW_KEY = os.getenv("RAGFLOW_API_KEY", "CHANGE_ME")

# ============================================================
# SSE 解析逻辑 (与 client.py 完全一致)
# ============================================================


def parse_sse_line(line: str) -> Optional[dict]:
    """解析 SSE 行, 去掉 data: 前缀并返回 JSON"""
    line = line.strip()
    if not line:
        return None
    json_str = line
    if line.startswith("data: "):
        json_str = line[6:]
    elif line.startswith("data:"):
        json_str = line[5:]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


# ============================================================
# 思维链分离 (与 client.py 完全一致)
# ============================================================
_THINKING_PREFIXES = [
    "好的,用户的问题", "好的,用户询问", "好的,我来分析", "好的,让我来",
    "让我来分析", "让我梳理一下", "首先,我需要理解", "根据用户的问题,我需要",
]
_ANSWER_TRANSITIONS = [
    "根据提供的知识库", "根据知识库内容", "根据知识库,",
    "根据检索到的信息", "以下是", "回答如下", "总结如下",
]


def split_thinking(answer: str) -> tuple:
    """分离思考内容和正文, 返回 (thinking, body)"""
    if not answer:
        return "", ""

    # 策略 1: 显式 <think> 标签
    if "<think>" in answer and "</think>" in answer:
        ts = answer.find("<think>")
        te = answer.find("</think>") + len("</think>")
        thinking = answer[ts + len("<think>"): te - len("</think>")].strip()
        body = (answer[:ts] + answer[te:]).strip()
        return thinking, body

    # 策略 2: 检测无标签的思维前缀
    stripped = answer.lstrip()
    for prefix in _THINKING_PREFIXES:
        if stripped.startswith(prefix):
            earliest_idx = len(answer)
            for trans in _ANSWER_TRANSITIONS:
                idx = answer.find(trans)
                if idx != -1 and idx < earliest_idx:
                    earliest_idx = idx
            if earliest_idx > 0 and earliest_idx < len(answer):
                thinking = answer[:earliest_idx].strip()
                body = answer[earliest_idx:].strip()
                return thinking, body
            first_newline = answer.find("\n")
            if first_newline > 0:
                thinking = answer[:first_newline].strip()
                body = answer[first_newline:].strip()
                return thinking, body
            break
    return "", answer.strip()


# ============================================================
# 测试 1: 连通性
# ============================================================
def test_connectivity() -> bool:
    print("=" * 60)
    print("测试 1: RAGFlow 服务连通性")
    print("=" * 60)
    print(f"  URL:       {RAGFLOW_URL}")
    key_display = "***" + RAGFLOW_KEY[-8:] if len(RAGFLOW_KEY) > 8 else "(未设置)"
    print(f"  API Key:   {key_display}")
    print(f"  LLM ID:    {RAGFLOW_LLM_ID or '(使用 RAGFlow 默认模型)'}")
    print(f"  Chat ID:   {RAGFLOW_CHAT_ID or '(未设置)'}")
    print()

    if not RAGFLOW_URL or not RAGFLOW_KEY:
        print("  [FAIL] 未配置 RAGFLOW 地址或 API Key")
        print("  请设置环境变量 RAGFLOW_TEST_URL 和 RAGFLOW_TEST_KEY")
        print("  或修改脚本开头的 DEFAULTS 字典")
        return False

    try:
        t0 = time.time()
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                f"{RAGFLOW_URL}/api/v1/app",
                headers={"Authorization": f"Bearer {RAGFLOW_KEY}"},
            )
        elapsed = round((time.time() - t0) * 1000)
        print(f"  [OK] 服务可达 (HTTP {resp.status_code}, {elapsed}ms)")
        return True
    except httpx.ConnectError:
        print(f"  [FAIL] 无法连接 RAGFlow 服务: {RAGFLOW_URL}")
        print(f"         请确认 RAGFlow 已启动且端口可达")
        return False
    except Exception as e:
        print(f"  [FAIL] 连接异常: {e}")
        return False


# ============================================================
# 测试 2: 非流式请求 (对比基线)
# ============================================================
def test_non_stream() -> bool:
    print()
    print("=" * 60)
    print("测试 2: 非流式请求 (对比基线)")
    print("=" * 60)

    question = os.getenv("TEST_QUESTION", "设备维护保养怎么做?")
    print(f"  问题: {question}")
    print()

    payload: dict = {
        "messages": [{"role": "user", "content": question}],
        "stream": False,
    }
    if RAGFLOW_CHAT_ID:
        payload["chat_id"] = RAGFLOW_CHAT_ID
    if RAGFLOW_LLM_ID:
        payload["llm_id"] = RAGFLOW_LLM_ID

    try:
        t0 = time.time()
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{RAGFLOW_URL}/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {RAGFLOW_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        elapsed = round((time.time() - t0) * 1000)
        data = resp.json()
        answer = ""
        refs = {}
        if isinstance(data.get("data"), dict):
            answer = data["data"].get("answer", "")
            refs = data["data"].get("reference", {})

        print(f"  HTTP {resp.status_code} ({elapsed}ms)")
        print(f"  回答长度: {len(answer)} 字符")
        print(f"  引用 chunks: {len(refs.get('chunks', []))} 个")
        print(f"  非流式不带 reference: {not bool(refs)}")
        if answer:
            preview = answer[:120] + "..." if len(answer) > 120 else answer
            print(f"  回答预览: {preview}")
        return True
    except Exception as e:
        print(f"  [FAIL] 请求失败: {e}")
        return False


# ============================================================
# 测试 3: 流式 SSE 核心诊断
# ============================================================
def test_streaming() -> bool:
    print()
    print("=" * 60)
    print("测试 3: 流式 SSE 完整解析 (核心诊断)")
    print("=" * 60)

    question = os.getenv("TEST_QUESTION", "设备维护保养怎么做?")
    print(f"  问题: {question}")
    print()

    payload: dict = {
        "messages": [{"role": "user", "content": question}],
        "stream": True,
    }
    if RAGFLOW_CHAT_ID:
        payload["chat_id"] = RAGFLOW_CHAT_ID
    if RAGFLOW_LLM_ID:
        payload["llm_id"] = RAGFLOW_LLM_ID

    events = []
    line_count = 0
    data_count = 0
    stream_error = None
    final_answer = ""
    prev_answer = ""
    deltas_received = []
    delta_before_break = None  # 修复前会丢失的 delta
    final_frame_delta_sent = False
    has_references = False
    chunks_count = 0

    print("  开始接收 SSE 流...")
    t0 = time.time()

    try:
        with httpx.Client(timeout=120.0) as client:
            with client.stream(
                "POST",
                f"{RAGFLOW_URL}/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {RAGFLOW_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as response:
                print(f"  HTTP {response.status_code}")

                if response.status_code != 200:
                    print(f"  [FAIL] HTTP 错误: {response.status_code}")
                    try:
                        body = response.read().decode()
                        print(f"  响应体: {body[:500]}")
                    except Exception:
                        pass
                    return False

                for line in response.iter_lines():
                    line_count += 1
                    data = parse_sse_line(line)
                    if data is None:
                        continue
                    data_count += 1

                    evt = {
                        "seq": data_count,
                        "is_final": False,
                        "answer_len": 0,
                        "chunk_count": 0,
                        "has_reference": False,
                    }

                    # 应用层错误
                    if isinstance(data.get("code"), int) and data.get("code", 0) != 0:
                        stream_error = data.get("message", f"code={data.get('code')}")
                        evt["error"] = stream_error
                        events.append(evt)
                        break

                    # 流结束标记
                    if isinstance(data.get("data"), bool):
                        events.append(evt)
                        break

                    answer_data = data.get("data", {})
                    if not isinstance(answer_data, dict):
                        continue

                    answer = answer_data.get("answer", "")
                    is_final = answer_data.get("final", False)
                    ref_raw = answer_data.get("reference")

                    evt["answer_len"] = len(answer)
                    evt["is_final"] = is_final
                    evt["has_reference"] = bool(ref_raw and isinstance(ref_raw, dict))
                    if evt["has_reference"]:
                        evt["chunk_count"] = len(ref_raw.get("chunks", []))

                    # ---- 模拟修复前的 bug: 先检查 is_final 再发 delta ----
                    if is_final:
                        if answer and answer != prev_answer:
                            delta_before_break = answer[len(prev_answer):]
                        final_answer = answer
                        if ref_raw and isinstance(ref_raw, dict):
                            has_references = True
                            chunks_count = len(ref_raw.get("chunks", []))
                        evt["note"] = "FINAL - 旧代码在此break, delta可能丢失"
                        events.append(evt)
                        break  # <-- 旧代码先break

                    # ---- 正确顺序: 先发 delta 再检查 is_final ----
                    if answer and answer != prev_answer:
                        delta = answer[len(prev_answer):]
                        prev_answer = answer
                        deltas_received.append(delta)
                        if is_final:
                            final_frame_delta_sent = True

                    events.append(evt)

    except Exception as e:
        print(f"  [FAIL] 流式请求异常: {e}")
        return False

    elapsed = round((time.time() - t0) * 1000)

    # ---- 诊断报告 ----
    print()
    print("  --- 流式诊断报告 ---")
    print(f"  总耗时:            {elapsed}ms")
    print(f"  SSE 原始行数:      {line_count}")
    print(f"  有效事件数:        {data_count}")
    print(f"  累积增量次数:      {len(deltas_received)}")
    print(f"  最终文本长度:      {len(final_answer)} 字符")

    # 检查 1: 最终帧 delta 是否丢失
    print()
    if delta_before_break:
        print(f"  [FAIL] 问题1 - 最终帧文本丢失")
        print(f"         修复前会丢失 {len(delta_before_break)} 字符:")
        print(f"         '{delta_before_break[:100]}'")
    else:
        print(f"  [OK]   问题1 - 最终帧无额外增量 (正常)")

    # 检查 2: 增量连续性
    all_deltas = "".join(deltas_received)
    if all_deltas != final_answer and final_answer:
        missing_len = len(final_answer) - len(all_deltas)
        if missing_len > 0:
            missing_text = final_answer[len(all_deltas):]
            print(f"  [FAIL] 问题2 - 增量不连续, 丢失 {missing_len} 字符")
            print(f"         丢失内容: '{missing_text[:100]}'")
        else:
            print(f"  [WARN] 问题2 - 增量比最终文本多 {abs(missing_len)} 字符")
    else:
        print(f"  [OK]   问题2 - 增量拼接与最终文本一致")

    # 检查 3: 思维链
    thinking, body = split_thinking(final_answer)
    if thinking:
        print(f"  [WARN] 问题3 - 存在思维链内容 ({len(thinking)} 字符)")
        print(f"         思维链: {thinking[:150]}...")
        print(f"         正文:   {body[:150]}...")
    else:
        print(f"  [OK]   问题3 - 未检测到思维链内容")

    # 检查 4: references
    if has_references:
        print(f"  [OK]   问题4 - 获取到引用数据: {chunks_count} 个 chunks")
    else:
        print(f"  [WARN] 问题4 - 未获取到引用数据")

    # 检查 5: 流式错误
    if stream_error:
        print(f"  [FAIL] 问题5 - 流式错误: {stream_error}")
    else:
        print(f"  [OK]   问题5 - 未检测到流式错误")

    # 最终输出预览
    print()
    print(f"  --- 最终输出预览 ---")
    display = final_answer[:400] + "..." if len(final_answer) > 400 else final_answer
    for line in display.split("\n")[:10]:
        print(f"    {line}")

    # 事件时间线
    print()
    print(f"  --- 事件时间线 (最后 6 个事件) ---")
    for evt in events[-6:]:
        flags = []
        if evt.get("is_final"):
            flags.append("FINAL")
        if evt.get("has_reference"):
            flags.append(f"refs={evt.get('chunk_count')}")
        if evt.get("note"):
            flags.append(evt["note"])
        flag_str = " | ".join(flags) if flags else ""
        print(f"    #{evt['seq']:2d}  answer_len={evt['answer_len']:5d}  {flag_str}")

    return True


# ============================================================
# 测试 4: 带历史消息的流式请求
# ============================================================
def test_with_history() -> bool:
    print()
    print("=" * 60)
    print("测试 4: 带历史消息的流式请求")
    print("=" * 60)

    question = "设备保养周期是多少?"
    history = [
        {"role": "user", "content": "什么是设备维护保养?"},
        {"role": "assistant", "content": "设备维护保养是指定期对设备进行检查、清洁、润滑、调整和更换易损件等工作。"},
    ]

    print(f"  历史消息: {len(history)} 条")
    print(f"  当前问题: {question}")
    print()

    payload: dict = {
        "messages": history + [{"role": "user", "content": question}],
        "stream": True,
    }
    if RAGFLOW_CHAT_ID:
        payload["chat_id"] = RAGFLOW_CHAT_ID
    if RAGFLOW_LLM_ID:
        payload["llm_id"] = RAGFLOW_LLM_ID

    final_answer = ""
    prev_answer = ""
    refs_count = 0
    deltas_count = 0
    final_frame_has_delta = False

    try:
        t0 = time.time()
        with httpx.Client(timeout=120.0) as client:
            with client.stream(
                "POST",
                f"{RAGFLOW_URL}/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {RAGFLOW_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as response:
                print(f"  HTTP {response.status_code}")

                for line in response.iter_lines():
                    data = parse_sse_line(line)
                    if data is None:
                        continue
                    if isinstance(data.get("code"), int) and data.get("code", 0) != 0:
                        print(f"  [FAIL] 错误: {data.get('message')}")
                        return False
                    if isinstance(data.get("data"), bool):
                        break

                    answer_data = data.get("data", {})
                    if not isinstance(answer_data, dict):
                        continue

                    answer = answer_data.get("answer", "")
                    is_final = answer_data.get("final", False)

                    # 正确顺序: 先发 delta 再 break
                    if answer and answer != prev_answer:
                        deltas_count += 1
                        prev_answer = answer
                        if is_final:
                            final_frame_has_delta = True

                    if is_final:
                        final_answer = answer
                        if answer_data.get("reference"):
                            refs_count = len(answer_data["reference"].get("chunks", []))
                        break

        elapsed = round((time.time() - t0) * 1000)
        print(f"  耗时:        {elapsed}ms")
        print(f"  delta 次数:  {deltas_count}")
        print(f"  最终帧有增量: {final_frame_has_delta}")
        print(f"  回答长度:    {len(final_answer)} 字符")
        print(f"  引用 chunks: {refs_count} 个")
        print(f"  [OK] 带历史消息的流式请求正常")
        return True
    except Exception as e:
        print(f"  [FAIL] 请求失败: {e}")
        return False


# ============================================================
# 主入口
# ============================================================
def main() -> int:
    print()
    print("=" * 60)
    print("  RAGFlow 流式输出诊断测试")
    print("=" * 60)
    print()

    results = {}

    # 1. 连通性 (必须通过)
    results["connectivity"] = test_connectivity()
    if not results["connectivity"]:
        print()
        print("[FAIL] RAGFlow 服务不可达, 终止后续测试")
        print()
        print("请先设置环境变量后重试:")
        print("  set RAGFLOW_TEST_URL=http://your-ragflow-host:9380")
        print("  set RAGFLOW_TEST_KEY=ragflow-xxxxxxxxxxxxxx")
        print()
        print("或修改脚本末尾 DEFAULTS 字典")
        return 1

    # 2. 非流式
    results["non-stream"] = test_non_stream()

    # 3. 流式 SSE
    results["streaming"] = test_streaming()

    # 4. 带历史
    results["with_history"] = test_with_history()

    # 总结
    print()
    print("=" * 60)
    print("诊断总结")
    print("=" * 60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, ok in results.items():
        status = "[OK]" if ok else "[FAIL]"
        print(f"  {status}  {name}")
    print(f"\n  通过: {passed}/{total}")

    if passed < total:
        print()
        print("  建议:")
        if not results.get("streaming"):
            print("  - 流式测试未通过, 请查看上方详细诊断报告")
        print("  - 对比非流式和流式结果的差异, 定位问题所在")

    print()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
