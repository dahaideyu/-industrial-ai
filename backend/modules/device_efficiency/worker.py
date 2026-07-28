# cython: annotation_typing=False, infer_types=False, language_level=3
"""
设备效率报告作业编排器
编排设备效率日/周/月报告的生成流程
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


class DeviceEfficiencyWorker:
    """设备效率报告作业编排器"""

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

    def run_device_efficiency_job(
        self,
        report_date: str = None,
        workshop_id: int = None,
        period_type: str = "day"
    ) -> dict:
        """
        执行设备效率报告生成

        Args:
            report_date: 报告日期，格式 yyyy-MM-dd，默认昨日
            workshop_id: 车间ID（可选，不传则工厂级）
            period_type: 周期类型：day/week/month，默认 day

        Returns:
            {
                "reportId": int,
                "success": bool,
                "error": str or None,
                "callbackOk": bool,
                "logFile": str,
            }
        """
        # 调试日志：打印接收到的参数
        print(f"[DEBUG] run_device_efficiency_job 接收参数:")
        print(f"  report_date: {report_date}")
        print(f"  workshop_id: {workshop_id}")
        print(f"  period_type: {period_type}")

        # 标准化 period_type（兼容 daily/weekly/monthly 和 day/week/month）
        period_type_map = {"daily": "day", "weekly": "week", "monthly": "month"}
        period_type = period_type_map.get(period_type, period_type)

        # 确定报告代码（根据 period_type 和 workshop_id 动态映射）
        period_suffix_map = {"day": "Daily", "week": "Weekly", "month": "Monthly"}
        dimension = "Workshop" if workshop_id else "Factory"
        period_suffix = period_suffix_map.get(period_type, "Daily")
        report_code = f"deviceEfficiency{dimension}{period_suffix}Report"

        print(f"[DEBUG] 映射结果:")
        print(f"  normalized period_type: {period_type}")
        print(f"  dimension: {dimension}")
        print(f"  period_suffix: {period_suffix}")
        print(f"  report_code: {report_code}")

        label = f"设备效率{'车间' if workshop_id else '工厂'}{'日报' if period_type == 'day' else '周报' if period_type == 'week' else '月报'}"

        job_logger = JobLogger(
            job_type=report_code,
            report_date=report_date or datetime.now().strftime("%Y-%m-%d"),
            params={"workshop_id": workshop_id, "period_type": period_type},
        )

        job_logger.print_separator()
        job_logger.info("[Agent 作业开始] %s 生成", label)
        job_logger.info("  report_code: %s", report_code)
        job_logger.info("  workshop_id: %s", workshop_id or "全部（工厂级）")
        job_logger.info("  period_type: %s", period_type)
        job_logger.print_separator()

        report_id = None
        has_error = False
        error_msg = ""
        callback_ok = None
        reports = []

        try:
            # ---- 阶段 1: 拉参 ----
            if not report_date:
                report_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            job_logger.info("[%s] 阶段 1/3: 拉取参数...", label)
            pull_result = self.upstream.pull_device_efficiency_params(
                report_date=report_date,
                workshop_id=workshop_id,
                period_type=period_type
            )
            report_id = pull_result["reportId"]
            payload = pull_result["payload"]
            job_logger.info("  拉参成功, reportId=%s", report_id)
            job_logger.info("  payload keys: %s", list(payload.keys()) if isinstance(payload, dict) else type(payload))

            # 确保 reportCode 正确
            payload.setdefault("reportCode", report_code)

            # ---- 从 payload 提取 period_label（账期） ----
            meta = payload.get("meta", {}) or {}
            period_label = meta.get("periodLabel", meta.get("period", report_date))
            job_logger.info("  账期 (period_label): %s", period_label or "(空)")

            # ---- 打印完整 payload 数据 ----
            job_logger.info("")
            job_logger.info("─" * 70)
            job_logger.info("[拉参结果] 完整 payload 数据:")
            job_logger.info("")
            # 打印完整 payload（格式化 JSON，不分段）
            payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
            job_logger.info("  payload 总长度: %d 字符", len(payload_str))
            for line in payload_str.split('\n'):
                job_logger.info("  %s", line)
            job_logger.info("")
            job_logger.info("─" * 70)
            job_logger.info("")

            # ---- 加载历史报告上下文 ----
            # 日报往前6期，周报往前3期，月报往前3期
            historical_periods_map = {"day": 6, "week": 3, "month": 3}
            hist_periods = historical_periods_map.get(period_type, 6)
            if period_label:
                job_logger.info("[%s] 加载历史报告上下文...", label)
                historical_context = self._load_device_efficiency_historical_context(
                    report_code=report_code,
                    period_label=period_label,
                    periods=hist_periods,
                    workshop_id=workshop_id,
                    job_logger=job_logger,
                )
                if historical_context:
                    # 将历史报告注入 payload 的 meta 中
                    if "meta" not in payload or not isinstance(payload["meta"], dict):
                        payload["meta"] = {}
                    payload["meta"]["historicalContext"] = historical_context
                    job_logger.info("  历史上下文注入完成，长度: %d 字符", len(historical_context))
                else:
                    job_logger.info("  未找到历史报告，跳过注入")

            # ---- 阶段 2: 生成报告 ----
            job_logger.info("[%s] 阶段 2/3: 生成报告...", label)

            # 数据预处理（clean + map-reduce，复用给 generator 和持久化）
            from backend.utils.data_preprocessor import preprocess_payload
            preprocessed_data_json = preprocess_payload(payload)
            job_logger.info("  数据预处理完成，长度: %d 字符", len(preprocessed_data_json))

            reports = self._collect_reports_from_stream(report_code, payload, job_logger=job_logger,
                                                        preprocessed_data_json=preprocessed_data_json)
            total_report_len = sum(len(r.get("content", "")) for r in reports)
            job_logger.info("  报告生成完成, 共 %d 份, 总长度=%d字符", len(reports), total_report_len)

            # ---- 阶段 3: 映射字段 + 回写 ----
            job_logger.info("[%s] 阶段 3/3: 映射回调字段并回写上游...", label)
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
            job_logger.info("  上游回写成功")

            # 持久化到 SQLite
            try:
                meta = payload.get("meta", {}) or {}
                date_type = meta.get("periodType", period_type)
                db.upsert_report(
                    report_code=report_code,
                    title=f"{label} {report_date}",
                    period_label=period_label,
                    request_payload=payload,
                    agent_response_raw=json.dumps({"reports": reports}, ensure_ascii=False),
                    markdown_content=callback_fields.get("markdownContent", ""),
                    summary_markdown=callback_fields.get("summaryMarkdown", ""),
                    kb_report_markdown=callback_fields.get("kbReportMarkdown", ""),
                    knowledge_base_payload=callback_fields.get("knowledgeBasePayload", ""),
                    status=0,
                    error_message="",
                    report_date=report_date,
                    date_type=date_type,
                    workshop_id=workshop_id,
                    agent_response_processed=preprocessed_data_json,
                )
                job_logger.info("  已持久化到 PostgreSQL (workshop_id=%s)", workshop_id)
            except Exception as e:
                job_logger.info("  PostgreSQL 持久化失败: %s", e)

        except Exception as e:
            has_error = True
            error_msg = str(e)
            import traceback
            job_logger.error("[%s] 执行失败: %s\n%s", label, error_msg, traceback.format_exc())

        finally:
            # ========== 控制台汇总输出 ==========
            job_logger.info("")
            job_logger.info("#" * 70)
            job_logger.info("# [Agent 作业完成]")
            job_logger.info("#" * 70)
            job_logger.info("#  报告日期: %s", report_date)
            job_logger.info("#  车间ID: %s", workshop_id or "全部（工厂级）")
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

        return {
            "reportId": report_id,
            "success": not has_error,
            "error": error_msg if has_error else None,
            "callbackOk": callback_ok,
            "logFile": job_logger.get_log_file_path(),
        }

    def _load_device_efficiency_historical_context(
        self,
        report_code: str,
        period_label: str,
        periods: int = 6,
        workshop_id: int = None,
        job_logger=None,
    ) -> str:
        """
        从 SQLite 查询设备效率历史报告上下文
        每个日期只取最新一条记录（去重）

        Args:
            report_code: 报告类型编码（如 deviceEfficiencyFactoryDailyReport）
            period_label: 当前报告账期
            periods: 往前拉取的期数，默认 6
            workshop_id: 车间 ID（None 表示工厂级）
            job_logger: 作业日志器

        Returns:
            历史报告内容字符串，无历史记录时返回空串
        """
        log = job_logger or logger

        log.info("")
        log.info("─" * 70)
        log.info("[设备效率历史报告] 查询参数:")
        log.info("  报告类型: %s", report_code)
        log.info("  当前账期: %s", period_label)
        log.info("  查询期数: %s", periods)
        log.info("  workshop_id: %s", workshop_id or "工厂级")
        log.info("")

        # 按账期去重查询（每个 period_label 只取最新一条）
        records = db.query_reports_distinct_by_period_label(
            report_code=report_code,
            period_label_exclude=period_label,
            workshop_id=workshop_id,
            status=0,
            limit=periods,
        )
        log.info("  找到 %s 个不同账期的历史记录", len(records))

        if records:
            for idx, record in enumerate(records, 1):
                log.info("    [%d] 日期: %s, 状态: %s",
                         idx,
                         record.get("report_date", ""),
                         "成功" if record.get("status") == 0 else "失败")

        if not records:
            log.info("  未找到任何设备效率历史报告记录")
            return ""

        # 按日期倒序拼接历史报告内容（query_reports_distinct_by_date 已包含 markdown_content）
        context_parts = []
        for idx, record in enumerate(records, 1):
            record_date = record.get("report_date", "")
            log.info("  [%d/%d] 处理日期: %s", idx, len(records), record_date)

            if not record_date:
                continue

            content = record.get("markdown_content", "")
            if content:
                log.info("    提取报告内容: %s 字符", len(content))
                context_parts.append(f"### {record_date}\n{content}")

        if not context_parts:
            log.info("  没有可用于拼接的历史报告内容")
            return ""

        historical_context = "\n\n".join(context_parts)
        log.info("[设备效率历史报告] 拼接完成: %d 期, 总长度=%d 字符",
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
                log.info("[报告生成] 开始生成 [%d]: %s", idx + 1, report_name)

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
                    log.info("[报告生成] 完成 [%d]: %s, %d 字符",
                             idx + 1, report_map[idx]["output_name"], len(report_map[idx]["content"]))

            elif event_type == "error":
                idx = event.get("index")
                error_detail = event.get("error", "未知错误")
                report_name = event.get("report_name", "")
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

        设备效率报告通常只有 1 份，映射到 markdownContent。
        若有多份，按 lean_morning_daily 的规则映射。

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

        if len(reports) == 1:
            # 单报告模式：全部映射到 markdownContent
            result = {
                "markdownContent": _get_content(0, "设备效率报告生成失败"),
                "summaryMarkdown": "",
                "kbReportMarkdown": "",
                "knowledgeBasePayload": "",
            }
        else:
            # 多报告模式：按 index 映射
            result = {
                "markdownContent": _get_content(0, "设备效率报告生成失败"),
                "summaryMarkdown": _get_content(1, ""),
                "kbReportMarkdown": _get_content(2, ""),
                "knowledgeBasePayload": _get_citations_json(min(2, len(reports) - 1)),
            }

        log.info("[回调字段映射] markdownContent: %d 字", len(result["markdownContent"]))
        return result
