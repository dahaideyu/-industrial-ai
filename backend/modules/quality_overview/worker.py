# cython: annotation_typing=False, infer_types=False, language_level=3
"""
质量概览报告作业编排器
编排质量日/周/月报告的生成流程
"""
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

# 确保 backend 目录在路径中
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(os.path.dirname(current_dir))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from backend.clients.upstream_client import UpstreamClient
from backend.core.singletons import get_upstream_client, get_report_generator_singleton
from backend.core.job_logger import JobLogger
from backend.core import database as db

logger = logging.getLogger(__name__)


class QualityOverviewWorker:
    """质量概览报告作业编排器"""

    def __init__(
        self,
        upstream_client: UpstreamClient = None,
        report_generator=None,
    ):
        """
        初始化作业编排器

        Args:
            upstream_client: 上游客户端（为 None 时使用全局单例）
            report_generator: 报告生成器（为 None 时使用全局单例）
        """
        self.upstream = upstream_client or get_upstream_client()
        self.generator = report_generator or get_report_generator_singleton()

    def _run_single_quality_report(
        self,
        report_type: str,
        report_date: str = None,
        workshop_id: int = None,
        job_logger=None,
    ) -> dict:
        """
        执行单个质量概览报告生成（日报/周报/月报）

        Args:
            report_type: 报告类型，可选值 "daily" | "weekly" | "monthly"
            report_date: 报告日期/锚点日（可选）
            job_logger: 可选，外部传入的日志器（批量模式时使用）

        Returns:
            {
                "reportId": int or None,
                "success": bool,
                "error": str or None,
                "callbackOk": bool or None,
                "logFile": str,
            }
        """
        config_map = {
            "daily": {
                "label": "质量概览日报",
                "report_code": "qualityDailyReport",
                "pull_method": self.upstream.pull_quality_daily_params,
            },
            "weekly": {
                "label": "质量概览周报",
                "report_code": "qualityWeeklyReport",
                "pull_method": self.upstream.pull_quality_weekly_params,
            },
            "monthly": {
                "label": "质量概览月报",
                "report_code": "qualityMonthlyReport",
                "pull_method": self.upstream.pull_quality_monthly_params,
            },
        }

        if report_type not in config_map:
            raise ValueError(f"不支持的报告类型: {report_type}")

        cfg = config_map[report_type]
        label = cfg["label"]
        report_code = cfg["report_code"]
        pull_method = cfg["pull_method"]

        # 如果外部没有传入日志器，则创建独立的日志器
        own_logger = False
        if job_logger is None:
            job_logger = JobLogger(
                job_type=report_code,
                report_date=report_date or datetime.now().strftime("%Y-%m-%d"),
                params={"report_type": report_type, "report_date": report_date},
            )
            own_logger = True
            job_logger.print_separator()
            job_logger.info("[Agent 作业开始] %s 生成", label)
            job_logger.print_separator()

        job_logger.info("")
        job_logger.print_separator()
        job_logger.info("[%s] 开始执行", label)
        job_logger.print_separator()

        if workshop_id:
            job_logger.info("  车间ID: %s", workshop_id)
        else:
            job_logger.info("  车间ID: 无（工厂级）")
        job_logger.info("  报告日期: %s", report_date or "默认昨日")

        report_id = None
        has_error = False
        error_msg = ""
        callback_ok = None
        reports = []

        try:
            # ---- 阶段 1: 拉参 ----
            # report_date 为空时默认昨日
            if not report_date:
                report_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            job_logger.info("")
            job_logger.info("[阶段 1/3] 拉取参数...")
            pull_result = pull_method(report_date=report_date, workshop_id=workshop_id)
            report_id = pull_result["reportId"]
            payload = pull_result["payload"]
            payload_len = len(json.dumps(payload, ensure_ascii=False))
            job_logger.info("  ✅ 拉参成功, reportId=%s, payload长度=%d字符", report_id, payload_len)

            # 确保 reportCode 正确
            payload.setdefault("reportCode", report_code)

            # ---- 从 payload 提取 period_label（账期） ----
            meta = payload.get("meta", {}) or {}
            period_label = meta.get("periodLabel", meta.get("period", ""))
            job_logger.info("  📅 账期 (period_label): %s", period_label or "(空)")

            # ---- 加载历史报告上下文 ----
            # 日报往前6期，周报往前3期，月报往前3期
            historical_periods_map = {
                "daily": 6,
                "weekly": 3,
                "monthly": 3,
            }
            hist_periods = historical_periods_map.get(report_type)
            if hist_periods and period_label:
                job_logger.info("  加载历史报告上下文...")
                historical_context = self._load_quality_historical_context(
                    report_code=report_code,
                    period_label=period_label,
                    periods=hist_periods,
                    job_logger=job_logger,
                )
                if historical_context:
                    # 将历史报告注入 payload 的 meta 中
                    if "meta" not in payload or not isinstance(payload["meta"], dict):
                        payload["meta"] = {}
                    payload["meta"]["historicalContext"] = historical_context
                    job_logger.info("  ✅ 历史上下文注入完成，长度: %d 字符", len(historical_context))
                else:
                    job_logger.info("  ⚠️  未找到历史报告，跳过注入")

            # ---- 数据预处理（clean + map-reduce，复用给 generator 和持久化） ----
            from backend.utils.data_preprocessor import preprocess_payload
            preprocessed_data_json = preprocess_payload(payload)
            job_logger.info("  ✅ 数据预处理完成，长度: %d 字符", len(preprocessed_data_json))

            # ---- 阶段 2: 生成报告 ----
            job_logger.info("")
            job_logger.info("[阶段 2/3] 生成报告...")
            reports = self._collect_reports_from_stream(report_code, payload, job_logger=job_logger,
                                                        preprocessed_data_json=preprocessed_data_json)
            total_report_len = sum(len(r.get("content", "")) for r in reports)
            job_logger.info("  ✅ 报告生成完成, 共 %d 份, 总长度=%d字符", len(reports), total_report_len)

            # ---- 阶段 3: 映射字段 + 回写 ----
            job_logger.info("")
            job_logger.info("[阶段 3/3] 映射回调字段并回写上游...")
            callback_fields = self._map_to_callback_fields(reports, job_logger=job_logger)

            self.upstream.callback_complete(
                report_id=report_id,
                status="0",
                markdown_content=callback_fields.get("markdownContent", ""),
                summary_markdown=callback_fields.get("summaryMarkdown", ""),
                kb_report_markdown=callback_fields.get("kbReportMarkdown", ""),
                knowledge_base_payload=callback_fields.get("knowledgeBasePayload", ""),
                agent_response_raw=json.dumps({"reports": reports}, ensure_ascii=False),
            )
            callback_ok = True
            job_logger.info("  ✅ 上游回写成功")

            # 持久化到 SQLite
            try:
                date_type = meta.get("periodType", meta.get("dateType", "day"))
                db.upsert_report(
                    report_code=report_code,
                    title=f"{label} {period_label}",
                    period_label=period_label,
                    request_payload=payload,
                    agent_response_raw=json.dumps({"reports": reports}, ensure_ascii=False),
                    markdown_content=callback_fields.get("markdownContent", ""),
                    summary_markdown=callback_fields.get("summaryMarkdown", ""),
                    kb_report_markdown=callback_fields.get("kbReportMarkdown", ""),
                    knowledge_base_payload=callback_fields.get("knowledgeBasePayload", ""),
                    status=0,
                    error_message="",
                    workshop_id=workshop_id,
                    report_date=report_date,
                    date_type=date_type,
                    agent_response_processed=preprocessed_data_json,
                )
                job_logger.info("  ✅ PostgreSQL 持久化完成 (workshop_id=%s)", workshop_id or 0)
            except Exception as e:
                job_logger.warning("  ❌ PostgreSQL 持久化失败: %s", e)

        except Exception as e:
            has_error = True
            error_msg = str(e)
            job_logger.error("[报告生成] 执行失败: %s", e, exc_info=True)
            job_logger.info("  ❌ 执行失败: %s", e)

            # 失败时尝试回写
            if report_id:
                try:
                    self.upstream.callback_complete(
                        report_id=report_id,
                        status="1",
                        error_message=error_msg,
                    )
                    callback_ok = True
                    job_logger.info("  ✅ 失败状态已回写上游")
                except Exception as cb_err:
                    callback_ok = False
                    job_logger.error("  ❌ 失败回写也失败了: %s", cb_err)

        job_logger.info("[报告生成] 执行结果: success=%s, reportId=%s, callbackOk=%s",
                        not has_error, report_id, callback_ok)

        result = {
            "reportId": report_id,
            "success": not has_error,
            "error": error_msg or None,
            "callbackOk": callback_ok,
            "logFile": job_logger.get_log_file_path(),
        }

        # ========== 控制台汇总输出 ==========
        job_logger.info("")
        job_logger.info("#" * 70)
        job_logger.info("# [Agent 作业完成]")
        job_logger.info("#" * 70)
        job_logger.info("#  报告日期: %s", report_date)
        if workshop_id:
            job_logger.info("#  车间ID: %s", workshop_id)
        job_logger.info("#  上游报告ID: %s", report_id)
        job_logger.info("#  生成状态: %s", "✅ 成功" if not has_error else "❌ 失败")
        job_logger.info("#  回调状态: %s", "✅ 成功" if callback_ok else "❌ 失败")
        job_logger.info("#  生成报告数: %s 份", len(reports))
        for i, r in enumerate(reports, 1):
            status = "❌" if r.get("error") else "✅"
            job_logger.info("#    [%d] %s %s (%d 字符)", i, status, r.get("output_name", ""), len(r.get("content", "")))
        job_logger.info("#  日志文件: %s", job_logger.get_log_file_path())
        job_logger.info("#" * 70)
        job_logger.info("")

        return result

    def _load_quality_historical_context(
        self,
        report_code: str,
        period_label: str,
        periods: int = 6,
        job_logger=None,
    ) -> str:
        """
        从 SQLite 查询质量报告历史上下文
        每个账期只取最新一条记录（去重）

        Args:
            report_code: 报告类型编码
            period_label: 当前报告账期
            periods: 往前拉取的周期数，默认 6
            job_logger: 作业日志器

        Returns:
            历史报告内容字符串，无历史记录时返回空串
        """
        log = job_logger or logger
        log.info("[质量历史报告] 查询: report_code=%s, period_label=%s, periods=%s",
                 report_code, period_label, periods)

        records = db.query_reports_distinct_by_period_label(
            report_code=report_code,
            period_label_exclude=period_label,
            status=0,
            limit=periods,
        )
        log.info("  找到 %s 个不同账期的历史记录", len(records))

        if not records:
            return ""

        # query_reports_distinct_by_period_label 已包含 markdown_content，无需再单独查询
        context_parts = []
        for record in records:
            record_date = record.get("report_date", "")
            content = record.get("markdown_content", "")
            if content:
                context_parts.append(f"### {record_date}\n{content}")

        if not context_parts:
            return ""

        historical_context = "\n\n".join(context_parts)
        log.info("[质量历史报告] 拼接完成: %d 期, 总长度=%d 字符",
                 len(context_parts), len(historical_context))
        return historical_context

    def _collect_reports_from_stream(
        self, report_code: str, payload: dict, job_logger=None, preprocessed_data_json: str = None
    ) -> list:
        """
        消费 generate_reports_stream() 生成器，收集完整报告列表

        Args:
            report_code: 报告类型编码
            payload: 完整 payload 数据
            preprocessed_data_json: 预处理后的数据 JSON（传给 generator 跳过重复计算）

        Returns:
            报告列表，按 index 排序
        """
        report_map = {}
        log = job_logger or logger

        for event in self.generator.generate_reports_stream(
            payload, report_code, job_logger=job_logger,
            preprocessed_data_json=preprocessed_data_json,
        ):
            event_type = event.get("event")

            if event_type == "report_start":
                idx = event.get("index", len(report_map))
                report_name = event.get("report_name", "")
                report_map[idx] = {
                    "output_name": report_name,
                    "template": event.get("template", ""),
                    "use_ragflow": event.get("use_ragflow", False),
                    "content": "",
                    "citations": [],
                    "error": None,
                }
                log.info("")
                log.info("=" * 60)
                log.info("[报告生成] 开始生成 [%d]: %s", idx + 1, report_name)
                log.info("=" * 60)

            elif event_type == "content":
                idx = event.get("index", 0)
                chunk = event.get("content", "")
                if idx in report_map:
                    report_map[idx]["content"] += chunk

            elif event_type == "citations":
                idx = event.get("index", 0)
                if idx in report_map:
                    report_map[idx]["citations"] = event.get("citations", [])

            elif event_type == "report_end":
                idx = event.get("index", 0)
                if idx in report_map:
                    total = event.get("total", "")
                    if total:
                        report_map[idx]["content"] = total
                    citations = event.get("citations", [])
                    if citations:
                        report_map[idx]["citations"] = citations
                    report_map[idx]["use_ragflow"] = event.get("use_ragflow", report_map[idx]["use_ragflow"])

                    report_name = report_map[idx]["output_name"]
                    content_len = len(report_map[idx]["content"])
                    cite_count = len(report_map[idx]["citations"])
                    log.info("")
                    log.info("=" * 70)
                    log.info("[报告生成] 完成 [%d]: %s", idx + 1, report_name)
                    log.info("[报告生成]   内容长度: %d 字符", content_len)
                    if report_map[idx]["use_ragflow"]:
                        log.info("[报告生成]   知识库引用: %d 条", cite_count)
                    log.info("")
                    log.info("  ┌─────────────────────────────────────────────┐")
                    log.info("  │            报告完整内容                        │")
                    log.info("  └─────────────────────────────────────────────┘")
                    display_content = report_map[idx]["content"][:2000] + ("..." if content_len > 2000 else "")
                    for line in display_content.split('\n'):
                        log.info("  %s", line)
                    log.info("")
                    log.info("=" * 70)
                    log.info("")

            elif event_type == "error":
                idx = event.get("index")
                error_detail = event.get("error", "未知错误")
                report_name = event.get("report_name", "")
                log.info("")
                log.info("[报告生成] [错误] %s: %s", report_name, error_detail)
                if idx is not None and idx in report_map:
                    report_map[idx]["error"] = error_detail
                    report_map[idx]["content"] = f"生成失败: {error_detail}"
                elif idx is not None:
                    report_map[idx] = {
                        "output_name": report_name,
                        "template": event.get("template", ""),
                        "use_ragflow": event.get("use_ragflow", False),
                        "content": f"生成失败: {error_detail}",
                        "citations": [],
                        "error": error_detail,
                    }

        sorted_keys = sorted(report_map.keys())
        return [report_map[k] for k in sorted_keys]

    def _map_to_callback_fields(self, reports: list, job_logger=None) -> dict:
        """
        将报告列表映射到回调字段

        质量概览报告通常只有 1 份，映射到 markdownContent。

        Args:
            reports: 报告列表

        Returns:
            回调字段字典
        """
        log = job_logger or logger

        def _get_content(index: int, fallback_msg: str) -> str:
            if index < len(reports):
                return reports[index].get("content", fallback_msg)
            return fallback_msg

        def _get_citations_json(index: int) -> str:
            if index < len(reports):
                citations = reports[index].get("citations", [])
                return json.dumps(citations, ensure_ascii=False) if citations else ""
            return ""

        result = {
            "markdownContent": _get_content(0, "质量报告生成失败"),
            "summaryMarkdown": _get_content(1, ""),
            "kbReportMarkdown": _get_content(2, ""),
            "knowledgeBasePayload": _get_citations_json(min(2, len(reports) - 1)),
        }

        log.info("[回调字段映射] markdownContent: %d 字", len(result["markdownContent"]))
        return result

    def run_quality_daily_job(self, report_date: str = None, workshop_id: int = None) -> dict:
        """执行质量概览日报生成"""
        return self._run_single_quality_report("daily", report_date, workshop_id)

    def run_quality_weekly_job(self, report_date: str = None, workshop_id: int = None) -> dict:
        """执行质量概览周报生成"""
        return self._run_single_quality_report("weekly", report_date, workshop_id)

    def run_quality_monthly_job(self, report_date: str = None, workshop_id: int = None) -> dict:
        """执行质量概览月报生成"""
        return self._run_single_quality_report("monthly", report_date, workshop_id)

    def run_quality_overview_job(self, report_date: str = None, workshop_id: int = None) -> dict:
        """
        执行质量概览日周月报告生成作业（串行执行三种报告）

        Args:
            report_date: 报告日期/锚点日（可选，不传则上游使用默认值）
            workshop_id: 车间ID（可选，不传则工厂级）

        Returns:
            最后一次执行的结果字典
        """
        results = []
        for report_type in ["daily", "weekly", "monthly"]:
            result = self._run_single_quality_report(report_type, report_date, workshop_id)
            results.append(result)
            if not result.get("success"):
                logger.warning("[质量概览] %s 报告生成失败，继续执行下一个", report_type)

        # 返回最后一个成功的结果，或第一个失败的结果
        for r in results:
            if not r.get("success"):
                return r
        return results[-1] if results else {
            "reportId": None, "success": False, "error": "无报告生成",
            "callbackOk": None, "logFile": "",
        }
