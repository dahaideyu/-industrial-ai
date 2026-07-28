# cython: annotation_typing=False, infer_types=False, language_level=3
"""
Agent 作业编排器
编排完整作业流：拉参 → 加载历史报告 → 生成多份报告 → 持久化 → 映射回调字段 → 回写上游
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
from backend.services.report_generator import ReportGenerator
from backend.core.job_logger import JobLogger
from backend.core import database as db

logger = logging.getLogger(__name__)


class AgentWorker:
    """精益早会日报作业编排器"""

    _batch_lock = threading.Lock()
    _batch_running = False

    # 工厂级报告锁，防止手动触发和定时调度同时执行
    _factory_report_lock = threading.Lock()

    def __init__(
        self,
        upstream_client: UpstreamClient = None,
        report_generator: ReportGenerator = None,
    ):
        """
        初始化作业编排器

        Args:
            upstream_client: 上游客户端（为 None 时使用全局单例）
            report_generator: 报告生成器（为 None 时使用全局单例）
        """
        self.upstream = upstream_client or get_upstream_client()
        self.generator = report_generator or get_report_generator_singleton()

    def run_lean_morning_daily_job(
        self,
        workshop_id: int,
        procedure_id: int,
        report_date: str = None,
        workshop_name: str = None,
        procedure_name: str = None,
        template_limit: int = None,
    ) -> dict:
        """
        同步执行：拉参 → 加载历史报告 → 生成 3 份报告 → 保存到 SQLite → 映射字段 → 回调上游

        Args:
            workshop_id: 车间 ID
            procedure_id: 工序 ID
            report_date: 报告日期（可选，默认昨日）
            workshop_name: 车间名称（可选，用于日志展示）
            procedure_name: 工序名称（可选，用于日志展示）

        Returns:
            作业结果摘要:
            {
                "success": bool,
                "reportId": int or None,
                "error": str or None,
                "callbackOk": bool or None,
                "reports": list[dict]   # 各报告结果概要
                "logFile": str          # 日志文件路径
            }
        """
        # 创建作业日志器（先使用默认日期，后续会根据实际 report_date 重建）
        job_logger = JobLogger(
            job_type="leanMorningDailyReport",
            report_date=report_date or datetime.now().strftime("%Y-%m-%d"),
            params={"workshop_id": workshop_id, "procedure_id": procedure_id},
        )

        job_logger.info("[AgentWorker] 开始执行精益早会日报作业: workshopId=%s, procedureId=%s, reportDate=%s",
            workshop_id, procedure_id, report_date or "默认昨日"
        )

        upstream_report_id = None

        job_logger.info("")
        job_logger.print_separator()
        job_logger.info("[Agent 作业开始] 精益早会日报生成")
        job_logger.print_separator()
        job_logger.info("  报告日期: %s", report_date)
        if workshop_name:
            job_logger.info("  车间: [%d] %s", workshop_id, workshop_name)
        else:
            job_logger.info("  车间ID: %s", workshop_id)
        if procedure_name:
            job_logger.info("  工序: [%d] %s", procedure_id, procedure_name)
        else:
            job_logger.info("  工序ID: %s", procedure_id)

        # ---- 阶段 1: 拉参 ----
        job_logger.info("")
        job_logger.info("[阶段 1/5] 从上游拉取参数...")
        try:
            pull_result = self.upstream.pull_lean_morning_daily_params(
                workshop_id=workshop_id,
                procedure_id=procedure_id,
                report_date=report_date,
            )
            upstream_report_id = pull_result["reportId"]
            payload = pull_result["payload"]
            job_logger.info("  ✅ 拉参成功")
            job_logger.info("  上游报告ID: %s", upstream_report_id)

            # 傍晚版（T+0）：注入场景标记，帮助 LLM 理解当前是当天白班数据而非昨日全天
            if template_limit is not None and template_limit <= 1:
                meta = payload.get("meta", {}) or {}
                meta["_note"] = "本报告为傍晚版（T+0），数据为当日白班部分数据，供傍晚例会使用。"
                payload["meta"] = meta
                job_logger.info("[AgentWorker] 傍晚版：已注入场景标记到 payload.meta")

            # 输出原始数据内容
            import json
            payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
            job_logger.info("  payload 长度: %d 字符", len(payload_json))
            job_logger.info("")
            job_logger.info("  ┌─────────────────────────────────────────┐")
            job_logger.info("  │           原始数据内容                   │")
            job_logger.info("  └─────────────────────────────────────────┘")
            for line in payload_json.split('\n'):
                job_logger.info("  %s", line)
            job_logger.info("")
        except Exception as e:
            job_logger.error("[AgentWorker] 拉参失败: %s", e, exc_info=True)
            job_logger.info("  ❌ 拉参失败: %s", e)
            return {
                "success": False,
                "reportId": None,
                "error": f"拉参失败: {e}",
                "callbackOk": None,
                "reports": [],
                "logFile": job_logger.get_log_file_path(),
            }

        # 确保报告编码正确
        report_code = payload.get("reportCode", "leanMorningDailyReport")
        payload.setdefault("reportCode", report_code)
        job_logger.info("  报告类型: %s", report_code)

        # 如果 report_date 未传入，从 payload 中提取实际日期，保证 SQLite UNIQUE 约束生效
        if not report_date:
            meta = payload.get("meta", {}) or {}
            report_date = meta.get("period") or meta.get("reportDate") or meta.get("report_date")
            if report_date:
                job_logger.info("[AgentWorker] 从 payload 回写 report_date: %s", report_date)
                job_logger.info("  📅 回写报告日期: %s（从上游拉参数据中提取）", report_date)
            else:
                job_logger.warning("[AgentWorker] 无法从 payload 中提取 report_date，UNIQUE 去重可能失效")

        # 使用实际的 report_date 重建 JobLogger，确保日志目录与报告日期一致
        # 保留旧日志文件中的内容，新的日志会写入新文件
        old_log_file = job_logger.get_log_file_path()
        if report_date and report_date != job_logger.report_date:
            job_logger.info("[AgentWorker] 使用实际 report_date 重建日志器: %s", report_date)
            job_logger = JobLogger(
                job_type="leanMorningDailyReport",
                report_date=report_date,
                params={"workshop_id": workshop_id, "procedure_id": procedure_id},
            )
            job_logger.info("[AgentWorker] 日志器已重建，日志目录: %s", job_logger.get_log_file_path())
            # 将旧日志文件内容复制到新日志文件
            try:
                if os.path.exists(old_log_file):
                    with open(old_log_file, 'r', encoding='utf-8') as f:
                        old_content = f.read()
                    with open(job_logger.get_log_file_path(), 'w', encoding='utf-8') as f:
                        f.write(old_content)
                    job_logger.info("[AgentWorker] 已将旧日志内容复制到新文件")
            except Exception as e:
                job_logger.warning("[AgentWorker] 复制旧日志内容失败: %s", e)

        # ---- 阶段 2: 加载历史报告上下文 ----
        job_logger.info("")
        job_logger.info("[阶段 2/5] 加载历史报告上下文...")

        # template_limit<=1（傍晚版）只生成第1份基础日报，
        # 第1份模板 use_historical_context=false，历史上下文不会被使用，跳过加载
        if template_limit is not None and template_limit <= 1:
            job_logger.info("[AgentWorker] template_limit=%d，跳过历史报告加载（傍晚版仅需基础日报）", template_limit)
            job_logger.info("  ⏭️  傍晚版仅需基础日报，无需历史报告上下文")
        else:
            try:
                historical_content = self._load_historical_context(
                    report_code=report_code,
                    workshop_id=workshop_id,
                    procedure_id=procedure_id,
                    report_date=report_date,
                    job_logger=job_logger,
                )
                if historical_content:
                    payload = self._inject_historical_context(payload, historical_content)
                    job_logger.info("[AgentWorker] 已注入历史报告上下文，长度=%d", len(historical_content))
                    job_logger.info("  ✅ 已注入历史报告，长度: %s 字符", len(historical_content))
                else:
                    job_logger.info("[AgentWorker] 无历史报告上下文")
                    job_logger.info("  ⚠️  无历史报告上下文（首次生成或日期范围内无记录）")
            except Exception as e:
                job_logger.warning("[AgentWorker] 加载历史上下文失败（非致命）: %s", e)
                job_logger.info("  ❌ 加载历史上下文失败: %s", e)

        # ---- 阶段 3: 生成报告 ----
        job_logger.info("")
        job_logger.info("[阶段 3/5] 开始生成报告（共 3 份）...")

        # 数据预处理（clean + map-reduce，复用给 generator 和持久化）
        from backend.utils.data_preprocessor import preprocess_payload
        preprocessed_data_json = preprocess_payload(payload)
        job_logger.info("  数据预处理完成，长度: %d 字符", len(preprocessed_data_json))

        reports = []
        has_critical_error = False
        error_msg = ""

        try:
            reports = self._collect_reports_from_stream(report_code, payload, job_logger=job_logger, template_limit=template_limit,
                                                        preprocessed_data_json=preprocessed_data_json)
            total_report_len = sum(len(r.get("content", "")) for r in reports)
            job_logger.info("  报告总长度: %d 字符", total_report_len)

            # 傍晚版后处理：修正 LLM 生成的"早会日报"标题为"傍晚版日报"
            if template_limit is not None and template_limit <= 1:
                for report in reports:
                    content = report.get("content", "")
                    if not content:
                        continue
                    content = content.replace(
                        "精益改善早会日报数据分析报告",
                        "精益改善日报数据分析报告（傍晚版）"
                    )
                    content = content.replace(
                        "精益改善早会日报",
                        "精益改善日报（傍晚版）"
                    )
                    report["content"] = content
                job_logger.info("[AgentWorker] 傍晚版：已完成报告标题后处理")
        except Exception as e:
            job_logger.error("[AgentWorker] 报告生成失败: %s", e, exc_info=True)
            has_critical_error = True
            error_msg = str(e)
            job_logger.info("")
            job_logger.info("  ❌ 报告生成异常: %s", e)

        # ---- 阶段 4: 映射回调字段 + 持久化 ----
        job_logger.info("")
        job_logger.info("[阶段 4/5] 映射回调字段并持久化到 SQLite...")
        callback_fields = {}
        try:
            callback_fields = self._map_to_callback_fields(reports, job_logger=job_logger, template_limit=template_limit)
            job_logger.info("  ✅ 回调字段映射完成")
        except Exception as e:
            job_logger.error("[AgentWorker] 映射回调字段失败: %s", e, exc_info=True)
            job_logger.info("  ❌ 映射回调字段失败: %s", e)
            if not error_msg:
                error_msg = str(e)

        # 构建回调结构体（SQLite 和上游共用同一份）
        callback_status = "1" if has_critical_error else "0"
        agent_response_raw = json.dumps({
            "reportId": upstream_report_id,
            "status": callback_status,
            "markdownContent": callback_fields.get("markdownContent", ""),
            "kbReportMarkdown": callback_fields.get("kbReportMarkdown", ""),
            "knowledgeBasePayload": callback_fields.get("knowledgeBasePayload", ""),
            "summaryMarkdown": callback_fields.get("summaryMarkdown", ""),
            "agentResponseRaw": json.dumps({"reports": reports}, ensure_ascii=False),
            "errorMessage": error_msg,
        }, ensure_ascii=False)

        # 持久化到 SQLite
        try:
            status = 1 if has_critical_error else 0

            # 提取业务字段
            meta = payload.get("meta", {}) or {}
            period_label = meta.get("periodLabel", meta.get("period", ""))
            date_type = meta.get("periodType", meta.get("dateType", "day"))

            db.upsert_report(
                report_code=report_code,
                title=f"精益早会日报 {period_label}",
                period_label=period_label,
                request_payload=payload,
                agent_response_raw=agent_response_raw,
                markdown_content=callback_fields.get("markdownContent", ""),
                summary_markdown=callback_fields.get("summaryMarkdown", ""),
                kb_report_markdown=callback_fields.get("kbReportMarkdown", ""),
                knowledge_base_payload=callback_fields.get("knowledgeBasePayload", ""),
                status=status,
                error_message=error_msg,
                workshop_id=workshop_id,
                date_type=date_type,
                procedure_id=procedure_id,
                report_date=report_date,
                agent_response_processed=preprocessed_data_json,
            )
            job_logger.info("[AgentWorker] 报告已持久化到 SQLite")
            job_logger.info("  ✅ SQLite 持久化完成")
        except Exception as e:
            job_logger.error("[AgentWorker] 持久化失败（非致命）: %s", e, exc_info=True)
            job_logger.info("  ❌ SQLite 持久化失败: %s", e)

        # ---- 阶段 5: 回调上游 ----
        job_logger.info("")
        job_logger.info("[阶段 5/5] 回调上游系统...")
        callback_ok = None
        try:
            self.upstream.callback_complete(
                report_id=upstream_report_id,
                status=callback_status,
                markdown_content=callback_fields.get("markdownContent", ""),
                summary_markdown=callback_fields.get("summaryMarkdown", ""),
                kb_report_markdown=callback_fields.get("kbReportMarkdown", ""),
                knowledge_base_payload=callback_fields.get("knowledgeBasePayload", ""),
                agent_response_raw=json.dumps({"reports": reports}, ensure_ascii=False),
                error_message=error_msg,
            )
            callback_ok = True
            job_logger.info("[AgentWorker] 回调上游成功")
            job_logger.info("  ✅ 上游回调成功")
        except Exception as e:
            callback_ok = False
            job_logger.error("[AgentWorker] 回调上游失败: %s", e, exc_info=True)
            job_logger.info("  ❌ 上游回调失败: %s", e)

        # ---- 汇总结果 ----
        result = {
            "success": not has_critical_error,
            "reportId": upstream_report_id,
            "reportDate": report_date,  # 返回实际使用的 report_date
            "error": error_msg or None,
            "callbackOk": callback_ok,
            "reports": [
                {
                    "output_name": r.get("output_name", ""),
                    "content": r.get("content", ""),
                    "content_length": len(r.get("content", "")),
                    "has_error": bool(r.get("error")),
                }
                for r in reports
            ],
            "logFile": job_logger.get_log_file_path(),
        }

        # ========== 控制台汇总输出 ==========
        job_logger.info("")
        job_logger.info("#" * 70)
        job_logger.info("# [Agent 作业完成]")
        job_logger.info("#" * 70)
        job_logger.info("#  报告日期: %s", report_date)
        job_logger.info("#  车间ID: %s", workshop_id)
        job_logger.info("#  工序ID: %s", procedure_id)
        job_logger.info("#  上游报告ID: %s", upstream_report_id)
        job_logger.info("#  生成状态: %s", "✅ 成功" if not has_critical_error else "❌ 失败")
        job_logger.info("#  回调状态: %s", "✅ 成功" if callback_ok else "❌ 失败")
        job_logger.info("#  生成报告数: %s 份", len(reports))
        for i, r in enumerate(reports, 1):
            status = "❌" if r.get("error") else "✅"
            job_logger.info("#    [%d] %s %s (%d 字符)", i, status, r.get("output_name", ""), len(r.get("content", "")))
        job_logger.info("#  日志文件: %s", job_logger.get_log_file_path())
        job_logger.info("#" * 70)
        job_logger.info("")

        job_logger.info("[AgentWorker] 作业完成: %s", result)
        return result

    def _load_historical_context(
        self,
        report_code: str,
        workshop_id: int,
        procedure_id: int,
        report_date: str,
        days: int = 6,
        job_logger=None,
    ) -> str:
        """
        从 SQLite 查询前 N 天的同维度历史报告，按日期倒序拼接
        每个日期只取最新一条记录（去重）

        查询范围：report_date 前第 1 天到前第 N 天（不含当天），
        将各日报告的第一份报告（日会早报）内容按日期倒序拼接返回。

        Args:
            report_code: 报告类型编码
            workshop_id: 车间 ID
            procedure_id: 工序 ID
            report_date: 当前报告日期（YYYY-MM-DD）
            days: 往前拉取天数，默认 6

        Returns:
            历史报告内容字符串，无历史记录时返回空串
        """
        # 使用传入的 job_logger 或降级到默认 logger
        log = job_logger or logger

        # 计算日期范围：前 days 天到前 1 天
        try:
            current_date = datetime.strptime(report_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            log.warning("[AgentWorker] report_date 格式无效: %s，无法计算日期范围", report_date)
            log.info("  ⚠️  历史报告查询失败: report_date 格式无效: %s", report_date)
            return ""

        date_from = (current_date - timedelta(days=days)).strftime("%Y-%m-%d")
        date_to = report_date  # 不含当天

        log.info(
            "[AgentWorker] 查询历史报告范围: %s ~ %s (不含), reportCode=%s, workshopId=%s, procedureId=%s",
            date_from, date_to, report_code, workshop_id, procedure_id
        )
        log.info("")
        log.info("─" * 70)
        log.info("[历史报告] 查询参数:")
        log.info("  报告类型: %s", report_code)
        log.info("  车间ID: %s", workshop_id)
        log.info("  工序ID: %s", procedure_id)
        log.info("  日期范围: %s ~ %s (不含)", date_from, date_to)
        log.info("  查询天数: %s 天", days)
        log.info("")

        # 按日期去重查询同维度记录（每个日期只取最新一条）
        log.info("[历史报告] 执行数据库查询（按日期去重）...")
        records = db.query_reports_distinct_by_date(
            report_code=report_code,
            workshop_id=workshop_id,
            procedure_id=procedure_id,
            report_date_from=date_from,
            report_date_to=date_to,
            status=0,
            limit=days,
        )

        log.info("  查询结果: 找到 %s 个不同日期的历史记录", len(records))

        if not records:
            log.info("  ⚠️  未找到任何历史报告记录")
            return ""

        # 按日期倒序拼接报告内容（query_reports_distinct_by_date 已包含 markdown_content）
        context_parts = []
        for idx, record in enumerate(records, 1):
            record_date = record.get("report_date", "")
            log.info("")
            log.info("  [%d/%d] 处理日期: %s", idx, len(records), record_date)

            if not record_date:
                log.info("    ⚠️  记录中无 report_date 字段，跳过")
                continue

            content = record.get("markdown_content", "")
            if content:
                log.info("    ✅ 提取报告内容: %s 字符", len(content))
                log.info("")
                log.info("    ┌─────────────────────────────────────────────┐")
                log.info("    │         历史报告内容（%s）              │", record_date)
                log.info("    └─────────────────────────────────────────────┘")
                # 输出报告内容（前 1000 字符，避免日志过长）
                display_content = content[:1000] + ("..." if len(content) > 1000 else "")
                for line in display_content.split('\n'):
                    log.info("    %s", line)
                log.info("")

            if content:
                context_parts.append(f"### {record_date}\n{content}")

        if not context_parts:
            log.info("  ⚠️  没有可用于拼接的历史报告内容")
            log.info("─" * 70)
            log.info("")
            return ""

        historical_context = "\n\n".join(context_parts)
        log.info(
            "[AgentWorker] 拼接历史报告: %d 天, 总长度=%d 字符",
            len(context_parts), len(historical_context)
        )
        log.info("")
        log.info("  %s", "─" * 68)
        log.info("  [历史报告] 汇总:")
        log.info("    成功提取: %s 份报告", len(context_parts))
        log.info("    总字符数: %s", len(historical_context))
        log.info("    报告日期: %s", ", ".join([p.split(chr(10))[0].replace('### ', '') for p in context_parts]))
        log.info("  %s", "─" * 68)
        log.info("")

        return historical_context

    def _inject_historical_context(self, payload: dict, historical_content: str) -> dict:
        """
        将历史报告内容注入 payload['meta']['historicalContext']

        Args:
            payload: 原始 payload
            historical_content: 历史报告内容

        Returns:
            注入后的 payload（原地修改并返回）
        """
        if "meta" not in payload or not isinstance(payload["meta"], dict):
            payload["meta"] = {}
        payload["meta"]["historicalContext"] = historical_content
        return payload

    def _load_factory_historical_context(
        self,
        report_date: str,
        days: int = 6,
        job_logger=None
    ) -> str:
        """
        从 SQLite 查询工厂级历史报告，按日期倒序拼接
        每个日期只取最新一条记录（去重），与工序级逻辑保持一致

        Args:
            report_date: 当前报告日期（YYYY-MM-DD）
            days: 往前拉取天数，默认 6
            job_logger: 作业日志器

        Returns:
            历史工厂报告内容字符串，无历史记录时返回空串
        """
        log = job_logger or logger

        # 计算日期范围：前 days 天到前 1 天
        try:
            current_date = datetime.strptime(report_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            log.warning("[工厂历史报告] report_date 格式无效: %s，无法计算日期范围", report_date)
            return ""

        date_from = (current_date - timedelta(days=days)).strftime("%Y-%m-%d")
        date_to = report_date  # 不含当天

        log.info("")
        log.info("=" * 70)
        log.info("[工厂历史报告] 开始加载历史报告上下文")
        log.info("=" * 70)
        log.info("  报告类型: factoryMorningDailyReport")
        log.info("  车间ID: 0 (工厂级)")
        log.info("  工序ID: 0 (工厂级)")
        log.info("  报告日期: %s", report_date)
        log.info("  查询天数: %s 天", days)
        log.info("  日期范围: %s ~ %s (不含当天)", date_from, date_to)
        log.info("")

        # 按日期去重查询工厂级记录（每个日期只取最新一条，与工序级逻辑一致）
        log.info("[工厂历史报告] 执行数据库查询（按日期去重）...")
        records = db.query_reports_distinct_by_date(
            report_code='factoryMorningDailyReport',
            workshop_id=0,
            procedure_id=0,
            report_date_from=date_from,
            report_date_to=date_to,
            status=0,
            limit=days,
        )

        log.info("[工厂历史报告] 查询结果: 找到 %s 个不同日期的历史记录", len(records))

        if not records:
            log.info("[工厂历史报告] 无历史记录，跳过加载")
            log.info("=" * 70)
            return ""

        # 显示找到的历史记录
        log.info("")
        log.info("  ┌─────────────────────────────────────────────┐")
        log.info("  │         找到的历史记录                        │")
        log.info("  └─────────────────────────────────────────────┘")
        for idx, record in enumerate(records, 1):
            record_date_str = record.get("report_date", "")
            record_status = "成功" if record.get("status") == 0 else "失败"
            log.info("  [%d] 日期: %s, 状态: %s", idx, record_date_str, record_status)
        log.info("")

        # 按日期倒序拼接报告内容（query_reports_distinct_by_date 已包含 markdown_content）
        context_parts = []
        for idx, record in enumerate(records, 1):
            record_date_str = record.get("report_date", "")
            log.info("[工厂历史报告] 处理第 %d/%d 条记录: %s", idx, len(records), record_date_str)

            if not record_date_str:
                log.info("  ⚠️  记录中无 report_date 字段，跳过")
                continue

            content = record.get("markdown_content", "")
            if content:
                log.info("  ✅ 提取报告内容: %d 字符", len(content))
                log.info("")
                log.info("  ┌─────────────────────────────────────────────┐")
                log.info("  │         历史工厂报告完整内容（%s）            │", record_date_str)
                log.info("  └─────────────────────────────────────────────┘")
                # 输出报告内容（前 1000 字符，避免日志过长）
                display_content = content[:1000] + ("..." if len(content) > 1000 else "")
                for line in display_content.split('\n'):
                    log.info("  %s", line)
                log.info("")
                context_parts.append(f"### {record_date_str}\n{content}")
            else:
                log.info("  ⚠️  报告内容为空，跳过")

        log.info("")
        log.info("[工厂历史报告] 处理完成:")
        log.info("  成功提取: %d 份报告", len(context_parts))

        if not context_parts:
            log.info("  结果: 没有可用于拼接的历史报告内容")
            log.info("=" * 70)
            return ""

        historical_context = "\n\n".join(context_parts)
        log.info("  总字符数: %d 字符", len(historical_context))
        log.info("  报告日期: %s", ", ".join([p.split("\n")[0].replace("### ", "") for p in context_parts]))
        log.info("")
        log.info("[工厂历史报告] ✅ 历史报告上下文加载完成")
        log.info("=" * 70)

        return historical_context

    def _load_quality_historical_context(
        self,
        report_code: str,
        period_label: str,
        periods: int = 6,
        job_logger=None
    ) -> str:
        """
        从 SQLite 查询质量报告历史上下文

        Args:
            report_code: 报告类型编码（qualityDailyReport/qualityWeeklyReport/qualityMonthlyReport）
            period_label: 当前报告账期（meta.period 值，如 YYYY-MM-DD 或 YYYY-MM-dd~YYYY-MM-dd 或 YYYY-MM）
            periods: 往前拉取的周期数，默认 6
            job_logger: 作业日志器

        Returns:
            历史报告内容字符串，无历史记录时返回空串
        """
        log = job_logger or logger
        label_map = {
            "qualityDailyReport": "质量日报",
            "qualityWeeklyReport": "质量周报",
            "qualityMonthlyReport": "质量月报",
        }
        label = label_map.get(report_code, report_code)

        log.info("")
        log.info("─" * 70)
        log.info("[质量历史报告] 查询参数:")
        log.info("  报告类型: %s (%s)", label, report_code)
        log.info("  当前账期: %s", period_label)
        log.info("  查询周期数: %s", periods)
        log.info("")

        # 查询历史记录（按 period_label 降序，排除当前账期，取前 N 条）
        records = db.query_quality_historical_reports(
            report_code=report_code,
            period_label=period_label,
            periods=periods,
        )
        log.info("  找到 %s 条历史记录", len(records))

        if records:
            for idx, record in enumerate(records, 1):
                log.info("    [%d] 周期: %s, 状态: %s",
                        idx,
                        record.get("period_label", record.get("report_date", "")),
                        "成功" if record.get("status") == 0 else "失败")

        if not records:
            log.info("  ⚠️  未找到任何%s历史报告记录", label)
            return ""

        # 按日期倒序获取各报告内容并拼接
        context_parts = []
        for idx, record in enumerate(records, 1):
            record_date = record.get("report_date", "")
            record_period = record.get("period_label", record_date)
            log.info("  [%d/%d] 处理周期: %s", idx, len(records), record_period)

            if not record_date:
                log.info("    ⚠️  记录中无 report_date 字段，跳过")
                continue

            # 获取报告详情
            detail = db.get_report_detail(
                report_code=report_code,
                report_date=record_date,
            )
            if not detail:
                log.info("    ❌ 未查询到该周期的报告详情，跳过")
                continue

            content = detail.get("markdown_content", "")
            if not content:
                log.info("    ⚠️  报告详情中无 markdown_content 字段，跳过")
                continue

            context_parts.append(f"### {record_period}\n{content}")

        if not context_parts:
            log.info("  ⚠️  没有可用于拼接的历史报告内容")
            return ""

        historical_context = "\n\n".join(context_parts)
        log.info("[质量历史报告] 拼接完成: %d 份, 总长度=%d 字符",
                len(context_parts), len(historical_context))

        return historical_context

    def _generate_factory_level_reports(
        self,
        all_workshop_reports: list,
        report_date: str,
        template_limit: int = None,
    ) -> dict:
        """
        生成工厂级汇总报告（3份）

        Args:
            all_workshop_reports: 所有工序生成的报告列表，每个元素包含 workshopId, workshopName, procedureId, procedureName, report1Content
            report_date: 报告日期（可选，为空时默认昨日）

        Returns:
            工厂级报告生成结果字典
        """
        # 确保 report_date 不为空，为空时默认使用昨天的日期
        if not report_date:
            report_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            print(f"[工厂级报告] report_date 为空，使用默认值: {report_date}")

        # 防重入：同一时刻只允许一个工厂级报告生成任务运行
        acquired = AgentWorker._factory_report_lock.acquire(blocking=False)
        if not acquired:
            warning_msg = f"已有工厂级报告生成任务正在执行（日期: {report_date}），本次触发已跳过"
            print(f"\n  ⚠️  {warning_msg}")
            logger.warning("[AgentWorker] %s", warning_msg)
            return {
                "success": False,
                "error": warning_msg,
                "reports": [],
            }

        try:
            return self._generate_factory_level_reports_impl(
                all_workshop_reports=all_workshop_reports,
                report_date=report_date,
                template_limit=template_limit,
            )
        finally:
            AgentWorker._factory_report_lock.release()
            logger.info("[AgentWorker] 工厂级报告锁已释放")

    def _generate_factory_level_reports_impl(
        self,
        all_workshop_reports: list,
        report_date: str,
        template_limit: int = None,
    ) -> dict:
        """
        工厂级报告生成的实际实现
        """
        # 创建工厂级报告专用的日志器
        job_logger = JobLogger(
            job_type="factoryMorningDailyReport",
            report_date=report_date,
            params={"workshop_count": len(all_workshop_reports)},
        )

        job_logger.info("")
        job_logger.print_separator()
        job_logger.info("[工厂级报告] 开始生成工厂级早会日报")
        job_logger.print_separator()
        job_logger.info("  报告日期: %s", report_date)
        job_logger.info("  成功工序数: %d", len(all_workshop_reports))
        job_logger.info("")

        try:
            # 1. 加载工厂级历史报告上下文
            job_logger.info("[阶段 1/4] 加载工厂级历史报告上下文...")
            historical_context = self._load_factory_historical_context(
                report_date=report_date,
                days=6,
                job_logger=job_logger,
            )
            job_logger.info("  ✅ 历史上下文加载完成，长度: %s 字符", len(historical_context))

            # 2. 生成 3 份工厂级报告
            job_logger.info("")
            job_logger.info("[阶段 2/4] 生成工厂级报告（共 3 份）...")
            job_logger.info("")
            job_logger.info("  ┌─────────────────────────────────────────────┐")
            job_logger.info("  │         工厂级报告输入数据汇总                  │")
            job_logger.info("  └─────────────────────────────────────────────┘")
            job_logger.info("  工序报告数量: %d 份", len(all_workshop_reports))
            if len(all_workshop_reports) > 0:
                # 按车间分组统计
                workshop_groups = {}
                for r in all_workshop_reports:
                    wid = r.get('workshopId', '未知')
                    wname = r.get('workshopName', '未知车间')
                    key = f"{wid}-{wname}"
                    if key not in workshop_groups:
                        workshop_groups[key] = []
                    workshop_groups[key].append(r)

                job_logger.info("  涉及车间数: %d 个", len(workshop_groups))
                job_logger.info("")
                job_logger.info("  各车间工序报告统计:")
                for key, reports in workshop_groups.items():
                    parts = key.split('-', 1)
                    wname = parts[1] if len(parts) > 1 else key
                    total_len = sum(len(r.get('report1Content', '')) for r in reports)
                    job_logger.info("    - %s: %d 份报告, 总长度 %d 字符", wname, len(reports), total_len)

            # 展示第1份报告的一小段内容作为预览
            if len(all_workshop_reports) > 0:
                first_report = all_workshop_reports[0]
                sample_content = first_report.get('report1Content', '')[:200]
                job_logger.info("")
                job_logger.info("  第1份工序报告样本（前200字）:")
                for line in sample_content.split('\n')[:5]:
                    job_logger.info("    %s", line)
            job_logger.info("")
            job_logger.info("=" * 70)
            job_logger.info("")

            reports = []
            report_map = {}

            for event in self.generator.generate_factory_reports_stream(
                all_workshop_reports=all_workshop_reports,
                report_date=report_date,
                historical_context=historical_context,
                job_logger=job_logger,
                template_limit=template_limit,
            ):
                event_type = event.get("event")

                if event_type == "report_start":
                    idx = event.get("index", len(report_map))
                    report_name = event.get("output_name", "")
                    report_map[idx] = {
                        "output_name": report_name,
                        "content": "",
                        "citations": [],
                        "error": None,
                    }
                    job_logger.info("")
                    job_logger.info("=" * 60)
                    job_logger.info("[工厂报告] 开始生成 [%d]: %s", idx+1, report_name)
                    job_logger.info("=" * 60)

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

                        report_name = report_map[idx]["output_name"]
                        content = report_map[idx]["content"]
                        content_len = len(content)
                        cite_count = len(report_map[idx]["citations"])
                        job_logger.info("")
                        job_logger.info("=" * 70)
                        job_logger.info("[工厂报告] 完成 [%d]: %s", idx+1, report_name)
                        job_logger.info("[工厂报告]   内容长度: %d 字符", content_len)
                        if cite_count > 0:
                            job_logger.info("[工厂报告]   知识库引用: %d 条", cite_count)
                        job_logger.info("")
                        job_logger.info("  ┌─────────────────────────────────────────────┐")
                        job_logger.info("  │            报告完整内容                        │")
                        job_logger.info("  └─────────────────────────────────────────────┘")
                        # 输出完整报告内容
                        for line in content.split('\n'):
                            job_logger.info("  %s", line)
                        job_logger.info("")
                        job_logger.info("=" * 70)
                        job_logger.info("")

                elif event_type == "error":
                    idx = event.get("index")
                    error_detail = event.get("error", "未知错误")
                    report_name = event.get("report_name", "")
                    job_logger.info("")
                    job_logger.info("[工厂报告] [错误] %s: %s", report_name, error_detail)
                    if idx is not None and idx in report_map:
                        report_map[idx]["error"] = error_detail
                        report_map[idx]["content"] = f"生成失败: {error_detail}"

            # 按 index 排序获取报告列表
            sorted_keys = sorted(report_map.keys())
            reports = [report_map[k] for k in sorted_keys]

            # 3. 持久化到 SQLite
            job_logger.info("")
            job_logger.info("[阶段 3/4] 持久化工厂级报告到 SQLite...")

            # 映射回调字段
            def _get_content(index: int, fallback_msg: str) -> str:
                if index < len(reports):
                    return reports[index].get("content", fallback_msg)
                return fallback_msg

            def _get_citations_json(index: int) -> str:
                if index < len(reports):
                    citations = reports[index].get("citations", [])
                    return json.dumps(citations, ensure_ascii=False) if citations else ""
                return ""

            callback_fields = {
                "markdownContent": _get_content(0, "工厂早会汇总生成失败"),
                "summaryMarkdown": _get_content(1, "工厂趋势分析生成失败"),
                "kbReportMarkdown": _get_content(2, "工厂改善建议生成失败"),
                "knowledgeBasePayload": _get_citations_json(2),
            }

            # 打印知识库引用详情（参考工序级日志）
            citations2 = reports[2].get("citations", []) if len(reports) > 2 else []
            job_logger.info("")
            job_logger.info("[工厂报告] 第3份报告（知识库引用）citations: %d 条", len(citations2))
            if citations2:
                job_logger.info("[工厂报告] 第3份报告引用详情:")
                for i, cite in enumerate(citations2[:5]):  # 最多显示前5条
                    job_logger.info("  [%d] %s", i+1, cite.get('source', '未知来源'))

            job_logger.info("[工厂报告] markdownContent: %d 字", len(callback_fields['markdownContent']))
            job_logger.info("[工厂报告] summaryMarkdown: %d 字", len(callback_fields['summaryMarkdown']))
            job_logger.info("[工厂报告] kbReportMarkdown: %d 字", len(callback_fields['kbReportMarkdown']))
            job_logger.info("[工厂报告] knowledgeBasePayload: %d 字符", len(callback_fields['knowledgeBasePayload']))

            # 构建 agent_response_raw
            agent_response_raw = json.dumps({"reports": reports}, ensure_ascii=False)

            # 将所有工序报告拼接后的完整内容输出到日志
            job_logger.info("")
            job_logger.info("=" * 70)
            job_logger.info("📋 所有工序报告拼接内容（工厂级日报输入数据）")
            job_logger.info("=" * 70)
            for idx, report in enumerate(all_workshop_reports, 1):
                workshop_name = report.get('workshopName', '未知车间')
                procedure_name = report.get('procedureName', '未知工序')
                report_content = report.get('report1Content', '无内容')
                job_logger.info("")
                job_logger.info("--- 报告 %d: %s - %s ---", idx, workshop_name, procedure_name)
                job_logger.info("  内容长度: %d 字符", len(report_content))
                # 输出完整报告内容
                for line in report_content.split('\n'):
                    job_logger.info("  %s", line)
            job_logger.info("")
            job_logger.info("=" * 70)
            job_logger.info("")

            # 使用 workshop_id=0, procedure_id=0 表示工厂级报告
            record_id = db.upsert_report(
                report_code='factoryMorningDailyReport',
                title=f"工厂级早会日报 {report_date}",
                period_label=report_date,
                request_payload={
                    "reportDate": report_date,
                    "workshopCount": len(all_workshop_reports),
                    "workshopReports": all_workshop_reports,
                },
                agent_response_raw=agent_response_raw,
                markdown_content=callback_fields.get("markdownContent", ""),
                summary_markdown=callback_fields.get("summaryMarkdown", ""),
                kb_report_markdown=callback_fields.get("kbReportMarkdown", ""),
                knowledge_base_payload=callback_fields.get("knowledgeBasePayload", ""),
                status=0,
                error_message="",
                workshop_id=0,
                date_type="day",
                procedure_id=0,
                report_date=report_date,
            )

            job_logger.info("  ✅ 工厂级报告持久化完成，记录 ID: %s", record_id)

            # 汇总结果
            result = {
                "success": True,
                "reportId": record_id,
                "reports": reports,
                "logFile": job_logger.get_log_file_path(),
            }

            # 4. 回调上游系统（成功场景）
            job_logger.info("")
            job_logger.info("[阶段 4/4] 回调上游系统...")
            job_logger.info("  回调报告类型: leanMorningDailyReport (工厂级汇总)")
            job_logger.info("  报告日期: %s", report_date)
            job_logger.info("  标题: 工厂级早会日报 %s", report_date)

            try:
                callback_result = self.upstream.callback_factory_summary(
                    report_code="leanMorningDailyReport",
                    period_label=report_date,
                    report_date=report_date,
                    status="0",
                    markdown_content=callback_fields.get("markdownContent", ""),
                    title=f"工厂级早会日报 {report_date}",
                    summary_markdown=callback_fields.get("summaryMarkdown", ""),
                    kb_report_markdown=callback_fields.get("kbReportMarkdown", ""),
                    knowledge_base_payload=callback_fields.get("knowledgeBasePayload", ""),
                    agent_response_raw=agent_response_raw,
                    date_type="day",
                    request_payload=json.dumps({
                        "reportDate": report_date,
                        "workshopCount": len(all_workshop_reports),
                        "source": "factorySummary"
                    }, ensure_ascii=False),
                    error_message="",
                )

                upstream_report_id = callback_result.get("data", {}).get("reportId")
                job_logger.info("")
                job_logger.info("  ┌─────────────────────────────────────────────┐")
                job_logger.info("  │            回调结果                           │")
                job_logger.info("  └─────────────────────────────────────────────┘")
                job_logger.info("  状态: ✅ 成功")
                job_logger.info("  上游 reportId: %s", upstream_report_id)
                job_logger.info("  回调响应完整内容: %s", json.dumps(callback_result, ensure_ascii=False))
                job_logger.info("")
                result["upstreamReportId"] = upstream_report_id

            except Exception as e:
                job_logger.error("[工厂报告] 回调上游失败（非致命）: %s", e, exc_info=True)
                job_logger.info("")
                job_logger.info("  ┌─────────────────────────────────────────────┐")
                job_logger.info("  │            回调结果                           │")
                job_logger.info("  └─────────────────────────────────────────────┘")
                job_logger.info("  状态: ⚠️  失败（非致命，不影响本地结果）")
                job_logger.info("  错误信息: %s", str(e))
                job_logger.info("")

            job_logger.info("")
            job_logger.info("#" * 70)
            job_logger.info("# [工厂级报告] 生成完成")
            job_logger.info("#" * 70)
            job_logger.info("#  报告日期: %s", report_date)
            job_logger.info("#  生成状态: ✅ 成功")
            job_logger.info("#  生成报告数: %s 份", len(reports))
            for i, r in enumerate(reports, 1):
                status = "❌" if r.get("error") else "✅"
                job_logger.info("#    [%d] %s %s (%d 字符)", i, status, r.get("output_name", ""), len(r.get("content", "")))
            job_logger.info("#  日志文件: %s", job_logger.get_log_file_path())
            job_logger.info("#" * 70)
            job_logger.info("")

            return result

        except Exception as e:
            error_msg = str(e)
            job_logger.error("[工厂级报告] 生成失败: %s", error_msg, exc_info=True)
            job_logger.info("")
            job_logger.info("#" * 70)
            job_logger.info("# [工厂级报告] 生成失败")
            job_logger.info("#" * 70)
            job_logger.info("#  报告日期: %s", report_date)
            job_logger.info("#  错误信息: %s", error_msg)
            job_logger.info("#  日志文件: %s", job_logger.get_log_file_path())
            job_logger.info("#" * 70)
            job_logger.info("")

            # 失败时也要回调上游（status=1）
            job_logger.info("[工厂级报告] 执行失败场景回调上游...")
            job_logger.info("  回调报告类型: leanMorningDailyReport (工厂级汇总)")
            job_logger.info("  报告日期: %s", report_date)
            job_logger.info("  状态码: 1 (失败)")
            try:
                callback_result = self.upstream.callback_factory_summary(
                    report_code="leanMorningDailyReport",
                    period_label=report_date,
                    report_date=report_date,
                    status="1",
                    error_message=error_msg,
                )
                upstream_report_id = callback_result.get("data", {}).get("reportId", "N/A")
                job_logger.info("")
                job_logger.info("  ┌─────────────────────────────────────────────┐")
                job_logger.info("  │            失败回调结果                        │")
                job_logger.info("  └─────────────────────────────────────────────┘")
                job_logger.info("  状态: ✅ 回调成功")
                job_logger.info("  上游 reportId: %s", upstream_report_id)
                job_logger.info("")
            except Exception as callback_error:
                job_logger.error("[工厂级报告] 失败场景回调失败: %s", callback_error, exc_info=True)
                job_logger.info("")
                job_logger.info("  ┌─────────────────────────────────────────────┐")
                job_logger.info("  │            失败回调结果                        │")
                job_logger.info("  └─────────────────────────────────────────────┘")
                job_logger.info("  状态: ❌ 回调失败")
                job_logger.info("  错误: %s", str(callback_error))
                job_logger.info("")

            return {
                "success": False,
                "error": error_msg,
                "reports": [],
                "logFile": job_logger.get_log_file_path(),
            }

    def _collect_reports_from_stream(
        self, report_code: str, payload: dict, job_logger=None, template_limit: int = None,
        preprocessed_data_json: str = None,
    ) -> list:
        """
        消费 generate_reports_stream() 生成器，收集完整报告列表

        使用字典按 index 跟踪多份报告，避免并发 report_start 事件互相覆盖。

        Args:
            report_code: 报告类型编码
            payload: 完整 payload 数据
            preprocessed_data_json: 预处理后的数据 JSON（传给 generator 跳过重复计算）

        Returns:
            报告列表，按 index 排序，每份报告:
            {
                "output_name": str,
                "template": str,
                "content": str,
                "citations": list,
                "use_ragflow": bool,
                "error": str or None
            }
        """
        # 按 index 存储进行中的报告
        report_map = {}
        log = job_logger or logger

        for event in self.generator.generate_reports_stream(
            payload, report_code, job_logger=job_logger, template_limit=template_limit,
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
                log.info("[报告生成] 开始生成 [%d]: %s", idx+1, report_name)
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
                    # 用 report_end 中的 total 作为权威内容
                    total = event.get("total", "")
                    if total:
                        report_map[idx]["content"] = total
                    # 用 report_end 中的 citations 作为权威引用
                    citations = event.get("citations", [])
                    if citations:
                        report_map[idx]["citations"] = citations
                    report_map[idx]["use_ragflow"] = event.get("use_ragflow", report_map[idx]["use_ragflow"])

                    # 打印报告完成信息
                    report_name = report_map[idx]["output_name"]
                    content_len = len(report_map[idx]["content"])
                    cite_count = len(report_map[idx]["citations"])
                    log.info("")
                    log.info("=" * 70)
                    log.info("[报告生成] 完成 [%d]: %s", idx+1, report_name)
                    log.info("[报告生成]   内容长度: %d 字符", content_len)
                    if report_map[idx]["use_ragflow"]:
                        log.info("[报告生成]   知识库引用: %d 条", cite_count)
                    log.info("")
                    log.info("  ┌─────────────────────────────────────────────┐")
                    log.info("  │            报告完整内容                        │")
                    log.info("  └─────────────────────────────────────────────┘")
                    # 输出完整报告内容
                    for line in report_map[idx]["content"].split('\n'):
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
                else:
                    # 全局错误，追加到最后
                    err_idx = len(report_map)
                    report_map[err_idx] = {
                        "output_name": report_name or "全局错误",
                        "template": event.get("template", ""),
                        "use_ragflow": event.get("use_ragflow", False),
                        "content": f"生成失败: {error_detail}",
                        "citations": [],
                        "error": error_detail,
                    }

        # 按 index 排序返回
        sorted_keys = sorted(report_map.keys())
        return [report_map[k] for k in sorted_keys]

    def _map_to_callback_fields(self, reports: list, job_logger=None, template_limit: int = None) -> dict:
        """
        按方案第 2 节规则，将 3 份报告映射到回调字段

        映射规则（已修正: kb开头的字段对应第3份，因第3份使用知识库检索）:
        - 第1份 (index 0): 日会早报（基础日报） → markdownContent
        - 第2份 (index 1): 日会早报趋势分析 → summaryMarkdown
        - 第3份 (index 2): 日会早报改善建议 → kbReportMarkdown + knowledgeBasePayload

        若某份报告缺失或生成失败，内容记为错误提示，仍按规则填入对应字段。

        Args:
            reports: 报告列表

        Returns:
            回调字段字典
        """
        def _get_content(index: int, fallback_msg: str) -> str:
            """安全获取指定索引报告的内容"""
            if index < len(reports):
                return reports[index].get("content", fallback_msg)
            return fallback_msg

        def _get_citations_json(index: int) -> str:
            """安全获取指定索引报告的 citations JSON"""
            if index < len(reports):
                citations = reports[index].get("citations", [])
                return json.dumps(citations, ensure_ascii=False) if citations else ""
            return ""

        log = job_logger or logger

        # 打印调试：第3份（index 2，使用知识库）报告的引用信息
        citations2 = reports[2].get("citations", []) if len(reports) > 2 else []
        log.info("")
        log.info("[回调字段映射] 第3份报告（知识库引用）citations: %d 条", len(citations2))
        if citations2:
            log.info("[回调字段映射] 第3份报告引用详情:")
            for i, cite in enumerate(citations2[:3]):
                log.info("  [%d] %s", i+1, cite.get('source', '未知来源'))

        # 构建回调字段（傍晚版仅1份报告时，其余字段用跳过消息而非"生成失败"）
        if template_limit is not None and template_limit <= 1:
            skip_msg = "傍晚版仅生成基础日报（此报告无需生成）"
            result = {
                "markdownContent": _get_content(0, "日会早报生成失败"),   # 第1份：基础日报
                "summaryMarkdown": _get_content(1, skip_msg),             # 傍晚版未生成
                "kbReportMarkdown": _get_content(2, skip_msg),            # 傍晚版未生成
                "knowledgeBasePayload": _get_citations_json(2),
            }
        else:
            result = {
                "markdownContent": _get_content(0, "日会早报生成失败"),      # 第1份：基础日报
                "summaryMarkdown": _get_content(1, "日会早报趋势分析生成失败"), # 第2份：趋势分析
                "kbReportMarkdown": _get_content(2, "日会早报改善建议生成失败"), # 第3份：改善建议（带知识库）
                "knowledgeBasePayload": _get_citations_json(2),                   # 第3份的引用数据
            }

        log.info("[回调字段映射] markdownContent: %d 字", len(result['markdownContent']))
        log.info("[回调字段映射] summaryMarkdown: %d 字", len(result['summaryMarkdown']))
        log.info("[回调字段映射] kbReportMarkdown: %d 字", len(result['kbReportMarkdown']))
        log.info("[回调字段映射] knowledgeBasePayload: %d 字符", len(result['knowledgeBasePayload']))
        log.info("")

        return result

    def run_batch_lean_morning_daily_job(
        self,
        report_date: str = None,
        workshop_ids: list = None,
        template_limit: int = None,
    ) -> dict:
        """
        批量执行精益早会日报生成（所有车间的所有工序）

        执行流程：
        1. 获取车间树（或使用指定的 workshop_ids）
        2. 对每个车间，获取其工序列表
        3. 对每个 (workshop_id, procedure_id) 依次调用 run_lean_morning_daily_job()
        4. 汇总所有执行结果

        Args:
            report_date: 报告日期（可选，默认昨日）
            workshop_ids: 可选，指定车间ID列表，None表示全部车间

        Returns:
            {
                "total": int,           # 总任务数
                "success": int,         # 成功数
                "failed": int,          # 失败数
                "results": [            # 各任务结果
                    {"workshopId": xx, "procedureId": xx, "success": bool, "error": "...", ...},
                    ...
                ],
                "elapsedTime": float,   # 总耗时（秒）
            }
        """
        start_time = time.time()
        results = []
        success_count = 0
        failed_count = 0

        # 确保 report_date 不为空，默认使用昨天的日期
        if not report_date:
            report_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            print(f"[批量作业] report_date 为空，使用默认值: {report_date}")

        # 防重入：同一时刻只允许一个批量任务运行
        acquired = AgentWorker._batch_lock.acquire(blocking=False)
        if not acquired:
            warning_msg = "已有批量作业正在执行，本次触发已跳过"
            logger.warning("[AgentWorker] %s", warning_msg)
            print(f"\n  ⚠️  {warning_msg}")
            # 即使失败也创建一个临时日志记录一下
            temp_logger = JobLogger(
                job_type="leanMorningDailyReport_batch",
                report_date=report_date or datetime.now().strftime("%Y-%m-%d"),
                params={"workshop_ids": workshop_ids},
            )
            temp_logger.warning("[AgentWorker] %s", warning_msg)
            return {
                "total": 0,
                "success": 0,
                "failed": 0,
                "results": [],
                "elapsedTime": 0,
                "error": warning_msg,
                "logFile": temp_logger.get_log_file_path(),
            }

        AgentWorker._batch_running = True

        # 创建批量作业日志
        job_logger = JobLogger(
            job_type="leanMorningDailyReport_batch",
            report_date=report_date or datetime.now().strftime("%Y-%m-%d"),
            params={"workshop_ids": workshop_ids},
        )

        try:

            print(f"\n{'='*70}")
            print(f"[批量作业] 开始执行精益早会日报批量生成")
            print(f"{'='*70}")
            print(f"  报告日期: {report_date or '默认昨日'}")
            print(f"  指定车间: {workshop_ids if workshop_ids else '全部'}")
            print(f"{'='*70}\n")

            job_logger.info("=" * 70)
            job_logger.info("[批量作业] 开始执行精益早会日报批量生成")
            job_logger.info("  报告日期: %s", report_date or "默认昨日")
            job_logger.info("  指定车间: %s", workshop_ids if workshop_ids else "全部")
            job_logger.info("=" * 70)

            # ---- 阶段 1: 获取车间树 ----
            print(f"[阶段 1/4] 获取车间树...")
            try:
                all_workshops = self.upstream.get_workshop_tree()
            except Exception as e:
                logger.error("[AgentWorker] 获取车间树失败: %s", e, exc_info=True)
                print(f"  ❌ 获取车间树失败: {e}")
                return {
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                    "results": [],
                    "elapsedTime": time.time() - start_time,
                    "error": f"获取车间树失败: {e}",
                }

            # 车间去重（按ID），防止同一车间重复
            unique_workshops = {}
            for w in all_workshops:
                if w["id"] not in unique_workshops:
                    unique_workshops[w["id"]] = w
                else:
                    logger.warning("[AgentWorker] 发现重复车间，已跳过: id=%s, name=%s", w["id"], w["name"])
                    print(f"  ⚠️  发现重复车间: {w['name']}(ID={w['id']})，已跳过")

            workshops = list(unique_workshops.values())

            # 过滤指定车间
            if workshop_ids:
                workshop_ids_set = set(workshop_ids)
                workshops = [w for w in workshops if w["id"] in workshop_ids_set]
                print(f"  ✅ 指定车间过滤，剩余 {len(workshops)} 个")
            else:
                print(f"  ✅ 去重后共 {len(workshops)} 个车间")

            if not workshops:
                print(f"  ⚠️  没有可处理的车间，批量作业结束")
                return {
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                    "results": [],
                    "elapsedTime": time.time() - start_time,
                    "warning": "没有可处理的车间",
                }

            # 输出车间清单
            print(f"\n  📋 待处理的车间清单:")
            for idx, w in enumerate(workshops, 1):
                print(f"    {idx:2d}. ID={w['id']:2d} - {w['name']}")
            job_logger.info("待处理车间清单: %s", [f"{w['id']}-{w['name']}" for w in workshops])

            # ---- 阶段 2: 收集所有需要处理的 (workshop, procedure) 组合 ----
            print(f"\n[阶段 2/4] 收集各车间的工序列表...")
            task_list = []
            seen_pairs = set()  # 用于去重，避免同一工序执行两次

            for workshop in workshops:
                workshop_id = workshop["id"]
                workshop_name = workshop["name"]
                print(f"  正在获取车间 [{workshop_id}] {workshop_name} 的工序...")

                # 获取工序列表（支持重试）
                procedures = None
                last_error = None
                for proc_attempt in range(1, 3):  # 最多重试2次
                    try:
                        procedures = self.upstream.get_procedure_list(workshop_id)
                        break
                    except Exception as e:
                        last_error = e
                        if proc_attempt < 2:
                            wait_sec = proc_attempt * 3
                            print(f"    ⚠️  第{proc_attempt}次获取工序失败: {e}，{wait_sec}秒后重试...")
                            time.sleep(wait_sec)

                if procedures is None:
                    logger.error(
                        "[AgentWorker] 获取车间 %s 工序列表失败（重试后）: %s",
                        workshop_name, last_error, exc_info=True
                    )
                    print(f"    ❌ 获取工序列表失败（重试后）: {last_error}，跳过该车间")
                    failed_count += 1
                    results.append({
                        "workshopId": workshop_id,
                        "workshopName": workshop_name,
                        "procedureId": None,
                        "success": False,
                        "error": f"获取工序列表失败（重试后）: {last_error}",
                    })
                    continue

                # 添加工序到任务列表（去重）
                added_count = 0
                for proc in procedures:
                    proc_id = proc["id"]
                    # 使用 (workshop_id, proc_id) 组合去重
                    pair_key = (workshop_id, proc_id)
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        task_list.append({
                            "workshopId": workshop_id,
                            "workshopName": workshop_name,
                            "procedureId": proc_id,
                            "procedureName": proc["name"],
                        })
                        added_count += 1
                    else:
                        print(f"    ⚠️  发现重复工序 {proc['name']}(ID={proc_id})，已跳过")
                        logger.warning(
                            "[AgentWorker] 发现重复工序，已跳过: workshopId=%s, procedureId=%s",
                            workshop_id, proc_id
                        )

                if len(procedures) == 0:
                    print(f"    ⚠️  警告：该车间没有配置任何工序！")
                    logger.warning("[AgentWorker] 车间 %s 的工序列表为空", workshop_name)
                elif added_count != len(procedures):
                    print(f"    ✅ 获取到 {len(procedures)} 个工序，有效任务数: {added_count}（去重后）")
                else:
                    print(f"    ✅ 获取到 {len(procedures)} 个工序")

            total_tasks = len(task_list) + failed_count
            print(f"\n  ✅ 收集完成，共 {len(task_list)} 个待生成的报告任务")

            # 按车间分组，输出完整工序清单
            print(f"\n  📋 完整工序清单（按车间分组）:")
            tasks_by_workshop = {}
            for task in task_list:
                w_id = task["workshopId"]
                if w_id not in tasks_by_workshop:
                    tasks_by_workshop[w_id] = {
                        "name": task["workshopName"],
                        "procedures": []
                    }
                tasks_by_workshop[w_id]["procedures"].append(task)

            for w_id, info in sorted(tasks_by_workshop.items()):
                print(f"\n    【车间 {w_id}: {info['name']}】")
                for idx, proc in enumerate(info["procedures"], 1):
                    print(f"      {idx:2d}. 工序ID={proc['procedureId']:2d} - {proc['procedureName']}")

            # 记录到日志
            all_tasks_summary = []
            for task in task_list:
                all_tasks_summary.append(f"[{task['workshopId']}]{task['workshopName']}/[{task['procedureId']}]{task['procedureName']}")
            job_logger.info("待处理任务清单（共 %d 个）: %s", len(all_tasks_summary), all_tasks_summary)

            # ---- 阶段 3: 按顺序执行每个任务 ----
            print(f"\n[阶段 3/4] 开始顺序执行报告生成...")
            print(f"{'='*70}\n")

            # 收集所有成功的工序报告（第1份）
            successful_workshop_reports = []

            # 单任务最大重试次数
            MAX_RETRIES = 2

            for idx, task in enumerate(task_list, 1):
                workshop_id = task["workshopId"]
                workshop_name = task["workshopName"]
                procedure_id = task["procedureId"]
                procedure_name = task["procedureName"]

                print(f"\n{'─'*70}")
                print(f"[{idx}/{len(task_list)}] 正在生成: {workshop_name} / {procedure_name}")
                print(f"{'─'*70}")

                single_result = None
                last_error = None

                for attempt in range(1, MAX_RETRIES + 1):
                    try:
                        single_result = self.run_lean_morning_daily_job(
                            workshop_id=workshop_id,
                            procedure_id=procedure_id,
                            report_date=report_date,
                            workshop_name=workshop_name,
                            procedure_name=procedure_name,
                            template_limit=template_limit,
                        )

                        if single_result.get("success"):
                            break
                        else:
                            last_error = single_result.get("error", "未知错误")
                            if attempt < MAX_RETRIES:
                                wait = attempt * 5
                                print(f"\n  ⚠️  [{idx}/{len(task_list)}] {workshop_name}/{procedure_name} 第{attempt}次失败: {last_error}，{wait}秒后重试...")
                                time.sleep(wait)
                    except Exception as e:
                        last_error = str(e)
                        logger.error(
                            "[AgentWorker] 任务执行失败(第%d次): workshopId=%s, procedureId=%s, error=%s",
                            "[AgentWorker] 任务执行失败(第%d次): workshopId=%s, procedureId=%s, error=%s",
                            attempt, workshop_id, procedure_id, e, exc_info=True
                        )
                        if attempt < MAX_RETRIES:
                            wait = attempt * 5
                            print(f"\n  ⚠️  [{idx}/{len(task_list)}] {workshop_name}/{procedure_name} 第{attempt}次异常: {e}，{wait}秒后重试...")
                            time.sleep(wait)

                # 判定最终结果
                if single_result and single_result.get("success"):
                    success_count += 1
                    results.append({
                        "workshopId": workshop_id,
                        "workshopName": workshop_name,
                        "procedureId": procedure_id,
                        "procedureName": procedure_name,
                        "success": True,
                        "reportId": single_result.get("reportId"),
                    })
                    print(f"\n  ✅ [{idx}/{len(task_list)}] {workshop_name}/{procedure_name} 生成成功")

                    reports = single_result.get("reports", [])
                    if reports and len(reports) > 0:
                        first_report = reports[0]
                        successful_workshop_reports.append({
                            "workshopId": workshop_id,
                            "workshopName": workshop_name,
                            "procedureId": procedure_id,
                            "procedureName": procedure_name,
                            "report1Content": first_report.get("content", "")
                        })
                else:
                    failed_count += 1
                    results.append({
                        "workshopId": workshop_id,
                        "workshopName": workshop_name,
                        "procedureId": procedure_id,
                        "procedureName": procedure_name,
                        "success": False,
                        "error": last_error,
                    })
                    print(f"\n  ❌ [{idx}/{len(task_list)}] {workshop_name}/{procedure_name} 重试{MAX_RETRIES}次后仍失败: {last_error}")

                # 任务之间停顿，避免请求过于集中
                if idx < len(task_list):
                    time.sleep(5)

            # ---- 阶段 4: 生成工厂级汇总报告 ----
            factory_reports_result = None
            if successful_workshop_reports:
                print(f"\n[阶段 4/4] 生成工厂级汇总报告...")
                print(f"{'='*70}\n")

                # 如果 report_date 仍未确定，尝试从成功工序结果中推断
                if not report_date:
                    # 取第一个成功工序的 reportDate
                    first_success = results[0] if results and results[0].get("success") else None
                    if first_success:
                        # 无法直接从 results 获取 reportDate，所以从数据库查询最新记录
                        pass
                    # 最终兜底：使用昨日日期
                    report_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                    print(f"  ⚠️  report_date 未传入，使用默认日期: {report_date}")

                try:
                    # 方案 A：优先使用内存中收集的数据（快）
                    factory_reports_result = self._generate_factory_level_reports(
                        all_workshop_reports=successful_workshop_reports,
                        report_date=report_date,
                        template_limit=template_limit,
                    )
                    print(f"\n  ✅ 工厂级报告生成成功（使用内存数据）")

                except Exception as e:
                    logger.error("[AgentWorker] 工厂级报告生成失败，尝试降级方案: %s", e, exc_info=True)
                    print(f"\n  ⚠️  工厂级报告主路径失败，尝试从数据库恢复...")

                    # 方案 B：降级，从 SQLite 数据库重新查询（慢，但可靠）
                    try:
                        db_workshop_reports = db.query_workshop_reports_by_date(
                            report_date=report_date,
                        )

                        if db_workshop_reports:
                            print(f"    ✅ 从数据库恢复了 {len(db_workshop_reports)} 份车间报告")
                            factory_reports_result = self._generate_factory_level_reports(
                                all_workshop_reports=db_workshop_reports,
                                report_date=report_date,
                                template_limit=template_limit,
                            )
                            print(f"\n  ✅ 工厂级报告生成成功（使用数据库数据）")
                        else:
                            print(f"    ❌ 数据库中没有可用的车间报告，工厂级报告生成失败")
                            logger.error("[AgentWorker] 降级方案也失败：数据库中无车间报告数据")

                    except Exception as e2:
                        logger.error("[AgentWorker] 降级方案也失败了: %s", e2, exc_info=True)
                        print(f"\n  ❌ 降级方案也失败了: {e2}")
            else:
                print(f"\n[阶段 4/4] 没有成功生成的工序报告，跳过工厂级报告生成")

            # ---- 汇总结果 ----
            elapsed_time = time.time() - start_time

            print(f"\n\n{'#'*70}")
            print(f"# [批量作业完成] 精益早会日报批量生成")
            print(f"{'#'*70}")
            print(f"#  总任务数: {total_tasks}")
            print(f"#  成功数: {success_count} ✅")
            print(f"#  失败数: {failed_count} ❌")
            print(f"#  总耗时: {elapsed_time:.1f} 秒")
            if total_tasks > 0:
                print(f"#  成功率: {success_count/total_tasks*100:.1f}%")
            if factory_reports_result:
                print(f"#  工厂级报告: {'✅ 已生成' if factory_reports_result else '❌ 失败'}")
            print(f"{'#'*70}")

            # ===== 完整执行结果汇总表 =====
            print(f"\n{'='*70}")
            print("📊 完整执行结果汇总表")
            print(f"{'='*70}")

            # 按车间分组展示结果
            results_by_workshop = {}
            for r in results:
                w_id = r["workshopId"]
                if w_id not in results_by_workshop:
                    results_by_workshop[w_id] = {
                        "name": r["workshopName"],
                        "items": []
                    }
                results_by_workshop[w_id]["items"].append(r)

            for w_id, info in sorted(results_by_workshop.items()):
                workshop_success = sum(1 for item in info["items"] if item["success"])
                workshop_total = len(info["items"])
                print(f"\n【车间 {w_id}: {info['name']}】({workshop_success}/{workshop_total} 成功)")
                print(f"{'─'*70}")
                print(f"  {'序号':<4} {'工序ID':<6} {'工序名称':<15} {'状态':<8} {'备注'}")
                print(f"{'─'*70}")
                for idx, item in enumerate(info["items"], 1):
                    status = "✅ 成功" if item["success"] else "❌ 失败"
                    proc_id = item["procedureId"] if item["procedureId"] else "-"
                    proc_name = item.get("procedureName", "-")
                    remark = "" if item["success"] else f"失败原因: {item.get('error', '未知')[:40]}"
                    print(f"  {idx:<4} {proc_id:<6} {proc_name:<15} {status:<8} {remark}")

            # ===== 失败清单（单独列出，方便排查） =====
            failed_items = [r for r in results if not r["success"]]
            if failed_items:
                print(f"\n\n{'!'*70}")
                print(f"❌ 失败任务清单（共 {len(failed_items)} 个）")
                print(f"{'!'*70}")
                for idx, item in enumerate(failed_items, 1):
                    print(f"\n  {idx}. {item['workshopName']} / {item.get('procedureName', '获取工序失败')}")
                    print(f"     车间ID: {item['workshopId']}, 工序ID: {item.get('procedureId', '-')}")
                    print(f"     失败原因: {item.get('error', '未知')}")

            print(f"\n{'#'*70}\n")

            job_logger.info("#" * 70)
            job_logger.info("# [批量作业完成] 精益早会日报批量生成")
            job_logger.info("#  总任务数: %d", total_tasks)
            job_logger.info("#  成功数: %d ✅", success_count)
            job_logger.info("#  失败数: %d ❌", failed_count)
            job_logger.info("#  总耗时: %.1f 秒", elapsed_time)
            if total_tasks > 0:
                job_logger.info("#  成功率: %.1f%%", success_count/total_tasks*100)
            if factory_reports_result:
                job_logger.info("#  工厂级报告: ✅ 已生成")
            job_logger.info("#" * 70)

            # ===== 完整执行结果汇总表（日志） =====
            job_logger.info("=" * 70)
            job_logger.info("📊 完整执行结果汇总表")
            job_logger.info("=" * 70)

            # 按车间分组展示结果
            results_by_workshop = {}
            for r in results:
                w_id = r["workshopId"]
                if w_id not in results_by_workshop:
                    results_by_workshop[w_id] = {
                        "name": r["workshopName"],
                        "items": []
                    }
                results_by_workshop[w_id]["items"].append(r)

            for w_id, info in sorted(results_by_workshop.items()):
                workshop_success = sum(1 for item in info["items"] if item["success"])
                workshop_total = len(info["items"])
                job_logger.info("【车间 %s: %s】(%d/%d 成功)", w_id, info["name"], workshop_success, workshop_total)
                job_logger.info("-" * 70)
                job_logger.info("  %-4s %-6s %-15s %-8s %s", "序号", "工序ID", "工序名称", "状态", "备注")
                job_logger.info("-" * 70)
                for idx, item in enumerate(info["items"], 1):
                    status = "✅ 成功" if item["success"] else "❌ 失败"
                    proc_id = item["procedureId"] if item["procedureId"] else "-"
                    proc_name = item.get("procedureName", "-")
                    remark = "" if item["success"] else "失败原因: %s" % (item.get('error', '未知')[:40])
                    job_logger.info("  %-4d %-6s %-15s %-8s %s", idx, proc_id, proc_name, status, remark)

            # ===== 失败清单（单独列出，方便排查） =====
            failed_items = [r for r in results if not r["success"]]
            if failed_items:
                job_logger.info("")
                job_logger.info("!" * 70)
                job_logger.info("❌ 失败任务清单（共 %d 个）", len(failed_items))
                job_logger.info("!" * 70)
                for idx, item in enumerate(failed_items, 1):
                    job_logger.info("  %d. %s / %s", idx, item['workshopName'], item.get('procedureName', '获取工序失败'))
                    job_logger.info("     车间ID: %s, 工序ID: %s", item['workshopId'], item.get('procedureId', '-'))
                    job_logger.info("     失败原因: %s", item.get('error', '未知'))

            logger.info(
                "[AgentWorker] 批量作业完成: total=%d, success=%d, failed=%d, elapsed=%.1fs",
                total_tasks, success_count, failed_count, elapsed_time
            )

            return {
                "total": total_tasks,
                "success": success_count,
                "failed": failed_count,
                "results": results,
                "elapsedTime": elapsed_time,
                "factoryReports": factory_reports_result,
                "logFile": job_logger.get_log_file_path(),
            }

        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error("[AgentWorker] 批量作业异常: %s", e, exc_info=True)
            job_logger.error("[AgentWorker] 批量作业异常: %s", str(e), exc_info=True)
            print(f"\n  ❌ 批量作业异常: {e}")
            return {
                "total": len(results),
                "success": success_count,
                "failed": failed_count,
                "results": results,
                "elapsedTime": elapsed_time,
                "error": f"批量作业异常: {e}",
                "logFile": job_logger.get_log_file_path(),
            }
        finally:
            AgentWorker._batch_running = False
            AgentWorker._batch_lock.release()
            logger.info("[AgentWorker] 批量作业锁已释放")
            job_logger.info("[批量作业] 执行结束，锁已释放")

    def _run_single_quality_report(
        self,
        report_type: str,
        report_date: str = None,
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
        job_logger.info("=" * 70)
        job_logger.info("[%s] 开始执行", label)
        job_logger.info("=" * 70)

        report_id = None
        has_error = False
        error_msg = ""
        callback_ok = None

        try:
            # ---- 阶段 1: 拉参 ----
            # report_date 为空时默认昨日
            if not report_date:
                report_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            job_logger.info("[%s] 阶段 1/3: 拉取参数...", label)
            pull_result = pull_method(report_date=report_date)
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
                job_logger.info("[%s] 加载历史报告上下文...", label)
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

            # ---- 阶段 2: 生成报告 ----
            job_logger.info("[%s] 阶段 2/3: 生成报告...", label)

            # 数据预处理（clean + map-reduce，复用给 generator 和持久化）
            from backend.utils.data_preprocessor import preprocess_payload
            preprocessed_data_json = preprocess_payload(payload)
            job_logger.info("  数据预处理完成，长度: %d 字符", len(preprocessed_data_json))

            reports = self._collect_reports_from_stream(report_code, payload, job_logger=job_logger,
                                                        preprocessed_data_json=preprocessed_data_json)
            total_report_len = sum(len(r.get("content", "")) for r in reports)
            job_logger.info("  ✅ 报告生成完成, 共 %d 份, 总长度=%d字符", len(reports), total_report_len)

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
                    workshop_id=None,  # 此方法为工厂级质量报告，无车间维度
                    report_date=report_date,
                    date_type=date_type,
                    agent_response_processed=preprocessed_data_json,
                )
                job_logger.info("  ✅ SQLite 持久化完成")
            except Exception as e:
                job_logger.warning("  ❌ SQLite 持久化失败: %s", e)

        except Exception as e:
            has_error = True
            error_msg = str(e)
            job_logger.error("[%s] 执行失败: %s", label, e, exc_info=True)
            job_logger.info("  ❌ %s 执行失败: %s", label, e)

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

        job_logger.info("[%s] 执行结果: success=%s, reportId=%s, callbackOk=%s",
                        label, not has_error, report_id, callback_ok)

        result = {
            "reportId": report_id,
            "success": not has_error,
            "error": error_msg or None,
            "callbackOk": callback_ok,
            "logFile": job_logger.get_log_file_path(),
        }

        # 如果是独立调用（非批量模式），输出汇总日志
        if own_logger:
            job_logger.info("")
            job_logger.print_separator()
            job_logger.info("[Agent 作业完成] %s 生成", label)
            job_logger.print_separator()

        return result

    def run_quality_daily_job(self, report_date: str = None) -> dict:
        """执行质量概览日报生成"""
        return self._run_single_quality_report("daily", report_date)

    def run_quality_weekly_job(self, report_date: str = None) -> dict:
        """执行质量概览周报生成"""
        return self._run_single_quality_report("weekly", report_date)

    def run_quality_monthly_job(self, report_date: str = None) -> dict:
        """执行质量概览月报生成"""
        return self._run_single_quality_report("monthly", report_date)

    def run_quality_overview_job(self, report_date: str = None) -> dict:
        """
        执行质量概览日周月报告生成作业（串行执行三种报告）

        Args:
            report_date: 报告日期/锚点日（可选，不传则上游使用默认值）

        Returns:
            {
                "success": bool,
                "reportDate": str,
                "daily": {"reportId": int, "success": bool, "error": str, "callbackOk": bool},
                "weekly": {"reportId": int, "success": bool, "error": str, "callbackOk": bool},
                "monthly": {"reportId": int, "success": bool, "error": str, "callbackOk": bool},
                "logFile": str,
            }
        """
        job_logger = JobLogger(
            job_type="qualityOverviewReport",
            report_date=report_date or datetime.now().strftime("%Y-%m-%d"),
            params={"report_date": report_date},
        )

        job_logger.info("[AgentWorker] 开始执行质量概览日周月报告作业: reportDate=%s", report_date or "默认")
        job_logger.print_separator()
        job_logger.info("[Agent 作业开始] 质量概览日周月报告生成")
        job_logger.print_separator()

        results = {
            "daily": self._run_single_quality_report("daily", report_date, job_logger=job_logger),
            "weekly": self._run_single_quality_report("weekly", report_date, job_logger=job_logger),
            "monthly": self._run_single_quality_report("monthly", report_date, job_logger=job_logger),
        }

        overall_success = all(r.get("success") for r in results.values())

        # ---- 汇总 ----
        job_logger.info("")
        job_logger.print_separator()
        job_logger.info("[Agent 作业完成] 质量概览日周月报告生成")
        job_logger.print_separator()
        job_logger.info("日报:  success=%s, reportId=%s", results["daily"].get("success"), results["daily"].get("reportId"))
        job_logger.info("周报:  success=%s, reportId=%s", results["weekly"].get("success"), results["weekly"].get("reportId"))
        job_logger.info("月报:  success=%s, reportId=%s", results["monthly"].get("success"), results["monthly"].get("reportId"))

        return {
            "success": overall_success,
            "reportDate": report_date,
            "daily": results["daily"],
            "weekly": results["weekly"],
            "monthly": results["monthly"],
            "logFile": job_logger.get_log_file_path(),
        }
