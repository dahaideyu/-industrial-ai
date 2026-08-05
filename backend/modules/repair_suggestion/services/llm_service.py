# cython: annotation_typing=False, infer_types=False, language_level=3
import logging
import httpx
from typing import Optional, Tuple
try:
    from ..config import Config
except ImportError:
    # 兼容该服务以独立脚本方式启动。
    from config import Config

logger = logging.getLogger(__name__)


class LLMService:
    """根据当前 PROVIDER 调用 OpenAI 兼容模型的通用服务。"""

    def __init__(self) -> None:
        """从统一配置中加载当前供应商的连接参数。"""
        self.provider = Config.LLM_PROVIDER
        self.base_url = Config.LLM_BASE_URL.rstrip("/")
        self.api_key = Config.LLM_API_KEY
        self.model = Config.LLM_MODEL
        self.timeout = 120.0

    def _get_headers(self) -> dict[str, str]:
        """构造 OpenAI 兼容接口请求头。

        Returns:
            包含认证信息和内容类型的请求头。
        """
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(self, system_prompt: str, user_prompt: str) -> Tuple[Optional[str], Optional[str]]:
        """调用当前配置的 LLM，返回内容与错误信息。"""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "temperature": 0.2,
        }
        logger.info("[LLM] 调用模型 - provider=%s, model=%s", self.provider, self.model)
        logger.debug("[LLM] System Prompt: %s", system_prompt)
        logger.debug("[LLM] User Prompt: %s", user_prompt)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=self._get_headers(), json=payload)
                logger.info(
                    "[LLM] 响应 - provider=%s, model=%s, status=%s",
                    self.provider,
                    self.model,
                    response.status_code,
                )
                if response.status_code == 200:
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    logger.debug("[LLM] 输出内容: %s", content)
                    return content, None
                else:
                    err_msg = f"LLM调用失败: {response.status_code} - {response.text}"
                    logger.error(
                        "[LLM] provider=%s, model=%s, error=%s",
                        self.provider,
                        self.model,
                        err_msg,
                    )
                    return None, err_msg
        except Exception as e:
            err_msg = f"LLM调用异常: {str(e)}"
            logger.exception(
                "[LLM] provider=%s, model=%s, error=%s",
                self.provider,
                self.model,
                err_msg,
            )
            return None, err_msg

    async def generate_repair_suggestion(
        self,
        device_name: str,
        fault_description: str,
        history_content: Optional[str] = None,
        doc_content: Optional[str] = None,
        device_type: str = "",
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """生成维修建议，返回 (conclusion, context, error_message)"""
        logger.info("[LLM] 生成维修建议 - device=%s, device_type=%s", device_name, device_type)
        logger.debug("[LLM] 故障描述: %s", fault_description)
        logger.debug("[LLM] 有历史维修单: %s", bool(history_content and history_content.strip()))
        logger.debug("[LLM] 有文档内容: %s", bool(doc_content and doc_content.strip()))

        has_history = bool(history_content and history_content.strip())
        has_doc = bool(doc_content and doc_content.strip())
        has_knowledge = has_history or has_doc

        # 第一步：生成 conclusion（总结）
        logger.info("[LLM] 第一步：生成故障处理总结")
        if has_knowledge:
            conclusion_system_prompt = """
你是一位专业的设备维修专家。请根据提供的信息，生成一段150-200字的故障处理总结。

总结应包括：
1. 简要分析故障可能原因
2. 指出关键处理要点
3. 给出整体处理建议

请直接输出总结内容，不要包含其他多余内容，控制在150-200字之间。
"""
        else:
            conclusion_system_prompt = """
你是一位专业的设备维修专家。知识库中没有找到相关内容，请根据你的专业知识生成一段150-200字的故障处理总结。

总结应包括：
1. 简要分析该类设备常见故障原因
2. 指出关键处理要点
3. 给出整体处理建议

请直接输出总结内容，不要包含其他多余内容，控制在150-200字之间。"""

        conclusion_user_parts = [f"设备型号：{device_name}"]
        if device_type:
            conclusion_user_parts.append(f"设备类型：{device_type}")
        conclusion_user_parts.append(f"故障现象：{fault_description}")
        if has_history:
            conclusion_user_parts.append(f"\n【历史维修单参考】\n{history_content}")
        if has_doc:
            conclusion_user_parts.append(f"\n【设备文档参考】\n{doc_content}")
        conclusion_user_prompt = "\n".join(conclusion_user_parts)

        conclusion, conclusion_err = await self.chat(conclusion_system_prompt, conclusion_user_prompt)
        if conclusion_err:
            return None, None, conclusion_err

        # 第二步：生成 context（详细维修建议）
        logger.info("[LLM] 第二步：生成详细维修建议")
        if has_knowledge:
            context_system_prompt = """
你是一位专业的设备维修专家。请根据提供的历史维修单和设备文档，为用户提供全面、专业的维修建议。

请直接输出维修建议，不要包含其他多余的内容。

维修建议应该包括：
1. 故障分析（
    历史维修单（标题加粗）：必须先说明历史维修单中是否有类似故障，若有提供工单编号并阐述之前的问题原因和处理方式；
    设备文档（标题加粗）：再说明设备文档中是否有类似的故障，并仔细核对提供的文档信息是否属于该设备,若有的话提供文档来源及相关信息
    ）
2. 排查步骤
3. 解决方案
4. 注意事项

每项标题必须加粗，请使用中文回答。
"""

            context_user_parts = [f"设备型号：{device_name}"]
            if device_type:
                context_user_parts.append(f"设备类型：{device_type}")
            context_user_parts.append(f"故障现象：{fault_description}")
            if has_history:
                context_user_parts.append(f"\n【历史维修单参考】\n{history_content}")
            if has_doc:
                context_user_parts.append(f"\n【设备文档参考】\n{doc_content}")
            context_user_prompt = "\n".join(context_user_parts)
        else:
            context_system_prompt = """
你是一位专业的设备维修专家。知识库中没有找到相关内容，请根据你的专业知识提供该类型设备的通用维修建议。

请直接输出维修建议，不要包含其他多余的内容。

输出格式要求：
首先说明"知识库中未检索到相关内容，以下是行业通用维修建议："
然后提供：
1. 常见故障原因分析
2. 通用排查步骤
3. 通用解决方案
4. 安全注意事项

每项标题必须加粗，请使用中文回答。"""
            context_user_prompt = f"设备型号：{device_name}"
            if device_type:
                context_user_prompt += f"\n设备类型：{device_type}"
            context_user_prompt += f"\n故障现象：{fault_description}"

        context, context_err = await self.chat(context_system_prompt, context_user_prompt)
        if context_err:
            return None, None, context_err

        return conclusion, context, None

    async def detect_spare_replacement(self, handle_action: str) -> Tuple[bool, Optional[str]]:
        """
        从处理措施文本中检测是否实际更换了备件
        返回 (has_replacement, error_message)
        """
        logger.info("[LLM] 检测备件更换情况")
        logger.debug("[LLM] 处理措施: %s", handle_action)
        system_prompt = """你是一位维修单审核专家。请根据处理措施的内容，判断该维修单中是否实际更换了备件。

判断标准：
- 如果处理措施中明确提到更换了某个部件、备件、零件、配件等，则判定为"已更换备件"
- 如果只是提到检查、调试、清理、修复、重新连接等操作，未明确提到更换，则判定为"未更换备件"
- 模糊描述如"已处理"、"已修复"等，也判定为"未更换备件"

请以JSON格式返回，格式如下：
{"has_replacement": true, "detail": "更换了XX部件"}
或
{"has_replacement": false, "detail": "未明确提及更换备件"}

只返回JSON，不要其他文字。"""

        user_prompt = f"处理措施：{handle_action}"

        content, err = await self.chat(system_prompt, user_prompt)
        if err:
            return False, err

        try:
            import json
            result = json.loads(content.strip())
            has_replacement = bool(result.get("has_replacement", False))
            detail = result.get("detail", "")
            logger.info(
                "[LLM] 备件检测结果 - has_replacement=%s, detail=%s",
                has_replacement,
                detail,
            )
            return has_replacement, None
        except Exception:
            return False, None

    async def generate_task_suggestion(
        self,
        procedure: str,
        task_type: str,
        task_description: str,
        doc_content: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """生成精益改善任务建议，返回 (conclusion, context, error_message)"""
        logger.info("[LLM] 生成任务建议 - procedure=%s, task_type=%s", procedure, task_type)
        logger.debug("[LLM] 任务描述: %s", task_description)
        logger.debug("[LLM] 有文档内容: %s", bool(doc_content and doc_content.strip()))

        has_doc = bool(doc_content and doc_content.strip())

        # 第一步：生成 conclusion（总结）
        logger.info("[LLM] 第一步：生成任务建议总结")
        if has_doc:
            conclusion_system_prompt = """你是一位精益生产管理专家。请根据提供的知识库内容和任务信息，生成一段150-200字的任务改善建议总结。

总结应包括：
1. 对该任务问题的简要分析
2. 关键改善要点
3. 整体改善方向和建议

请直接输出总结内容，不要包含其他多余内容，控制在150-200字之间。"""
        else:
            conclusion_system_prompt = """你是一位精益生产管理专家。知识库中没有找到相关内容，请根据你的专业知识生成一段150-200字的任务改善建议总结。

总结应包括：
1. 对该任务问题的简要分析
2. 关键改善要点
3. 整体改善方向和建议

请直接输出总结内容，不要包含其他多余内容，控制在150-200字之间。"""

        conclusion_user_parts = [
            f"工序：{procedure}",
            f"任务分类：{task_type}",
            f"任务描述：{task_description}",
        ]
        if has_doc:
            conclusion_user_parts.append(f"\n【知识库参考】\n{doc_content}")
        conclusion_user_prompt = "\n".join(conclusion_user_parts)

        conclusion, conclusion_err = await self.chat(conclusion_system_prompt, conclusion_user_prompt)
        if conclusion_err:
            return None, None, conclusion_err

        # 第二步：生成 context（详细建议）
        logger.info("[LLM] 第二步：生成详细任务改善建议")
        if has_doc:
            context_system_prompt = """你是一位精益生产管理专家。请根据提供的知识库内容，为用户提供全面、专业的精益改善建议。

请直接输出改善建议，不要包含其他多余的内容。

改善建议应该包括：
1. 问题分析（标题加粗）：先说明知识库中是否有相关的处理经验，然后分析该任务反映出的生产管理问题，从精益生产角度剖析根本原因
2. 改善措施（标题加粗）：提出具体可操作的改善方案，包括短期对策和长期预防措施
3. 预期效果（标题加粗）：说明实施改善措施后预期能达到的效果
4. 注意事项（标题加粗）：实施过程中需要注意的风险点和关键控制点

每项标题必须加粗，请使用中文回答。"""

            context_user_parts = [
                f"工序：{procedure}",
                f"任务分类：{task_type}",
                f"任务描述：{task_description}",
                f"\n【知识库参考】\n{doc_content}",
            ]
            context_user_prompt = "\n".join(context_user_parts)
        else:
            context_system_prompt = """你是一位精益生产管理专家。知识库中没有找到相关内容，请根据你的专业知识提供该类型任务的通用改善建议。

请直接输出改善建议，不要包含其他多余的内容。

输出格式要求：
首先说明"知识库中未检索到相关内容，以下是行业通用改善建议："
然后提供：
1. 问题分析（标题加粗）：从精益生产角度分析可能的原因
2. 改善措施（标题加粗）：提出通用的改善方案
3. 预期效果（标题加粗）：实施后的预期效果
4. 注意事项（标题加粗）：实施中的风险点和关键控制点

每项标题必须加粗，请使用中文回答。"""
            context_user_prompt = f"工序：{procedure}\n任务分类：{task_type}\n任务描述：{task_description}"

        context, context_err = await self.chat(context_system_prompt, context_user_prompt)
        if context_err:
            return None, None, context_err

        return conclusion, context, None

    async def score_task_quality(
        self,
        task_description: str,
        handle_action: str,
    ) -> Tuple[float, str, Optional[str]]:
        """
        对精益改善任务描述和处理措施进行质量评分
        返回 (score, reason, error_message)
        score范围: 1-3星，支持0.5分步进
        """
        logger.info("[LLM] 任务质量评分")
        logger.debug("[LLM] 任务描述: %s", task_description)
        logger.debug("[LLM] 处理措施: %s", handle_action)

        system_prompt = """你是一位精益生产管理评审专家。请对以下精益改善任务进行质量评分。

评分标准（满分3星，最低1星，支持0.5分步进）：

任务描述评分维度（占40%权重）：
- 优秀：问题描述清晰，包含具体数据/指标，明确了问题发生的工序和影响范围
- 良好：问题描述较清晰，有基本的问题定位，但缺乏量化数据
- 一般：问题描述模糊，仅简单提及问题现象
- 较差：几乎没有有效描述

处理措施评分维度（占60%权重）：
- 优秀：处理措施详细具体，逻辑自洽，针对问题根因，包含预防性措施
- 良好：处理措施合理，与问题描述匹配，但不够详细
- 一般：处理措施简单笼统，缺乏具体步骤
- 较差：几乎没有有效内容或与问题描述不相关

特别关注"自洽性"：处理措施是否真正针对任务描述中的问题，是否存在逻辑矛盾。

请以JSON格式返回，格式如下：
{
    "score": 2.5,
    "reason": "评分原因的详细说明，分别评价任务描述和处理措施，并说明自洽性判断"
}
只返回JSON，不要其他文字。"""

        user_prompt = """任务描述：{}
处理措施：{}""".format(task_description, handle_action)

        content, err = await self.chat(system_prompt, user_prompt)
        if err:
            return 1.5, "AI评分服务暂时不可用，按基础分计算", err

        try:
            import json
            result = json.loads(content.strip())
            score = float(result.get("score", 1.5))
            reason = result.get("reason", "AI质量评分完成")
            score = max(1.0, min(3.0, score))
            return score, reason, None
        except Exception:
            return 1.5, "AI质量评分完成", None

    async def score_content_quality(
        self,
        handle_analysis: str,
        handle_action: str,
        is_replace_spare: bool,
    ) -> Tuple[Optional[float], Optional[str], Optional[str]]:
        """
        对根因分析和处理措施进行质量评分
        返回 (score, reason, error_message)
        score范围: 非更换备件1-3星，更换备件1-2星，支持0.5分步进
        """
        logger.info("[LLM] 内容质量评分 - is_replace_spare=%s", is_replace_spare)
        logger.debug("[LLM] 根因分析: %s", handle_analysis)
        logger.debug("[LLM] 处理措施: %s", handle_action)
        max_score = 2.0 if is_replace_spare else 3.0
        system_prompt = """你是一位维修单质量评审专家。请对以下维修单内容进行质量评分。

评分标准：
- 满分：{}星，最低1星，支持0.5分步进（如1.5、2.5等）

根因分析评分维度（占一半权重）：
- 优秀：详细描述了故障来源、排查过程、定位方法等
- 良好：描述了故障原因，但不够详细
- 一般：只简单提到了故障，缺乏细节
- 较差：几乎没有有效内容

处理措施评分维度（占一半权重）：
- 优秀：详细描述了解决步骤，或带有预防措施
- 良好：描述了处理方法，但不够详细
- 一般：只简单说"已处理"，缺乏细节
- 较差：几乎没有有效内容

请以JSON格式返回，格式如下：
{{"score": 分数, "reason": "评分理由"}}
只返回JSON，不要其他文字。""".format(max_score)

        user_prompt = """根因分析：{}
处理措施：{}
是否更换备件：{}""".format(handle_analysis, handle_action, '是' if is_replace_spare else '否')

        content, err = await self.chat(system_prompt, user_prompt)
        if err:
            return None, None, err

        try:
            import json
            result = json.loads(content.strip())
            score = float(result.get("score", max_score / 2))
            reason = result.get("reason", "AI质量评分完成")
            score = max(1.0, min(max_score, score))
            return score, reason, None
        except Exception:
            return max_score / 2, "AI质量评分完成", None


# 兼容旧调用方；新代码统一导入 LLMService。
DeepSeekService = LLMService
