# cython: annotation_typing=False, infer_types=False, language_level=3
import json
import os
import time
import asyncio
import threading
import queue as threading_queue

import httpx
from core.config import CONFIG, get_llm_client
from modules.daily_report.prompts import get_prompt_template, list_available_templates
from backend.utils.data_cleaner import clean_raw_data, EXCLUDED_SOURCE_KEYS


def is_ollama() -> bool:
    """判断是否为 Ollama 模型"""
    return "ollama" in CONFIG.get("provider", "").lower() or "11434" in CONFIG.get("base_url", "") or os.getenv("OLLAMA_NATIVE_API", "").lower() == "true"


def build_prompt(payload: dict) -> tuple[str, str]:
    """根据 payload 构建提示词"""
    report_code = payload.get("reportCode")
    # 过滤掉 reportCode/report_code 和 None 值，只保留有效业务数据
    data_sources = {k: v for k, v in payload.items() if k not in ("reportCode", "report_code") and v is not None}

    print(f"[调试] 报告类型 (reportCode): {report_code}")
    prompt_template = get_prompt_template(report_code)
    if not prompt_template:
        available = list(list_available_templates().keys())
        error_msg = f"不支持的报告类型: {report_code}，可用类型: {available}"
        print(f"[错误] {error_msg}")
        raise ValueError(error_msg)
    print(f"[调试] 提示词模板加载成功，长度: {len(prompt_template)} 字符")

    print(f"[调试] 数据源 keys: {list(data_sources.keys())}")
    if not data_sources:
        print(f"[警告] 数据源为空！请检查请求 body 是否包含 'data' 字段")

    # 如果数据在 'data' 子键下且不为空，自动提取（避免嵌套）
    actual_data = data_sources
    if "data" in data_sources and data_sources["data"] is not None and isinstance(data_sources["data"], dict) and data_sources["data"]:
        print(f"[调试] 检测到 'data' 嵌套，自动提取，内部 keys: {list(data_sources['data'].keys())}")
        actual_data = data_sources["data"]

    # ========================================
    # 预处理：清洗原数据（去空字段、过滤 sourceKey、剥离 HTTP 包装）
    # ========================================
    raw_json_before = json.dumps(actual_data, ensure_ascii=False, separators=(',', ':'))
    response_list = actual_data.get("response", []) if isinstance(actual_data, dict) else []
    source_keys_before = [
        item.get("sourceKey") for item in response_list
        if isinstance(item, dict) and "sourceKey" in item
    ]
    excluded_in_data = [sk for sk in source_keys_before if sk in EXCLUDED_SOURCE_KEYS]

    cleaned_data = clean_raw_data(actual_data)
    after_clean = len(json.dumps(cleaned_data, ensure_ascii=False, separators=(',', ':')))

    # 数据预处理：对配置了预处理器的 sourceKey 执行 map-reduce 变换（聚合统计 + 压缩上下文）
    response_list = cleaned_data.get("response", [])
    if isinstance(response_list, list):
        from backend.utils.data_preprocessor import preprocess_sources
        preprocess_sources(response_list)
        prepped_names = [
            item.get("sourceKey", "?") for item in response_list
            if isinstance(item, dict) and isinstance(item.get("data"), dict)
            and item["data"].get("_preprocessed")
        ]
        preprocessed_count = len(prepped_names)

    data_sources_json = json.dumps(cleaned_data, ensure_ascii=False, separators=(',', ':'))
    after_reduce = len(data_sources_json)

    source_keys_after = [
        item.get("sourceKey") for item in cleaned_data.get("response", [])
        if isinstance(item, dict) and "sourceKey" in item
    ] if isinstance(cleaned_data, dict) else []
    reduction_pct = (1 - after_reduce / len(raw_json_before)) * 100 if raw_json_before else 0

    print(f"\n[预处理] 原始={len(raw_json_before)} → 清洗后={after_clean}(-空值&过滤sourceKey) → reduce后={after_reduce} 字符 (总缩减 {reduction_pct:.1f}%)")
    print(f"[预处理] sourceKey: {len(source_keys_before)} → {len(source_keys_after)} 个, map-reduce: {preprocessed_count} 个 ({', '.join(prepped_names) if prepped_names else '无'})")
    if excluded_in_data:
        print(f"[预处理] 已过滤 sourceKey: {excluded_in_data}")
    print(f"[预处理] ====================================\n")

    prompt = prompt_template.replace("{temporary_rules}", "").replace("{data_sources}", data_sources_json)
    print(f"[调试] 提示词构建完成，长度: {len(prompt)} 字符，数据长度: {len(data_sources_json)} 字符")
    print(f"\n{'='*60}\n[完整提示词] (前500字符):\n{prompt[:500]}\n...")
    print(f"[完整提示词] (后500字符):\n...\n{prompt[-500:]}\n{'='*60}")
    return prompt, report_code


