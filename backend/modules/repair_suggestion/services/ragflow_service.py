# cython: annotation_typing=False, infer_types=False, language_level=3
import logging
import httpx
import json
from typing import Optional, Tuple
try:
    from ..config import Config
except ImportError:
    # 兼容该服务以独立脚本方式启动。
    from config import Config

logger = logging.getLogger(__name__)


class RAGFlowService:
    def __init__(self):
        self.base_url = Config.RAGFLOW_BASE_URL.rstrip("/")
        self.api_key = Config.RAGFLOW_API_KEY
        self.timeout = 120.0

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(self, chat_id: str, message: str, llm_id: str = "deepseek-v4-flash") -> Tuple[Optional[str], Optional[str]]:
        """对话（流式），返回（answer, error_message）"""
        url = f"{self.base_url}/api/v1/chat/completions"
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": message
                }
            ],
            "stream": True,
            "chat_id": chat_id,
            "llm_id": llm_id
        }
        logger.info(f"[RAGFlow] 发送消息 - chat_id: {chat_id}")
        logger.debug(f"[RAGFlow] 输入消息: {message}")
        try:
            final_answer = ""
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, headers=self._get_headers(), json=payload) as response:
                    logger.info(f"[RAGFlow] 对话响应 - status: {response.status_code}")
                    if response.status_code != 200:
                        err_msg = f"对话失败: {response.status_code}"
                        logger.error(f"[RAGFlow] {err_msg}")
                        return None, err_msg

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        # 去掉data:前缀
                        json_str = line
                        if line.startswith("data: "):
                            json_str = line[6:]
                        elif line.startswith("data:"):
                            json_str = line[5:]
                        try:
                            data = json.loads(json_str)
                            # 检查是否是结束标记
                            if isinstance(data.get("data"), bool) and data.get("data") is True:
                                logger.debug(f"[RAGFlow] 收到结束标记")
                                break
                            # 获取answer内容
                            answer_data = data.get("data", {})
                            if isinstance(answer_data, dict):
                                answer = answer_data.get("answer", "")
                                # 如果是final块，用这个完整的answer
                                if answer_data.get("final"):
                                    logger.debug(f"[RAGFlow] 收到final数据")
                                    final_answer = answer
                                    break
                        except json.JSONDecodeError as e:
                            logger.debug(f"[RAGFlow] JSON解析失败: {e}, line: {line}")
                            continue

            # 过滤掉思考内容
            final_answer = self._extract_non_thinking_content(final_answer)
            return final_answer, None

        except Exception as e:
            err_msg = f"对话异常: {str(e)}"
            logger.exception(f"[RAGFlow] {err_msg}")
            return None, err_msg

    def _extract_non_thinking_content(self, answer: str) -> str:
        """提取非思考内容，去掉思考块"""
        if not answer:
            return ""
        if "<think>" in answer and "</think>" in answer:
            think_start = answer.find("<think>")
            think_end = answer.find("</think>") + len("</think>")
            return (answer[:think_start] + answer[think_end:]).strip()
        return answer.strip()

    async def delete_all_sessions(self, chat_id: str) -> Tuple[bool, Optional[str]]:
        """删除聊天助手所有会话，返回（success, error_message）"""
        url = f"{self.base_url}/api/v1/chats/{chat_id}/sessions"
        logger.info(f"[RAGFlow] 删除所有会话 - chat_id: {chat_id}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.delete(url, headers=self._get_headers())
                logger.info(f"[RAGFlow] 删除会话响应 - status: {response.status_code}")
                if response.status_code == 200:
                    logger.info(f"[RAGFlow] 会话删除成功")
                    return True, None
                else:
                    err_msg = f"删除会话失败: {response.status_code} - {response.text}"
                    logger.error(f"[RAGFlow] {err_msg}")
                    return False, err_msg
        except Exception as e:
            err_msg = f"删除会话异常: {str(e)}"
            logger.exception(f"[RAGFlow] {err_msg}")
            return False, err_msg

    async def query_history_repair_orders(self, device_name: str, device_type: str, fault_description: str) -> Tuple[Optional[str], Optional[str]]:
        """查询历史维修单知识库"""
        chat_id = Config.RAGFLOW_HISTORY_ASSISTANT_ID
        type_hint = f"，设备类型：{device_type}" if device_type else ""
        message = f"设备：{device_name}{type_hint}，故障：{fault_description}，请检查是否有历史出现过的故障记录，若有的话提供根因分析及处理措施，并提供工单编号"
        logger.info(f"[RAGFlow] 查询历史维修单")
        return await self.chat(chat_id, message)

    async def query_device_docs(self, device_name: str, device_type: str, fault_description: str) -> Tuple[Optional[str], Optional[str]]:
        """查询设备文档知识库"""
        chat_id = Config.RAGFLOW_DOC_ASSISTANT_ID
        type_hint = f"，设备类型：{device_type}" if device_type else ""
        message = f"设备型号：{device_name}{type_hint}，故障现象：{fault_description}，请查询相关的设备文档和维修资料，若有类似故障现象请提供可能的问题原因及处理措施，并标注来源文档的名称，注意不要混淆设备类型，不属于该设备的文档不可做参考"
        logger.info(f"[RAGFlow] 查询设备文档")
        return await self.chat(chat_id, message)

    async def query_task_knowledge(self, procedure: str, task_type: str, task_description: str) -> Tuple[Optional[str], Optional[str]]:
        """查询精益改善任务相关知识"""
        chat_id = Config.RAGFLOW_DOC_ASSISTANT_ID
        message = f"工序：{procedure}，任务分类：{task_type}，任务描述：{task_description}，请查询相关的设备文档和改善资料，若有类似问题的处理经验请提供参考，并标注来源文档的名称"
        logger.info(f"[RAGFlow] 查询任务知识库")
        return await self.chat(chat_id, message)
