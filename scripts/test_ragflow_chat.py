"""
RAGFlow /api/v1/chat/completions 接口测试脚本

用法:
  python scripts/test_ragflow_chat.py                          # 交互模式
  python scripts/test_ragflow_chat.py "什么是设备效率？"        # 直接提问
  python scripts/test_ragflow_chat.py --list-chats             # 列出已有 chat assistant
  python scripts/test_ragflow_chat.py --create "测试助手"       # 创建新的 chat assistant
"""

import json
import sys
import os

# 修复 Windows GBK 编码下 emoji 输出问题
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

# ── 配置（优先本地 Docker，否则用 .env 中的远程地址） ──────────────
BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://localhost:9380")
API_KEY = os.getenv("RAGFLOW_API_KEY", "CHANGE_ME")
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# ── 颜色输出 ──────────────────────────────────────────────────────
class Colors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def cprint(color: str, *args):
    text = " ".join(str(a) for a in args)
    print(f"{color}{text}{Colors.RESET}")


def list_chats():
    """列出所有 Chat Assistant"""
    cprint(Colors.CYAN, f"\n📋 GET {BASE_URL}/api/v1/chats")
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{BASE_URL}/api/v1/chats", headers=HEADERS)
        data = resp.json()
        print(f"  状态码: {resp.status_code}")
        print(f"  原始响应:\n{json.dumps(data, ensure_ascii=False, indent=2)}")

        if data.get("code") == 0:
            chats = data.get("data", [])
            # 兼容嵌套结构
            if isinstance(chats, dict) and "chats" in chats:
                chats = chats["chats"]
            if chats:
                cprint(Colors.GREEN, f"\n  找到 {len(chats)} 个 Chat Assistant:")
                for c in chats:
                    name = c.get("name", "?")
                    cid = c.get("id", "?")
                    ds = c.get("dataset_ids", [])
                    cprint(Colors.MAGENTA, f"    • {name}")
                    print(f"      id={cid}  datasets={ds}")
            else:
                cprint(Colors.YELLOW, "  ⚠ 没有 Chat Assistant，需要先创建")
    except Exception as e:
        cprint(Colors.RED, f"  ✗ 请求失败: {e}")


def create_chat(name: str, dataset_ids: list = None) -> str | None:
    """创建 Chat Assistant，返回 chat_id"""
    payload = {"name": name, "dataset_ids": dataset_ids or []}
    cprint(Colors.CYAN, f"\n🔧 POST {BASE_URL}/api/v1/chats")
    print(f"  payload: {json.dumps(payload, ensure_ascii=False)}")
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(f"{BASE_URL}/api/v1/chats", headers=HEADERS, json=payload)
        data = resp.json()
        print(f"  状态码: {resp.status_code}")
        print(f"  响应:\n{json.dumps(data, ensure_ascii=False, indent=2)}")
        if data.get("code") == 0:
            chat_id = data["data"]["id"]
            cprint(Colors.GREEN, f"  ✓ 创建成功! chat_id = {chat_id}")
            return chat_id
        else:
            cprint(Colors.RED, f"  ✗ 创建失败: {data.get('message', '')}")
    except Exception as e:
        cprint(Colors.RED, f"  ✗ 请求失败: {e}")
    return None


