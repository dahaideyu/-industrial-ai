# cython: annotation_typing=False, infer_types=False, language_level=3
"""评估服务：收集项综合评估 + 计划进度更新"""
import json
import logging
from datetime import date, datetime, timezone

import requests
from sqlalchemy.orm import Session

from backend.core.knowledge_management.config import settings
from backend.core.knowledge_management.exceptions import NotFoundError
from backend.core.knowledge_management.models import (
    CollectionPlan,
    Document,
    DocumentVersion,
    PlanItem,
)

logger = logging.getLogger(__name__)


class EvaluationService:
    """多层评估：收集项综合评估 + 计划总进度更新。"""

    def evaluate_plan_item(self, db: Session, item_id: str):
        """汇总收集项下所有 approved 文档的评分，调 DeepSeek 生成综合评估。

        评估内容：
        - 整体完成度：是否满足要求、缺失关键文档或内容
        - 综合质量得分：加权平均或模型推理得分
        - 状态建议：已完成/待完善/缺失

        评估完成后自动触发 update_plan_progress。

        Args:
            db: 数据库会话。
            item_id: 收集项 ID。
        """
        from sqlalchemy.orm import joinedload, selectinload

        item = (
            db.query(PlanItem)
            .options(
                joinedload(PlanItem.category),
                joinedload(PlanItem.target),
                joinedload(PlanItem.plan),
                selectinload(PlanItem.documents).selectinload(Document.versions),
            )
            .filter(PlanItem.id == item_id)
            .first()
        )
        if item is None:
            raise NotFoundError(f"收集项不存在: {item_id}")

        category = item.category
        target = item.target
        plan = item.plan

        # 汇总该收集项下所有文档及其审批状态
        all_docs = item.documents
        total_docs = len(all_docs)
        approved_versions = [
            v for doc in all_docs
            for v in doc.versions
            if v.is_current and v.status == "approved"
        ]

        # 无文档时视为缺失
        if total_docs == 0:
            item.overall_completion = "缺失：未上传任何文档"
            item.overall_score = 0
            item.overall_status = "missing"
            item.evaluation_detail = {}
            db.commit()
            self.update_plan_progress(db, plan.id)
            return

        # 全部文档审批通过 → 已完成（不受 AI 评分影响）
        if len(approved_versions) >= total_docs:
            item.overall_status = "completed"
            item.overall_completion = f"已完成：{total_docs} 份文档全部通过审批"
        elif not approved_versions:
            item.overall_completion = "缺失：尚无已审批的文档"
            item.overall_score = 0
            item.overall_status = "missing"
            item.evaluation_detail = {}
            db.commit()
            self.update_plan_progress(db, plan.id)
            return
        else:
            item.overall_status = "improving"

        # 构建文档评分摘要
        doc_summaries = []
        for v in approved_versions:
            doc_summaries.append(
                {
                    "filename": v.original_filename,
                    "version": v.version_label,
                    "relevance_score": v.ai_relevance_score,
                    "quality_score": v.ai_quality_score,
                    "relevance_remark": v.ai_relevance_remark,
                    "quality_remark": v.ai_quality_remark,
                }
            )

        # 构建评估提示
        requirement_desc = item.requirement_override or category.requirement_desc
        due_info = f"截止日期: {item.due_date}" if item.due_date else "无截止日期"
        overdue = ""
        if item.due_date and item.due_date < date.today():
            overdue = "（已超期）"

        prompt = """你是一个文档质量评估专家。请根据以下信息，对收集项进行综合评估。

## 收集项信息
- 文档类别: {}
- 收集对象: {}（{}）
- 收集要求: {}
- 优先级: {}
- {}{}

## 已提交文档（共 {} 份）
{}

## 请输出 JSON 格式评估结果
{{}}""".format(category.name, target.name, target.target_type, requirement_desc, item.priority, due_info, overdue, len(approved_versions), json.dumps(doc_summaries, ensure_ascii=False, indent=2), "overall_completion")

        try:
            result = self._call_llm(prompt)
            eval_data = json.loads(result)

            item.overall_completion = eval_data.get("overall_completion", "")
            item.overall_score = eval_data.get("overall_score", 0)
            # AI 的建议状态仅作参考，不覆盖全部通过时的 completed
            if item.overall_status != "completed":
                ai_status = eval_data.get("overall_status", "待完善")
                item.overall_status = "completed" if ai_status == "已完成" else "improving" if ai_status == "待完善" else "missing"
            item.evaluation_detail = eval_data.get("evaluation_detail", {})
            item.evaluated_at = datetime.now(timezone.utc)
        except Exception:
            logger.exception("收集项评估失败: item_id=%s", item_id)
            avg_score = sum(
                (v.ai_quality_score or 0) for v in approved_versions
            ) // len(approved_versions)
            item.overall_score = avg_score
            if item.overall_status != "completed":
                item.overall_status = "completed" if avg_score >= 80 else "improving" if avg_score >= 50 else "missing"
            item.overall_completion = f"基于 {len(approved_versions)} 份文档的平均质量得分 {avg_score}"
            item.evaluated_at = datetime.now(timezone.utc)

        db.commit()
        logger.info(
            "收集项评估完成: item_id=%s, status=%s, score=%s",
            item_id,
            item.overall_status,
            item.overall_score,
        )

        # 自动触发计划进度更新
        self.update_plan_progress(db, plan.id)

    def update_plan_progress(self, db: Session, plan_id: str):
        """统计各收集项状态，计算整体进度百分比，调 DeepSeek 生成整体分析。

        统计维度：已完成/待完善/缺失/超期
        更新 collection_plan 的 overall_progress, overall_analysis, overall_stats。

        Args:
            db: 数据库会话。
            plan_id: 计划 ID。
        """
        plan = db.get(CollectionPlan, plan_id)
        if plan is None:
            raise NotFoundError(f"收集计划不存在: {plan_id}")

        items = (
            db.query(PlanItem)
            .filter(PlanItem.plan_id == plan_id)
            .all()
        )

        if not items:
            plan.overall_progress = 0
            plan.overall_analysis = "暂无收集项"
            plan.overall_stats = {
                "completed": 0,
                "improving": 0,
                "missing": 0,
                "overdue": 0,
            }
            db.commit()
            return

        # 统计各状态（overall_status 值为英文: completed/improving/missing）
        stats = {"completed": 0, "improving": 0, "missing": 0, "overdue": 0}
        today = date.today()

        for item in items:
            status = item.overall_status
            is_overdue = item.due_date and item.due_date < today and status != "completed"

            if status == "completed":
                stats["completed"] += 1
            elif status == "improving":
                stats["improving"] += 1
            else:  # missing 或 None
                stats["missing"] += 1

            if is_overdue:
                stats["overdue"] += 1

        total = len(items)
        progress = round(stats["completed"] / total * 100) if total > 0 else 0

        # 构建评估提示
        item_details = []
        for item in items:
            cat_name = item.category.name if item.category else "未知"
            target_name = item.target.name if item.target else "未知"
            item_details.append(
                f"- {target_name} - {cat_name}: "
                f"状态={item.overall_status or '未评估'}, "
                f"得分={item.overall_score or '-'}, "
                f"优先级={item.priority}"
            )

        prompt = """你是一个文档收集计划管理专家。请根据以下收集项评估结果，生成整体分析说明。

## 计划信息
- 计划名称: {}
- 总收集项数: {}
- 已完成: {}  待完善: {}  缺失: {}  超期: {}
- 整体进度: {}%

## 各收集项详情
{}

## 请输出简洁的整体分析说明（200字以内），包括：
1. 整体完成情况
2. 主要缺失或薄弱环节
3. 建议优先处理的方向""".format(plan.name, total, stats['completed'], stats['improving'], stats['missing'], stats['overdue'], progress, chr(10).join(item_details))

        try:
            analysis = self._call_llm(prompt)
        except Exception:
            logger.exception("生成计划整体分析失败: plan_id=%s", plan_id)
            analysis = (
                f"计划共 {total} 个收集项，已完成 {stats['completed']} 个"
                f"（{progress}%），待完善 {stats['improving']} 个，"
                f"缺失 {stats['missing']} 个，超期 {stats['overdue']} 个。"
            )

        plan.overall_progress = progress
        plan.overall_analysis = analysis
        plan.overall_stats = stats
        plan.evaluated_at = datetime.now(timezone.utc)
        # 计算计划级平均质量分
        scores = [item.overall_score for item in items if item.overall_score is not None]
        plan.overall_score = round(sum(scores) / len(scores)) if scores else None
        db.commit()

        logger.info(
            "计划进度更新完成: plan_id=%s, progress=%d%%, stats=%s",
            plan_id,
            progress,
            stats,
        )

    def check_auto_evaluate(self, db: Session, plan_item_id: str):
        """检查收集项下所有文档是否都完成了审批，如果是则自动触发评估。

        条件：该收集项下至少有一份文档，且所有文档的当前版本都已审批（approved 或 rejected）。

        Args:
            db: 数据库会话。
            plan_item_id: 收集项 ID。
        """
        item = db.get(PlanItem, plan_item_id)
        if item is None:
            return

        # 获取所有文档及其当前版本（一次查询）
        from backend.core.knowledge_management.models import Document
        from sqlalchemy.orm import selectinload

        documents = (
            db.query(Document)
            .options(selectinload(Document.versions))
            .filter(Document.plan_item_id == plan_item_id)
            .all()
        )

        if not documents:
            return

        for doc in documents:
            current_version = next(
                (v for v in doc.versions if v.is_current), None
            )
            if current_version is None:
                return
            if current_version.status not in ("approved", "rejected"):
                return

        # 所有文档都完成了审批，触发评估
        logger.info("自动触发收集项评估: plan_item_id=%s", plan_item_id)
        self.evaluate_plan_item(db, plan_item_id)

    # ------------------------------------------------------------------
    #  内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _call_llm(prompt: str) -> str:
        """调用 LLM API 生成文本（根据 PROVIDER 环境变量自动适配模型供应商）。

        Args:
            prompt: 用户提示。

        Returns:
            模型返回的文本内容。

        Raises:
            RuntimeError: API 调用失败。
        """
        url = f"{settings.deepseek_base_url.rstrip('/')}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.deepseek_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 2000,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("LLM API 未返回有效响应")

        return choices[0]["message"]["content"].strip()


# 模块级单例
evaluation_svc = EvaluationService()