def get_llm():
    """获取 LLM 实例（OpenAI 兼容接口）"""
    print(f"[调试] 初始化 LLM... 供应商: {CONFIG['provider']} 模型: {CONFIG['model']}")
    return get_llm_client(timeout=600.0)


def ollama_stream(prompt: str, model: str, base_url: str):
    """使用 Ollama 原生 API /api/chat 进行流式调用"""
    # 去掉 /v1 后缀，Ollama 原生 API 不需要 /v1 前缀
    clean_url = base_url.rstrip("/")
    if clean_url.endswith("/v1"):
        clean_url = clean_url[:-3]
    url = f"{clean_url}/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "think": True,
        "options": {
            "temperature": 0.2
        }
    }
    print(f"[调试] Ollama 原生 API 调用: {url}")
    print(f"[调试] Ollama 参数: temperature=0.2, num_ctx=65536, num_predict=8192")

    with httpx.Client(timeout=600.0) as client:
        with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            yield data["message"]["content"]
                        if data.get("done", False):
                            break
                    except json.JSONDecodeError:
                        print(f"[警告] Ollama 返回非 JSON 行: {line[:100]}")


async def generate_report_stream(payload: dict):
    """
    流式生成 AI 报告，返回异步生成器（SSE 格式）
    """
    print(f"\n{'='*60}")
    print(f"[调试] 开始流式生成 AI 报告")
    print(f"{'='*60}")

    start_time = time.time()

    yield f"event: start\ndata: {{\"code\": 200, \"msg\": \"ok\"}}\n\n".encode('utf-8')

    for i in range(2):
        yield ": heartbeat\n\n".encode('utf-8')
        await asyncio.sleep(0.05)

    prompt, report_code = build_prompt(payload)
    llm = get_llm()

    print(f"[调试] 正在调用 LLM (流式)...")
    first_chunk = True

    content_queue = threading_queue.Queue()
    done_event = threading.Event()

    def llm_worker():
        try:
            full_content = ""

            if is_ollama():
                # Ollama 原生 API /api/chat
                for content in ollama_stream(prompt, CONFIG["model"], CONFIG["base_url"]):
                    full_content += content
                    content_queue.put(('content', content))
            else:
                # OpenAI 兼容接口
                for chunk in llm.chat.completions.create(
                    model=CONFIG["model"],
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    stream=True,
                    extra_body={"thinking": {"type": "disabled"}}
                ):
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_content += content
                        content_queue.put(('content', content))

            content_queue.put(('done', full_content))
        except Exception as e:
            import traceback
            traceback.print_exc()
            content_queue.put(('error', str(e)))
        finally:
            done_event.set()

    worker_thread = threading.Thread(target=llm_worker, daemon=True)
    worker_thread.start()

    full_content = ""
    last_activity_time = time.time()

    try:
        while not done_event.is_set() or not content_queue.empty():
            try:
                msg_type, msg_data = await asyncio.to_thread(content_queue.get, timeout=1.5)
            except threading_queue.Empty:
                current_time = time.time()
                if current_time - last_activity_time > 1.0:
                    yield ": heartbeat\n\n".encode('utf-8')
                    last_activity_time = current_time
                continue

            if msg_type == 'content':
                chunk_content = msg_data
                if first_chunk:
                    first_chunk_time = time.time() - start_time
                    print(f"[调试] 首字耗时: {first_chunk_time:.2f} 秒")
                    first_chunk = False
                print(chunk_content, end='', flush=True)
                full_content += chunk_content
                last_activity_time = time.time()

                lines = chunk_content.split('\n')
                for line in lines:
                    yield f"data: {line}\n".encode('utf-8')
                yield "\n".encode('utf-8')

            elif msg_type == 'done':
                full_content = msg_data
                break

            elif msg_type == 'error':
                raise Exception(msg_data)

        elapsed_time = time.time() - start_time
        print(f"\n[调试] 流式输出完成 总耗时: {elapsed_time:.2f} 秒 长度: {len(full_content)} 字符")
        print(f"{'='*60}\n")

        yield f"event: end\ndata: {json.dumps({'data': full_content, 'totalTime': elapsed_time}, ensure_ascii=False)}\n\n".encode('utf-8')

    except Exception as e:
        elapsed_time = time.time() - start_time
        print(f"\n[错误] LLM 流式调用失败: {e}")
        import traceback
        traceback.print_exc()
        error_msg = str(e)
        yield f"event: error\ndata: {json.dumps({'code': 500, 'msg': f'生成报告失败: {error_msg}'}, ensure_ascii=False)}\n\n".encode('utf-8')
    finally:
        done_event.set()
        worker_thread.join(timeout=1.0)
