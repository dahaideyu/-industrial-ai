# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库健康度诊断与 LLM 总结服务。"""

import concurrent.futures
import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from backend.core.knowledge_management.models import (
    CollectionPlan,
    Document,
    DocumentVersion,
    KnowledgeBase,
    PlanItem,
)
from backend.services.knowledge_management.kb_type_state_svc import kb_type_state_svc

logger = logging.getLogger(__name__)

# 24 小时按日缓存：保证每天最多调用一次 LLM
_SUMMARY_CACHE_TTL_SEC = 24 * 60 * 60
_summary_cache: Dict[str, Any] = {"text": "", "expires_at": 0.0}
_summary_lock = threading.Lock()

_LLM_TIMEOUT_SEC = 30

# ── LLM 工具函数 ──

def _call_llm_inner(prompt: str, system_prompt: str) -> str:
    """调用 LLM（内部实现，不经超时包装）。"""
    from backend.core.agentic_qa.llm import LLM

    llm = LLM()
    return llm.chat_once(user_prompt=prompt, system_prompt=system_prompt, max_tokens=2000)


def _call_llm(prompt: str, system_prompt: str) -> str:
    """调用 LLM，30s 超时；失败抛 RuntimeError。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call_llm_inner, prompt, system_prompt)
        try:
            return future.result(timeout=_LLM_TIMEOUT_SEC)
        except concurrent.futures.TimeoutError:
            raise RuntimeError(f"LLM 调用超时 ({_LLM_TIMEOUT_SEC}s)")

# ── 辅助函数 ──

def _kb_type_enabled(kb_type: str, disabled_types: set) -> bool:
    """判断 kb_type 是否有效启用。"""
    return kb_type not in disabled_types


def _compute_kb_progress(kb: KnowledgeBase, disabled_types: set) -> float | None:
    """计算单个 KB 的进度百分比。"""
    total_items = 0
    completed_items = 0
    for plan in kb.plans:
        for item in plan.plan_items:
            if not item.not_applicable:
                total_items += 1
                if item.overall_status == "completed":
                    completed_items += 1
    return round(completed_items / total_items * 100, 1) if total_items > 0 else 0.0


# ── 服务类 ──

class KnowledgeOverviewService:
    """聚合 4 个维度诊断 + 调用 LLM 生成中文总结。"""

    def diagnose(self, db: Session) -> Dict[str, Any]:
        """返回结构化诊断数据，前端 /knowledge-overview 与 Dashboard 共用。

        向数据库查询进度 / 质量 / 合规 / 内容缺失四个维度的真实数据。
        """
        if db is None:
            return self._empty_diagnose(evaluated_at=None)
        return self._diagnose_with_db(db)

    def _diagnose_with_db(self, db: Session) -> Dict[str, Any]:
        tz_china = timezone(timedelta(hours=8))
        evaluated_at = datetime.now(tz_china).isoformat()

        states = kb_type_state_svc.list_states(db)
        enabled_count = sum(1 for v in states.values() if v)
        disabled_count = sum(1 for v in states.values() if not v)
        disabled_types = db_disabled = {k for k, v in states.items() if not v}

        # ── 进度维度 ──
        all_kbs = (
            db.query(KnowledgeBase)
            .options(
                joinedload(KnowledgeBase.plans).joinedload(CollectionPlan.plan_items)
            )
            .filter(
                KnowledgeBase.status == "active",
                KnowledgeBase.kb_type.in_(["device", "compliance"]),
            )
            .all()
        )
        kbs = [
            kb
            for kb in all_kbs
            if kb.enabled and _kb_type_enabled(kb.kb_type, disabled_types)
        ]

        # plan_type -> {score_sum, progress_sum, count, doc_count, plan_count, device_types}
        plan_type_stats: Dict[str, dict] = {}
        _WORKSHOP_PROGRESSES: Dict[str, list] = {}  # workshop -> [progress, ...]

        for kb in kbs:
            ws = (kb.tags or {}).get("workshop", "") if kb.tags else ""

            if kb.kb_type == "compliance":
                total_items = 0
                completed_items = 0
                item_docs = 0
                for plan in kb.plans:
                    for item in plan.plan_items:
                        if not item.not_applicable:
                            total_items += 1
                            if item.overall_status == "completed":
                                completed_items += 1
                        if item.documents:
                            item_docs += len(item.documents)
                progress = (
                    round(completed_items / total_items * 100, 1)
                    if total_items > 0
                    else 0.0
                )
                key = "compliance"
                if key not in plan_type_stats:
                    plan_type_stats[key] = {
                        "score_sum": 0, "progress_sum": 0.0, "count": 0,
                        "doc_count": 0, "plan_count": 0, "device_types": set(),
                    }
                st = plan_type_stats[key]
                st["score_sum"] += kb.overall_score or 0
                st["progress_sum"] += progress
                st["count"] += 1
                st["doc_count"] += item_docs
                st["plan_count"] += len(kb.plans)
            else:
                for plan in kb.plans:
                    pt = plan.plan_type or "device_doc"
                    if pt not in ("device_doc", "sop_doc"):
                        continue
                    total_items = 0
                    completed_items = 0
                    item_docs = 0
                    for item in plan.plan_items:
                        if not item.not_applicable:
                            total_items += 1
                            if item.overall_status == "completed":
                                completed_items += 1
                        if item.documents:
                            item_docs += len(item.documents)
                    progress = (
                        round(completed_items / total_items * 100, 1)
                        if total_items > 0
                        else 0.0
                    )
                    if pt not in plan_type_stats:
                        plan_type_stats[pt] = {
                            "score_sum": 0, "progress_sum": 0.0, "count": 0,
                            "doc_count": 0, "plan_count": 0, "device_types": set(),
                        }
                    st = plan_type_stats[pt]
                    st["score_sum"] += plan.overall_score or 0
                    st["progress_sum"] += progress
                    st["count"] += 1
                    st["doc_count"] += item_docs
                    st["plan_count"] += 1
                    if kb.device_type:
                        st["device_types"].add(kb.device_type)

                # workshop 进度聚合（用于 lagging_workshops）
                if ws:
                    ws_progress = kb.overall_progress or _compute_kb_progress(kb, disabled_types)
                    if ws_progress is not None:
                        _WORKSHOP_PROGRESSES.setdefault(ws, []).append(ws_progress)

        # 聚合 plan_type_stats → kb_progress 列表
        kb_progress_list = []
        for ptype, st in plan_type_stats.items():
            n = st["count"]
            kb_progress_list.append({
                "kb_type": ptype,
                "name": {
                    "device_doc": "设备说明知识库",
                    "sop_doc": "设备SOP知识库",
                    "compliance": "合规性知识库",
                }.get(ptype, ptype),
                "progress": round(st["progress_sum"] / n, 1) if n > 0 else 0,
                "score": round(st["score_sum"] / n, 1) if n > 0 else 0,
                "plan_count": st["plan_count"],
                "doc_count": st["doc_count"],
                "device_type_count": len(st["device_types"]),
            })

        # 总进度
        progresses = [s["progress"] for s in kb_progress_list]
        total_progress = round(sum(progresses) / len(progresses), 1) if progresses else 0.0

        # 总质量分（沿用 dashboard_base 逻辑）
        comp_score = next((s["score"] for s in kb_progress_list if s["kb_type"] == "compliance"), None)
        device_scores = [s["score"] for s in kb_progress_list if s["kb_type"] in ("device_doc", "sop_doc")]
        device_avg = sum(device_scores) / len(device_scores) if device_scores else 0
        if comp_score is not None and device_scores:
            total_score = round((comp_score + device_avg) / 2, 1)
        elif comp_score is not None:
            total_score = comp_score
        elif device_scores:
            total_score = round(device_avg, 1)
        else:
            total_score = 0

        # 落后车间（进度最低的 5 个）
        ws_avg = {ws: sum(vals) / len(vals) for ws, vals in _WORKSHOP_PROGRESSES.items() if vals}
        lagging_workshops = sorted(
            [
                {"workshop": ws, "progress": round(avg, 1)}
                for ws, avg in ws_avg.items()
                if avg < 60  # 只在落后时展示
            ],
            key=lambda x: x["progress"],
        )[:5]

        # 落后设备类型
        device_kbs = [
            kb for kb in kbs
            if kb.kb_type == "device" and kb.device_type and (kb.overall_progress or 0) < 60
        ]
        device_kbs.sort(key=lambda kb: kb.overall_progress or 0)
        lagging_device_types = [
            {
                "workshop": (kb.tags or {}).get("workshop", ""),
                "device_type": kb.device_type,
                "kb_type": "device_doc",
                "progress": kb.overall_progress or 0,
            }
            for kb in device_kbs[:10]
        ]

        # ── 质量维度 ──
        low_quality_versions = (
            db.query(DocumentVersion)
            .join(Document, DocumentVersion.document_id == Document.id)
            .join(PlanItem, Document.plan_item_id == PlanItem.id)
            .join(CollectionPlan, PlanItem.plan_id == CollectionPlan.id)
            .join(KnowledgeBase, CollectionPlan.knowledge_base_id == KnowledgeBase.id)
            .filter(
                DocumentVersion.is_current == True,
                DocumentVersion.ai_quality_score.isnot(None),
                DocumentVersion.ai_quality_score < 60,
                KnowledgeBase.enabled == True,
            )
            .order_by(DocumentVersion.ai_quality_score.asc())
            .limit(20)
            .all()
        )

        quality_distribution = {"high": 0, "medium": 0, "low": 0}
        _all_scored = (
            db.query(DocumentVersion.ai_quality_score)
            .join(Document, DocumentVersion.document_id == Document.id)
            .join(PlanItem, Document.plan_item_id == PlanItem.id)
            .join(CollectionPlan, PlanItem.plan_id == CollectionPlan.id)
            .join(KnowledgeBase, CollectionPlan.knowledge_base_id == KnowledgeBase.id)
            .filter(
                DocumentVersion.is_current == True,
                DocumentVersion.ai_quality_score.isnot(None),
                KnowledgeBase.enabled == True,
            )
            .all()
        )
        for (score,) in _all_scored:
            if score is None:
                continue
            if score >= 80:
                quality_distribution["high"] += 1
            elif score >= 60:
                quality_distribution["medium"] += 1
            else:
                quality_distribution["low"] += 1

        low_quality_docs = []
        for v in low_quality_versions:
            doc = v.document
            plan_item = doc.plan_item if doc else None
            plan = plan_item.plan if plan_item else None
            kb = plan.knowledge_base if plan else None
            low_quality_docs.append({
                "version_id": v.id,
                "filename": v.original_filename or "—",
                "kb_type": kb.kb_type if kb else "—",
                "device_type": kb.device_type if kb and kb.device_type else "—",
                "relevance_score": v.ai_relevance_score or 0,
                "quality_score": v.ai_quality_score or 0,
                "remark": v.ai_quality_remark or v.ai_relevance_remark or "",
            })

        low_quality_doc_count = len(low_quality_docs)

        # ── 合规维度 ──
        compliance_versions = (
            db.query(DocumentVersion)
            .join(Document, DocumentVersion.document_id == Document.id)
            .join(PlanItem, Document.plan_item_id == PlanItem.id)
            .join(CollectionPlan, PlanItem.plan_id == CollectionPlan.id)
            .join(KnowledgeBase, CollectionPlan.knowledge_base_id == KnowledgeBase.id)
            .filter(
                KnowledgeBase.kb_type == "compliance",
                KnowledgeBase.enabled == True,
                DocumentVersion.is_current == True,
                DocumentVersion.valid_until.isnot(None),
            )
            .all()
        )

        today = date.today()
        soon_deadline = today + timedelta(days=30)
        valid_count = 0
        expired_count = 0
        expiring_soon_count = 0
        expired_docs = []
        expiring_soon_docs = []

        for v in compliance_versions:
            if v.valid_until is None:
                continue
            if v.valid_until < today:
                expired_count += 1
                expired_docs.append({
                    "version_id": v.id,
                    "filename": v.original_filename or "—",
                    "expired_days": (today - v.valid_until).days,
                })
            elif v.valid_until <= soon_deadline:
                expiring_soon_count += 1
                expiring_soon_docs.append({
                    "version_id": v.id,
                    "filename": v.original_filename or "—",
                    "days_to_expire": (v.valid_until - today).days,
                })
            else:
                valid_count += 1

        # ── 内容缺失维度 ──
        # 1) 已启用的 device KB 但没有任何 active 计划
        device_kbs_all = (
            db.query(KnowledgeBase)
            .options(joinedload(KnowledgeBase.plans))
            .filter(
                KnowledgeBase.status == "active",
                KnowledgeBase.kb_type.in_(["device", "device_doc", "sop_doc"]),
                KnowledgeBase.enabled == True,
            )
            .all()
        )
        enabled_kb_without_plan = []
        for kb in device_kbs_all:
            if kb.kb_type in disabled_types:
                continue
            if not kb.plans or len(kb.plans) == 0:
                enabled_kb_without_plan.append({
                    "workshop": (kb.tags or {}).get("workshop", "—"),
                    "device_type": kb.device_type or "—",
                    "kb_type": "device_doc",
                })

        # 2) 精确 COUNT：所有未完成的收集项总数（与 evaluation_svc 统计一致，不过滤 not_applicable）
        missing_total_count = (
            db.query(func.count(PlanItem.id))
            .join(CollectionPlan, PlanItem.plan_id == CollectionPlan.id)
            .join(KnowledgeBase, CollectionPlan.knowledge_base_id == KnowledgeBase.id)
            .filter(
                KnowledgeBase.enabled == True,
                or_(
                    PlanItem.overall_status != "completed",
                    PlanItem.overall_status.is_(None),
                ),
            )
            .scalar()
        ) or 0

        # 3) 按 plan_type 分组拉取详情（与 evaluation_svc 一致不过滤 not_applicable）
        #    不限制 limit：必须看到所有设备类型的所有缺失项
        missing_by_plan_type = {"compliance": [], "device_doc": [], "sop_doc": []}
        for pt in ("compliance", "device_doc", "sop_doc"):
            rows = (
                db.query(PlanItem)
                .join(CollectionPlan, PlanItem.plan_id == CollectionPlan.id)
                .join(KnowledgeBase, CollectionPlan.knowledge_base_id == KnowledgeBase.id)
                .filter(
                    KnowledgeBase.enabled == True,
                    CollectionPlan.plan_type == pt,
                    or_(
                        PlanItem.overall_status != "completed",
                        PlanItem.overall_status.is_(None),
                    ),
                )
                .options(
                    joinedload(PlanItem.category),
                    joinedload(PlanItem.plan).joinedload(CollectionPlan.knowledge_base),
                )
                .all()
            )
            for item in rows:
                kb = item.plan.knowledge_base if item.plan else None
                ws = (kb.tags or {}).get("workshop", "") if kb and kb.tags else ""
                missing_by_plan_type[pt].append({
                    "plan_item_id": item.id,
                    "category": item.category.name if item.category else "—",
                    "device_type": kb.device_type if kb and kb.device_type else "—",
                    "workshop": ws,
                    "missing_days": (today - (item.due_date or today)).days if item.due_date else 0,
                })

        missing_device_type_count = len(enabled_kb_without_plan)
        missing_plan_item_count = missing_total_count

        # 设备类型清单（每个 KB 独立，从 KnowledgeBase 直接取，固定 19 个）
        device_type_list = {"device_doc": [], "sop_doc": []}
        device_kbs_for_list = (
            db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.status == "active",
                KnowledgeBase.kb_type == "device",
                KnowledgeBase.enabled == True,
                KnowledgeBase.device_type.isnot(None),
            )
            .all()
        )
        for kb in device_kbs_for_list:
            if kb.kb_type in disabled_types:
                continue
            # device KB 同时包含 device_doc 和 sop_doc 两个 plan
            # 即使某个 plan 下没有缺失项，也应显示该设备类型
            device_type_list["device_doc"].append(kb.device_type)
            device_type_list["sop_doc"].append(kb.device_type)
        # 去重 + 排序
        for pt in device_type_list:
            device_type_list[pt] = sorted(set(device_type_list[pt]))

        return {
            "evaluated_at": evaluated_at,
            "summary": {
                "total_progress": total_progress,
                "total_score": total_score,
                "expired_count": expired_count,
                "missing_device_type_count": missing_device_type_count,
                "missing_plan_item_count": missing_plan_item_count,
                "low_quality_doc_count": low_quality_doc_count,
                "enabled_kb_count": enabled_count,
                "disabled_kb_count": disabled_count,
            },
            "progress": {
                "kb_progress": kb_progress_list,
                "lagging_workshops": lagging_workshops,
                "lagging_device_types": lagging_device_types,
            },
            "quality": {
                "distribution": quality_distribution,
                "low_quality_docs": low_quality_docs,
            },
            "compliance": {
                "valid_count": valid_count,
                "expired_count": expired_count,
                "expiring_soon_count": expiring_soon_count,
                "expired_docs": expired_docs,
                "expiring_soon_docs": expiring_soon_docs,
            },
            "missing": {
                "enabled_kb_without_plan": enabled_kb_without_plan,
                "missing_by_plan_type": missing_by_plan_type,
                "device_type_list": device_type_list,
            },
        }

    def _empty_diagnose(self, evaluated_at: str | None = None) -> Dict[str, Any]:
        """数据库不可用时的兜底结构。"""
        if evaluated_at is None:
            tz_china = timezone(timedelta(hours=8))
            evaluated_at = datetime.now(tz_china).isoformat()
        return {
            "evaluated_at": evaluated_at,
            "summary": {
                "total_progress": 0.0,
                "total_score": 0,
                "expired_count": 0,
                "missing_device_type_count": 0,
                "missing_plan_item_count": 0,
                "low_quality_doc_count": 0,
                "enabled_kb_count": 0,
                "disabled_kb_count": 0,
            },
            "progress": {"kb_progress": [], "lagging_workshops": [], "lagging_device_types": []},
            "quality": {"distribution": {"high": 0, "medium": 0, "low": 0}, "low_quality_docs": []},
            "compliance": {
                "valid_count": 0, "expired_count": 0, "expiring_soon_count": 0,
                "expired_docs": [], "expiring_soon_docs": [],
            },
            "missing": {"enabled_kb_without_plan": [], "missing_by_plan_type": {"compliance": [], "device_doc": [], "sop_doc": []}, "device_type_list": {"device_doc": [], "sop_doc": []}},
        }

    def build_summary(self, diag: Dict[str, Any]) -> str:
        """根据诊断数据生成 ≤400 字中文总结。失败/超时返回降级文案。"""
        cache_key_text = json.dumps(diag.get("summary", {}), ensure_ascii=False, sort_keys=True)
        now = time.time()

        with _summary_lock:
            if (
                _summary_cache["text"]
                and _summary_cache.get("cache_key") == cache_key_text
                and now < _summary_cache["expires_at"]
            ):
                return _summary_cache["text"]

        diag_json = json.dumps(diag, ensure_ascii=False, indent=2)
        system_prompt = (
            "你是一名工业知识库管理顾问。请根据以下诊断数据，用中文输出 Markdown 格式总结，"
            "严格按以下三段结构：\n"
            "## 结论\n（1-2 句话直接给出整体健康判断，例如'知识库整体健康偏弱，最紧急的问题是 X'）\n"
            "## 逐项分析\n（用 3-4 个要点，分别覆盖进度、质量、合规、内容缺失，每点 1-2 句）\n"
            "## 整改建议\n（3 条按优先级排序的可执行建议，每条一行）\n"
            "总长度不超过 600 字。只输出上述 Markdown 三段，不要多余说明。"
        )
        user_prompt = f"诊断数据：\n{diag_json}"

        try:
            text = _call_llm(user_prompt, system_prompt)
            text = (text or "").strip()[:800]
            if not text:
                raise RuntimeError("LLM 返回空内容")
        except Exception as exc:
            logger.warning("build_summary LLM 调用失败，降级为模板文案: %s", exc)
            text = self._fallback_summary(diag)

        with _summary_lock:
            _summary_cache.update(
                {"text": text, "cache_key": cache_key_text, "expires_at": now + _SUMMARY_CACHE_TTL_SEC}
            )
        return text

    def _fallback_summary(self, diag: Dict[str, Any]) -> str:
        """LLM 失败时本地拼接的降级文案。"""
        s = diag.get("summary", {})
        parts = [
            f"知识库总体完成率 {s.get('total_progress', 0)}%，质量分 {s.get('total_score', 0)}。",
        ]
        if s.get("expired_count", 0) > 0:
            parts.append(f"合规方面，{s['expired_count']} 项证书已过期需尽快续期。")
        if s.get("missing_device_type_count", 0) > 0:
            parts.append(f"{s['missing_device_type_count']} 个设备类型尚未建立知识库。")
        if s.get("missing_plan_item_count", 0) > 0:
            parts.append(f"{s['missing_plan_item_count']} 个收集项尚未上传文档。")
        if s.get("low_quality_doc_count", 0) > 0:
            parts.append(f"{s['low_quality_doc_count']} 份文档 AI 评分低于 60，建议重传。")
        parts.append("详细诊断请进入评估报告查看。")
        return "".join(parts)[:800]
