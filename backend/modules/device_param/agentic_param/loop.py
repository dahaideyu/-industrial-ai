# cython: annotation_typing=False, infer_types=False, language_level=3
"""ReAct 主循环（同步，native tool-calling）。独立于 agentic_qa。"""

import json
import time
from typing import Any, Dict, List

from .llm import get_client, get_model
from .prompt import SYSTEM_PROMPT
from .tools import TOOLS, TOOLS_SCHEMA

MAX_ROUNDS = 7
_MAX_TOOL_CHARS = 7000


def run_diagnosis(device_code: str, max_rounds: int = MAX_ROUNDS,
                  extra_hint: str = "") -> Dict[str, Any]:
    """对单台设备跑诊断 agent。返回 {diagnosis(markdown), trace, rounds, elapsed_ms}。

    device_code 强制锁定本次设备（忽略 LLM 在工具参数里传的 device_code）。
    """
    t0 = time.time()
    client, model = get_client(), get_model()
    user = f"请诊断设备 {device_code}。"
    if extra_hint:
        user += f"\n额外关注：{extra_hint}"
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    trace: List[Dict[str, Any]] = []
    final = ""
    rounds = 0

    while rounds < max_rounds:
        rounds += 1
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0.2,
                max_tokens=2200, tools=TOOLS_SCHEMA, tool_choice="auto")
        except Exception as e:
            return {"device_code": device_code, "diagnosis": "",
                    "error": f"LLM 调用失败: {e}", "trace": trace,
                    "rounds": rounds, "elapsed_ms": round((time.time() - t0) * 1000)}

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:                       # 无工具调用=给出最终诊断
            final = msg.content or ""
            messages.append({"role": "assistant", "content": final})
            break

        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": tc.id, "type": "function",
                                         "function": {"name": tc.function.name,
                                                      "arguments": tc.function.arguments}}
                                        for tc in tool_calls]})
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            args.pop("device_code", None)        # 锁定本次设备
            fn = TOOLS.get(name)
            if fn is None:
                result = {"error": f"未知工具: {name}"}
            else:
                try:
                    result = fn(device_code, **args)
                except Exception as e:
                    result = {"error": str(e)}
            trace.append({"tool": name, "args": args,
                          "ok": "error" not in result})
            rj = json.dumps(result, ensure_ascii=False, default=str)
            if len(rj) > _MAX_TOOL_CHARS:
                rj = rj[:_MAX_TOOL_CHARS] + "...(截断)"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": rj})

    if not final:
        final = "（多轮取证后未生成诊断结论，可能数据不足，请先回填统计/建画像后重试。）"
    return {"device_code": device_code, "diagnosis": final, "trace": trace,
            "rounds": rounds, "elapsed_ms": round((time.time() - t0) * 1000)}
