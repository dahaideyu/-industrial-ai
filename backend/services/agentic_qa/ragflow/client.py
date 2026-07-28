# cython: annotation_typing=False, infer_types=False, language_level=3
"""RAGFlow 客户端 — 流式 SSE 实现

RAGFlow 目前只能通过流式输出来获取完整回答和引用信息。
非流式返回的 answer 可能为空且不含 reference。
"""

import json
import os
import httpx
from typing import Optional, Dict, Any, Tuple, Callable, List
from backend.core.agentic_qa.config import settings
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("ragflow.client")

# RAGFlow Chat Assistant 使用的 LLM ID（需与 RAGFlow 服务端注册的模型名一致）
# 可通过环境变量 RAGFLOW_LLM_ID 或 RAGFLOW_MODEL 指定；都不设则为 None（RAGFlow 使用默认模型）
_RAGFLOW_LLM_ID = os.getenv("RAGFLOW_LLM_ID") or os.getenv("RAGFLOW_MODEL") or None


def _parse_sse_events(raw_chunks):
    """从原始字节流中解析 SSE 事件，解决 audio_binary 导致 JSON 跨行的问题。

    RAGFlow 的流式响应包含 audio_binary (TTS 语音数据)，其 base64 内容可能包含
    换行符，导致 iter_lines() 把 JSON 切成碎片。正确的 SSE 协议使用 \\n\\n 分隔
    事件，一个事件内的多个 data: 行应拼接后再解析。

    这是一个生成器，每次 yield 一个解析好的 JSON dict。
    """
    buffer = ""
    for chunk in raw_chunks:
        buffer += chunk.decode("utf-8", errors="replace")

        # SSE 事件以 \\n\\n 分隔
        while "\n\n" in buffer:
            idx = buffer.index("\n\n")
            event_text = buffer[:idx]
            buffer = buffer[idx + 2:]

            data_parts = _extract_data_parts(event_text)
            if not data_parts:
                continue

            full_json = "".join(data_parts)
            parsed = _try_parse_json(full_json)
            if parsed is not None:
                yield parsed

    # 流结束后处理 buffer 中残留的不完整数据（RAGFlow 连接关闭时最后一个事件可能不以 \\n\\n 结尾）
    if buffer.strip():
        data_parts = _extract_data_parts(buffer)
        if data_parts:
            full_json = "".join(data_parts)
            parsed = _try_parse_json(full_json)
            if parsed is not None:
                yield parsed


def _extract_data_parts(event_text: str):
    """从 SSE 事件文本中提取所有 data: 行的 JSON 内容。"""
    data_parts = []
    for line in event_text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            data_parts.append(line[6:])
        elif line.startswith("data:"):
            data_parts.append(line[5:])
    return data_parts


def _try_parse_json(full_json: str):
    """尝试解析 JSON，失败时记录日志并返回 None。"""
    try:
        return json.loads(full_json)
    except json.JSONDecodeError:
        logger.debug(f"SSE JSON parse failed: {full_json[:80]}...")
        return None


async def _parse_sse_events_async(raw_chunks):
    """异步版 SSE 事件解析，用于 async chat() 方法。"""
    buffer = ""
    async for chunk in raw_chunks:
        buffer += chunk.decode("utf-8", errors="replace")

        while "\n\n" in buffer:
            idx = buffer.index("\n\n")
            event_text = buffer[:idx]
            buffer = buffer[idx + 2:]

            data_parts = _extract_data_parts(event_text)
            if not data_parts:
                continue

            full_json = "".join(data_parts)
            parsed = _try_parse_json(full_json)
            if parsed is not None:
                yield parsed

    # 流结束后处理 buffer 中残留的不完整数据
    if buffer.strip():
        data_parts = _extract_data_parts(buffer)
        if data_parts:
            full_json = "".join(data_parts)
            parsed = _try_parse_json(full_json)
            if parsed is not None:
                yield parsed


