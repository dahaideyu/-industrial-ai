# cython: annotation_typing=False, infer_types=False, language_level=3
import logging
from datetime import datetime, date
from typing import Tuple
from .llm_service import LLMService

logger = logging.getLogger(__name__)


class ScoringService:
    def __init__(self) -> None:
        """初始化通用 LLM 评分服务。"""
        self.llm_service = LLMService()

    async def score_task(
        self,
        plan_end_time: str,
        close_time: str,
        task_description: str,
        handle_action: str,
        is_upload_file: bool,
    ) -> Tuple[float, str]:
        """
        精益改善任务智能评分
        返回 (score, explanation)
        """
        logger.info(f"[TaskScoring] 开始任务评分")
        logger.debug(f"[TaskScoring] plan_end_time: {plan_end_time}, close_time: {close_time}")
        logger.debug(f"[TaskScoring] is_upload_file: {is_upload_file}")
        logger.debug(f"[TaskScoring] 任务描述: {task_description}")
        logger.debug(f"[TaskScoring] 处理措施: {handle_action}")

        score = 0.0
        reasons = []

        # 1. 是否延期（1星）
        is_overdue = self._check_overdue(plan_end_time, close_time)
        if is_overdue is None:
            reasons.append("日期格式异常，无法判断是否延期，不扣分")
        elif not is_overdue:
            score += 1.0
            reasons.append("未延期，+1星 🌟")
        else:
            score -= 1.0
            reasons.append("已延期，扣1星")

        # 2. 是否上传文件（1星）
        if is_upload_file:
            score += 1.0
            reasons.append("已上传文件，+1星 🌟")
        else:
            score -= 1.0
            reasons.append("未上传文件，扣1星")

        # 3. AI质量评分（1-3星）
        ai_score, ai_reason, ai_err = await self.llm_service.score_task_quality(
            task_description, handle_action
        )
        if ai_err:
            logger.warning(f"[TaskScoring] AI评分失败: {ai_err}")
            ai_score = 1.5
            ai_reason = "AI评分服务暂时不可用，按基础分计算"
        score += ai_score
        reasons.append(f"内容质量：{ai_reason} (+{ai_score}星)")

        # 确保总分在0-5之间
        score = max(0.0, min(5.0, score))

        # 生成说明
        explanation = self._generate_task_explanation(score, reasons)
        logger.info(f"[TaskScoring] 评分完成 - 最终得分: {score}")
        return score, explanation

    def _check_overdue(self, plan_end_time: str, close_time: str) -> bool | None:
        """检查是否延期，返回 True=延期, False=未延期, None=无法判断"""
        try:
            plan_date = datetime.strptime(plan_end_time.strip(), "%Y-%m-%d").date()
            close_date = datetime.strptime(close_time.strip(), "%Y-%m-%d").date()
            return close_date > plan_date
        except ValueError as e:
            logger.warning(f"[TaskScoring] 日期解析失败: {e}")
            return None

    def _generate_task_explanation(self, score: float, reasons: list) -> str:
        """生成任务评分说明"""
        stars_display = "🌟" * int(score)
        if score - int(score) >= 0.5:
            stars_display += "✨"

        explanation_parts = [
            f"总分：{score} {stars_display}",
            "",
            "评分详情：",
        ]
        for reason in reasons:
            explanation_parts.append(f"  • {reason}")

        if score >= 4.5:
            summary = "太棒了！这份精益改善任务完成得非常出色，堪称范本！🎉"
        elif score >= 3.5:
            summary = "不错哦！任务处理质量良好，继续保持！👍"
        elif score >= 2.5:
            summary = "还可以，但还有提升空间，下次再完善一些细节吧~"
        else:
            summary = "这份任务处理还有不少需要完善的地方，加油！💪"

        explanation_parts.append("")
        explanation_parts.append(summary)
        return "\n".join(explanation_parts)

    async def score_repair_order(
        self,
        is_have_pic: bool,
        is_have_video: bool,
        handle_analysis: str,
        handle_action: str,
        is_replace_spare: bool,
        is_have_spare_record: bool,
    ) -> Tuple[float, str]:
        """
        维修单智能评分
        返回 (score, explanation)
        """
        logger.info(f"[Scoring] 开始维修单评分")
        logger.debug(f"[Scoring] 输入参数 - is_have_pic: {is_have_pic}, is_have_video: {is_have_video}")
        logger.debug(f"[Scoring] 输入参数 - is_replace_spare: {is_replace_spare}, is_have_spare_record: {is_have_spare_record}")
        logger.debug(f"[Scoring] 根因分析: {handle_analysis}")
        logger.debug(f"[Scoring] 处理措施: {handle_action}")
        score = 0.0
        reasons = []

        # 1. 图片：1星
        if is_have_pic:
            score += 1.0
            reasons.append("已上传图片，+1星 🌟")
        else:
            reasons.append("未上传图片，扣1星")

        # 2. 视频：1星
        if is_have_video:
            score += 1.0
            reasons.append("已上传视频，+1星 🌟")
        else:
            reasons.append("未上传视频，扣1星")

        # 3. 确定是否实际更换了备件
        actual_replace_spare = is_replace_spare
        ai_detected_replace = False
        if not is_replace_spare:
            # 请求中说未更换，但需要通过AI从处理措施中检测是否实际更换了
            has_replacement, detect_err = await self.llm_service.detect_spare_replacement(handle_action)
            if detect_err:
                logger.warning(f"[Scoring] 备件检测失败: {detect_err}")
            elif has_replacement:
                actual_replace_spare = True
                ai_detected_replace = True
                logger.info(f"[Scoring] AI检测到处理措施中实际更换了备件")

        # 4. AI质量评分
        ai_score, ai_reason, ai_err = await self.llm_service.score_content_quality(
            handle_analysis, handle_action, actual_replace_spare
        )
        if ai_err:
            ai_score = 1.0 if actual_replace_spare else 1.5
            ai_reason = "AI评分服务暂时不可用，按基础分计算"
        score += ai_score
        reasons.append(f"内容质量：{ai_reason} (+{ai_score}星)")

        # 5. 备件记录检查
        if actual_replace_spare:
            if is_have_spare_record:
                score += 1.0
                reasons.append("备件更换记录完整，+1星 🌟")
            elif ai_detected_replace:
                # AI从处理措施中检测到更换了备件，但请求中未标记且无记录
                reasons.append("处理措施显示更换了备件，但未填写备件更换记录，扣1星")
            else:
                reasons.append("更换了备件但未填写记录，扣1星")
        else:
            reasons.append("本维修单未更换备件")

        # 确保总分在0-5之间
        score = max(0.0, min(5.0, score))

        # 生成说明
        explanation = self._generate_explanation(score, reasons, is_replace_spare)
        logger.info(f"[Scoring] 评分完成 - 最终得分: {score}")
        return score, explanation

    def _generate_explanation(self, score: float, reasons: list, is_replace_spare: bool) -> str:
        """生成轻松风格的评分说明"""
        stars_display = "🌟" * int(score)
        if score - int(score) >= 0.5:
            stars_display += "✨"

        explanation_parts = [
            f"总分：{score} {stars_display}",
            "",
            "评分详情：",
        ]
        for reason in reasons:
            explanation_parts.append(f"  • {reason}")

        # 总结语
        if score >= 4.5:
            summary = "太棒了！这份维修单写得非常优秀，堪称范本！🎉"
        elif score >= 3.5:
            summary = "不错哦！维修单内容挺完整的，继续保持！👍"
        elif score >= 2.5:
            summary = "还可以，但还有提升空间，下次再完善一些细节吧~"
        else:
            summary = "这份维修单还有不少需要完善的地方，加油！💪"

        explanation_parts.append("")
        explanation_parts.append(summary)
        return "\n".join(explanation_parts)