def test_chat_completions(question: str, chat_id: str):
    """测试 /api/v1/chat/completions 流式接口，打印原始 SSE 输出"""
    url = f"{BASE_URL}/api/v1/chat/completions"
    payload = {
        "messages": [{"role": "user", "content": question}],
        "stream": True,
        "chat_id": chat_id,
    }

    cprint(Colors.CYAN, f"\n{'='*70}")
    cprint(Colors.CYAN, f"🚀 POST {url}")
    cprint(Colors.DIM, f"   chat_id: {chat_id}")
    cprint(Colors.DIM, f"   question: {question}")
    print(f"   payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    cprint(Colors.CYAN, f"{'='*70}")

    # ── 累积变量 ──
    full_answer = ""
    references = None
    event_count = 0

    try:
        with httpx.Client(timeout=120.0) as client:
            with client.stream("POST", url, headers=HEADERS, json=payload) as resp:
                cprint(Colors.YELLOW, f"\n📡 HTTP 状态码: {resp.status_code}")
                if resp.status_code != 200:
                    cprint(Colors.RED, f"  ✗ 错误: {resp.status_code}")
                    print(f"  {resp.text}")
                    return

                cprint(Colors.GREEN, "\n📦 原始 SSE 事件流:\n")

                # 按 \n\n 解析 SSE 事件
                buffer = ""
                for raw_chunk in resp.iter_raw():
                    buffer += raw_chunk.decode("utf-8", errors="replace")

                    while "\n\n" in buffer:
                        idx = buffer.index("\n\n")
                        event_text = buffer[:idx]
                        buffer = buffer[idx + 2:]

                        # 提取 data: 行
                        data_lines = []
                        for line in event_text.split("\n"):
                            line = line.strip()
                            if line.startswith("data:"):
                                # 去除 "data:" 或 "data: " 前缀
                                data_lines.append(line[5:].lstrip())

                        if not data_lines:
                            continue

                        full_json = "".join(data_lines)

                        # 尝试解析 JSON
                        try:
                            parsed = json.loads(full_json)
                        except json.JSONDecodeError:
                            print(f"  ⚠ JSON 解析失败: {full_json[:100]}...")
                            continue

                        event_count += 1

                        # ── 打印原始事件 ──
                        code = parsed.get("code", "?")
                        data_field = parsed.get("data")

                        # 流结束标记
                        if isinstance(data_field, bool):
                            cprint(Colors.MAGENTA, f"  [{event_count}] ★ 流结束标记 data={data_field}")
                            break

                        # 错误
                        if isinstance(code, int) and code != 0:
                            cprint(Colors.RED, f"  [{event_count}] ❌ 错误 code={code} "
                                   f"message={parsed.get('message', '?')}")
                            print(f"         原始: {json.dumps(parsed, ensure_ascii=False)}")
                            break

                        if not isinstance(data_field, dict):
                            cprint(Colors.DIM, f"  [{event_count}] data={data_field}")
                            continue

                        answer = data_field.get("answer", "")
                        is_final = data_field.get("final", False)
                        ref_raw = data_field.get("reference")

                        # 增量文本
                        if answer and answer != full_answer:
                            delta = answer[len(full_answer):]
                            full_answer = answer
                            cprint(Colors.GREEN, f"  [{event_count}] 📝 {repr(delta)}")

                        # 引用
                        if ref_raw and isinstance(ref_raw, dict):
                            references = ref_raw
                            total = ref_raw.get("total", 0)
                            chunks = ref_raw.get("chunks", [])
                            cprint(Colors.CYAN,
                                   f"  [{event_count}] 📎 references total={total} chunks={len(chunks)}")

                        if is_final:
                            cprint(Colors.MAGENTA, f"  [{event_count}] ★ final=True")

                # 处理 buffer 中残留的不完整事件
                if buffer.strip():
                    data_lines = []
                    for line in buffer.split("\n"):
                        line = line.strip()
                        if line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                    if data_lines:
                        try:
                            parsed = json.loads("".join(data_lines))
                            cprint(Colors.DIM, f"  [残留] {json.dumps(parsed, ensure_ascii=False)[:200]}")
                        except json.JSONDecodeError:
                            pass

        # ── 汇总 ──
        cprint(Colors.CYAN, f"\n{'='*70}")
        cprint(Colors.CYAN, "📊 结果汇总")
        cprint(Colors.CYAN, f"{'='*70}")
        print(f"  事件数: {event_count}")
        print(f"  回答长度: {len(full_answer)} 字符")

        if references:
            print(f"  引用总数: {references.get('total', 0)}")
            chunks = references.get("chunks", [])
            doc_aggs = references.get("doc_aggs", [])
            for i, doc in enumerate(doc_aggs[:5]):
                print(f"    文档 {i+1}: {doc.get('doc_name', '?')}")

        print(f"\n{'─'*70}")
        cprint(Colors.GREEN, f"📝 完整回答:\n{Colors.RESET}{full_answer}")
        print(f"{'─'*70}")

        if references:
            cprint(Colors.YELLOW, f"\n📎 引用详情:")
            for i, chunk in enumerate(references.get("chunks", [])[:3]):
                print(f"  chunk {i+1}: {json.dumps(chunk, ensure_ascii=False, indent=4)[:500]}")
                print()

    except httpx.HTTPError as e:
        cprint(Colors.RED, f"\n✗ 连接失败: {e}")
    except KeyboardInterrupt:
        cprint(Colors.YELLOW, "\n\n⚠ 用户中断")
    except Exception as e:
        cprint(Colors.RED, f"\n✗ 异常: {e}")


# ── 主入口 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--list-chats" in sys.argv:
        list_chats()
    elif "--create" in sys.argv:
        idx = sys.argv.index("--create")
        name = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "测试助手"
        create_chat(name)
    else:
        # 先列出已有的 chat，让用户选择一个
        cprint(Colors.CYAN, "🔍 获取已有 Chat Assistant...")
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{BASE_URL}/api/v1/chats", headers=HEADERS)
            data = resp.json()
            chats = []
            if data.get("code") == 0:
                raw = data.get("data", [])
                if isinstance(raw, dict) and "chats" in raw:
                    chats = raw["chats"]
                elif isinstance(raw, list):
                    chats = raw

            if not chats:
                cprint(Colors.YELLOW, "⚠ 没有已有的 Chat Assistant，请先创建:")
                print('  python scripts/test_ragflow_chat.py --create "你的助手名"')
                sys.exit(1)

            cprint(Colors.GREEN, f"找到 {len(chats)} 个 Chat Assistant:")
            for i, c in enumerate(chats):
                print(f"  [{i}] {c.get('name', '?')}  (id={c.get('id', '?')[:20]}...)")

            # 指定了 index 参数？
            selected_idx = None
            if len(sys.argv) > 1 and sys.argv[-1].isdigit():
                selected_idx = int(sys.argv[-1])
                question = " ".join(sys.argv[1:-1]) if len(sys.argv) > 2 else None
            else:
                question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None

            if selected_idx is None:
                print()
                raw_input = input("请选择序号 [0]: ").strip()
                selected_idx = int(raw_input) if raw_input else 0

            if selected_idx < 0 or selected_idx >= len(chats):
                cprint(Colors.RED, "无效的序号")
                sys.exit(1)

            chat_id = chats[selected_idx]["id"]
            chat_name = chats[selected_idx]["name"]
            cprint(Colors.GREEN, f"✓ 已选择: {chat_name}")

            if not question:
                question = input("请输入问题: ").strip()

            if not question:
                cprint(Colors.RED, "问题不能为空")
                sys.exit(1)

            test_chat_completions(question, chat_id)

        except KeyboardInterrupt:
            print()
            sys.exit(0)
        except Exception as e:
            cprint(Colors.RED, f"初始化失败: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