# 常见 LLM 思维输出前缀（部分模型不用 <think> 标签，直接在正文前输出推理过程）
_THINKING_PREFIXES = [
    "好的，用户的问题",
    "好的，用户询问",
    "好的，我来分析",
    "好的，让我来",
    "让我来分析",
    "让我梳理一下",
    "首先，我需要理解",
    "根据用户的问题，我需要",
]

# 思维链 → 正式回答的过渡标记
_ANSWER_TRANSITIONS = [
    "根据提供的知识库",
    "根据知识库内容",
    "根据知识库，",
    "根据检索到的信息",
    "以下是",
    "回答如下",
    "总结如下",
]


def _split_thinking(answer: str) -> Tuple[str, str]:
    """分离思考内容和正文，返回 (thinking, body)。

    策略：
    1. 优先检测显式 <think>...</think> 标签（Qwen 等模型的格式）
    2. 无标签时检测常见 LLM 思维前缀 + 过渡标记模式（DeepSeek 等模型的格式）
    """
    if not answer:
        return "", ""

    # ---- 策略 1：显式 <think> 标签 ----
    if "<think>" in answer and "</think>" in answer:
        ts = answer.find("<think>")
        te = answer.find("</think>") + len("</think>")
        thinking = answer[ts + len("<think>"):te - len("</think>")].strip()
        body = (answer[:ts] + answer[te:]).strip()
        return thinking, body

    # ---- 策略 2：检测无标签的思维前缀 ----
    stripped = answer.lstrip()
    for prefix in _THINKING_PREFIXES:
        if stripped.startswith(prefix):
            # 查找第一个过渡标记的位置
            earliest_idx = len(answer)
            for trans in _ANSWER_TRANSITIONS:
                idx = answer.find(trans)
                if idx != -1 and idx < earliest_idx:
                    earliest_idx = idx

            if earliest_idx > 0 and earliest_idx < len(answer):
                thinking = answer[:earliest_idx].strip()
                body = answer[earliest_idx:].strip()
                return thinking, body

            # 找到思维前缀但没找到过渡标记，保守处理：只去除前缀所在的首行
            first_newline = answer.find("\n")
            if first_newline > 0:
                thinking = answer[:first_newline].strip()
                body = answer[first_newline:].strip()
                return thinking, body
            break  # 只匹配第一个前缀

    return "", answer.strip()


class RAGFlowError(Exception):
    """RAGFlow API 错误。"""
    pass


class RAGFlowReference:
    """RAGFlow 引用信息"""
    def __init__(self, raw: dict):
        self.total = raw.get("total", 0)
        self.chunks: List[dict] = raw.get("chunks", [])
        self.doc_aggs: List[dict] = raw.get("doc_aggs", [])

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "chunks": self.chunks,
            "doc_aggs": self.doc_aggs,
        }


class RAGFlowClient:
    """RAGFlow Chat Assistant 客户端

    API 参考: https://ragflow.io/docs/http_api_reference#converse-with-chat-assistant
    """

    def __init__(self):
        self.base_url = settings.ragflow_api_url.rstrip("/")
        self.api_key = settings.ragflow_api_key
        self.chat_id = settings.ragflow_chat_id
        self.timeout = 120.0

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ============================================================
    # 异步流式对话
    # ============================================================

    async def chat(
        self,
        message: str,
        llm_id: str = _RAGFLOW_LLM_ID,
        chat_id: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> Tuple[Optional[str], Optional[RAGFlowReference], Optional[str]]:
        """异步流式对话，返回 (answer, reference, error_message)"""
        url = f"{self.base_url}/api/v1/chat/completions"
        payload: dict = {
            "messages": [{"role": "user", "content": message}],
            "stream": True,
            "chat_id": chat_id or self.chat_id,
        }
        # llm_id 为 None 时不传，让 RAGFlow 使用默认模型
        if llm_id is not None:
            payload["llm_id"] = llm_id

        logger.info(f"[RAGFlow] async stream: '{message[:60]}'")
        try:
            references = None
            prev_answer = ""
            in_thinking = False

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", url, headers=self._get_headers(), json=payload
                ) as response:
                    logger.info(f"[RAGFlow] status: {response.status_code}")
                    if response.status_code != 200:
                        err = f"HTTP {response.status_code}"
                        logger.error(f"[RAGFlow] {err}")
                        return None, None, err

                    data_count = 0
                    async for data in _parse_sse_events_async(response.aiter_raw()):
                        data_count += 1

                        if isinstance(data.get("code"), int) and data.get("code", 0) != 0:
                            err_msg = data.get("message", f"code={data.get('code')}")
                            logger.error(f"[RAGFlow] error: {err_msg}")
                            return None, None, err_msg

                        # 流结束标记：data 字段为 bool（标准 RAGFlow 协议）
                        if isinstance(data.get("data"), bool):
                            break

                        answer_data = data.get("data", {})
                        if not isinstance(answer_data, dict):
                            continue

                        # 追踪思维链状态
                        if answer_data.get("start_to_think"):
                            in_thinking = True
                        if answer_data.get("end_to_think"):
                            in_thinking = False

                        answer = answer_data.get("answer", "")
                        is_final = answer_data.get("final", False)

                        # 增量/累积模式兼容
                        if answer and answer != prev_answer:
                            if answer.startswith(prev_answer):
                                delta = answer[len(prev_answer):]
                            else:
                                delta = answer
                            prev_answer = answer

                            if not in_thinking and not is_final and on_chunk and delta:
                                on_chunk(delta)

                        # 收集 references（可能在任意事件中，不依赖 final 标记）
                        ref_raw = answer_data.get("reference")
                        if ref_raw and isinstance(ref_raw, dict):
                            references = RAGFlowReference(ref_raw)

                        # is_final 兜底
                        if is_final:
                            break

                    final_answer = prev_answer

            thinking, body = _split_thinking(final_answer)
            if thinking:
                logger.debug(f"[RAGFlow] thinking: {len(thinking)} chars")
            logger.info(f"[RAGFlow] answer: {len(body)} chars, refs: {references.total if references else 0}")
            return final_answer, references, None

        except Exception as e:
            err = f"异常: {str(e)}"
            logger.exception(f"[RAGFlow] {err}")
            return None, None, err

    # ============================================================
    # 同步流式对话（供 LangGraph sync 节点使用）
    # ============================================================

    def chat_sync(
        self,
        question: str,
        chat_id: str,
        history_messages: Optional[List[Dict[str, str]]] = None,
        llm_id: str = _RAGFLOW_LLM_ID,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """同步流式对话，支持多轮历史 messages。

        Args:
            question: 当前问题
            chat_id: RAGFlow Chat Assistant ID
            history_messages: 历史问答 [{"role": "user/assistant", "content": "..."}]

        on_chunk: 每收到一个增量文本块时回调 on_chunk(delta_text)
        """
        url = f"{self.base_url}/api/v1/chat/completions"
        messages = list(history_messages or [])
        messages.append({"role": "user", "content": question})
        payload: dict = {
            "messages": messages,
            "stream": True,
            "chat_id": chat_id,
        }
        # llm_id 为 None 时不传，让 RAGFlow 使用默认模型
        if llm_id is not None:
            payload["llm_id"] = llm_id
        # 不传 session_id，让 RAGFlow 根据 chat_id 自动创建
        logger.info(f"[RAGFlow] sync stream: '{question[:60]}' (history={len(history_messages or [])} msgs)")
        try:
            final_answer = ""
            references = None
            prev_answer = ""
            in_thinking = False  # 追踪思维链状态

            with httpx.Client(timeout=self.timeout) as client:
                raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                with client.stream(
                    "POST", url, headers=self._get_headers(), content=raw_body
                ) as response:
                    logger.info(f"[RAGFlow] status: {response.status_code}")
                    if response.status_code != 200:
                        err = f"HTTP {response.status_code}"
                        logger.error(f"[RAGFlow] {err}")
                        return {"success": False, "error": err, "answer": f"RAGFlow 连接失败: {err}"}

                    data_count = 0
                    stream_error = None
                    for data in _parse_sse_events(response.iter_raw()):
                        data_count += 1

                        # 应用层错误
                        if isinstance(data.get("code"), int) and data.get("code", 0) != 0:
                            stream_error = data.get("message", f"code={data.get('code')}")
                            logger.error(f"[RAGFlow] error: {stream_error}")
                            break

                        # 流结束标记：data 字段为 bool（标准 RAGFlow 协议）
                        if isinstance(data.get("data"), bool):
                            break

                        answer_data = data.get("data", {})
                        if not isinstance(answer_data, dict):
                            continue

                        # 追踪思维链状态（RAGFlow 标注的 start_to_think / end_to_think）
                        if answer_data.get("start_to_think"):
                            in_thinking = True
                        if answer_data.get("end_to_think"):
                            in_thinking = False

                        answer = answer_data.get("answer", "")
                        is_final = answer_data.get("final", False)

                        # 增量/累积模式兼容：RAGFlow 不同版本 answer 可能是增量或累积
                        if answer and answer != prev_answer:
                            if answer.startswith(prev_answer):
                                delta = answer[len(prev_answer):]   # 累积模式：diff 取增量
                            else:
                                delta = answer                      # 增量模式：直接使用
                            prev_answer = answer

                            # 思维链期间的文本不推送给前端（思考过程在 done 事件中统一返回）
                            # final 事件含完整累积文本（含 <think>），也不推送，由 _split_thinking 清洗后返回
                            if not in_thinking and not is_final and on_chunk and delta:
                                on_chunk(delta)

                        # 收集 references（可能在任意事件中，不依赖 final 标记）
                        ref_raw = answer_data.get("reference")
                        if ref_raw and isinstance(ref_raw, dict):
                            references = RAGFlowReference(ref_raw)

                        # is_final 兜底：兼容不发 data:bool 事件的 RAGFlow 版本
                        if is_final:
                            break

                    final_answer = prev_answer

                    logger.info(f"[RAGFlow] {data_count} events, {len(final_answer)} chars answer, "
                               f"{references.total if references else 0} refs")

            thinking, body = _split_thinking(final_answer)

            if stream_error:
                logger.error(f"[RAGFlow] stream error: {stream_error}")
                return {
                    "success": False,
                    "error": stream_error,
                    "answer": f"RAGFlow 返回错误: {stream_error}",
                }

            if not body and not thinking:
                logger.warning("[RAGFlow] empty answer from stream")
                return {
                    "success": False,
                    "error": "流式未获取到回答",
                    "answer": "未获取到回答，请确认知识库是否已配置。",
                }

            logger.info(f"[RAGFlow] thinking={len(thinking)} answer={len(body)} refs={references.total if references else 0}")

            return {
                "success": True,
                "answer": body,
                "thinking": thinking,
                "references": references.to_dict() if references else None,
                # 保留原始答案供调试（_split_thinking 处理前的完整文本）
                "raw": {"final_answer": final_answer, "thinking_len": len(thinking)},
            }

        except httpx.HTTPError as e:
            err = f"连接失败: {str(e)}"
            logger.error(f"[RAGFlow] {err}")
            return {"success": False, "error": err, "answer": f"RAGFlow 连接失败: {err}"}
        except Exception as e:
            err = f"异常: {str(e)}"
            logger.exception(f"[RAGFlow] {err}")
            return {"success": False, "error": err, "answer": f"RAGFlow 对话异常: {err}"}

    # ============================================================
    # 文档下载（代理 RAGFlow API）
    # ============================================================

    def download_document(self, dataset_id: str, document_id: str) -> Tuple[Optional[bytes], Optional[str]]:
        """下载文档内容，返回 (content, error)"""
        url = f"{self.base_url}/api/v1/datasets/{dataset_id}/documents/{document_id}"
        logger.info(f"[RAGFlow] download doc: dataset={dataset_id} doc={document_id}")

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, headers=self._get_headers())
                if resp.status_code == 200:
                    return resp.content, None
                err_detail = ""
                try:
                    err_detail = resp.json().get("message", "")
                except Exception:
                    pass
                err = f"下载失败: HTTP {resp.status_code} {err_detail}"
                logger.error(f"[RAGFlow] {err}")
                return None, err
        except httpx.HTTPError as e:
            err = f"下载异常: {str(e)}"
            logger.error(f"[RAGFlow] {err}")
            return None, err

    # ============================================================
    # Chat Assistant 生命周期管理
    # ============================================================

    def _post_json(self, url: str, payload: dict) -> dict:
        """POST JSON 辅助方法。"""
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=self._get_headers(), json=payload)
        try:
            return resp.json()
        except Exception:
            return {"code": resp.status_code, "message": resp.text}

    def _patch_json(self, url: str, payload: dict) -> dict:
        """PATCH JSON 辅助方法。"""
        with httpx.Client(timeout=10.0) as client:
            resp = client.patch(url, headers=self._get_headers(), json=payload)
        try:
            return resp.json()
        except Exception:
            return {"code": resp.status_code, "message": resp.text}

    def _delete_json(self, url: str) -> dict:
        """DELETE 辅助方法。"""
        with httpx.Client(timeout=10.0) as client:
            resp = client.delete(url, headers=self._get_headers())
        try:
            return resp.json()
        except Exception:
            return {"code": resp.status_code, "message": resp.text}

    def list_chats(self, name: Optional[str] = None) -> List[dict]:
        """GET /api/v1/chats 列出 Chat Assistant，可按名字精确过滤。"""
        url = f"{self.base_url}/api/v1/chats"
        logger.info(f"[RAGFlow] list_chats: name={name or '(全部)'}")
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, headers=self._get_headers(), params={"name": name} if name else None)
            data = resp.json()
        except Exception as e:
            logger.warning(f"[RAGFlow] list_chats 失败: {e}")
            return []
        if data.get("code") == 0:
            payload = data.get("data")
            # 兼容不同 RAGFlow 版本的返回结构：data 直接是数组，或嵌套在 data.chats 里
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict) and isinstance(payload.get("chats"), list):
                return payload["chats"]
        return []

    def create_chat(
        self,
        name: str,
        dataset_ids: list = None,
        llm_id: str = _RAGFLOW_LLM_ID,
    ) -> str:
        """POST /api/v1/chats 创建 Chat Assistant，返回 chat_id。"""
        url = f"{self.base_url}/api/v1/chats"
        payload: dict = {
            "name": name,
            "dataset_ids": dataset_ids or [],
        }
        # llm_id 为 None 时不传，让 RAGFlow 使用默认模型
        if llm_id is not None:
            payload["llm_id"] = llm_id
        logger.info(f"[RAGFlow] create_chat: name={name}, llm_id={llm_id or '(默认)'}")
        data = self._post_json(url, payload)
        if data.get("code") == 0 and data.get("data", {}).get("id"):
            return data["data"]["id"]
        raise RAGFlowError(data.get("message", "create_chat failed"))

    def update_chat_datasets(self, chat_id: str, dataset_ids: list) -> bool:
        """PATCH /api/v1/chats/{chat_id} 更新 dataset_ids。"""
        url = f"{self.base_url}/api/v1/chats/{chat_id}"
        payload = {"dataset_ids": dataset_ids}
        logger.info(f"[RAGFlow] update_chat_datasets: chat_id={chat_id}, n={len(dataset_ids)}")
        data = self._patch_json(url, payload)
        return data.get("code") == 0

    def delete_chat(self, chat_id: str) -> bool:
        """DELETE /api/v1/chats/{chat_id} 删除 Chat Assistant。"""
        url = f"{self.base_url}/api/v1/chats/{chat_id}"
        logger.info(f"[RAGFlow] delete_chat: chat_id={chat_id}")
        data = self._delete_json(url)
        return data.get("code") == 0


ragflow_client = RAGFlowClient()
