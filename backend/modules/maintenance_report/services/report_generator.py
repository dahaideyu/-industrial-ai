# cython: annotation_typing=False, infer_types=False, language_level=3
"""
报告生成服务 - 使用 LLM 生成自然语言报告
"""

import json
import time
import asyncio
import threading
import queue as threading_queue
from datetime import datetime, timedelta
from typing import AsyncGenerator, Dict, List, Optional

from openai import OpenAI

from core.config import CONFIG
from modules.device_warning.ai_analysis.postgres_loader import PostgresDB
from .data_aggregator import DataAggregator
from .analysis_integrator import AnalysisIntegrator
from ..prompts import get_prompt_template


class MaintenanceReportGenerator:
    """预测性维护报告生成器"""

    def __init__(self):
        self.db = PostgresDB()
        self.data_aggregator = DataAggregator()

    def get_llm(self):
        """获取 LLM 实例"""
        return OpenAI(
            base_url=CONFIG["base_url"],
            api_key=CONFIG["api_key"],
            timeout=600.0
        )

    async def generate_device_report(
        self,
        device_id: str,
        report_type: str,
        report_date: datetime = None
    ) -> Dict:
        """
        生成单台设备的预测性维护报告

        Args:
            device_id: 设备ID
            report_type: 报告类型 (daily/weekly/monthly)
            report_date: 报告日期

        Returns:
            {
                "device_id": str,
                "report_type": str,
                "report_date": date,
                "analysis_results": {...},
                "report_content": str,
                "report_id": int
            }
        """
        start_time = time.time()

        if report_date is None:
            report_date = datetime.now()

        print(f"[报告生成] 开始生成 {device_id} 的 {report_type} 报告...")

        # 1. 确定数据时间范围
        period_start, period_end = self.data_aggregator.get_period(report_type, report_date)

        # 2. 聚合数据
        device_data = self.data_aggregator.aggregate_device_data(
            device_id, period_start, period_end
        )

        # 3. 执行 AI 分析
        integrator = AnalysisIntegrator(device_id)
        analysis_results = integrator.analyze(device_data.get("history_data", {}))

        # 4. 获取对比数据 (周报/月报)
        comparison_data = None
        if report_type in ['weekly', 'monthly']:
            prev_start, prev_end = self.data_aggregator.get_previous_period(
                report_type, period_start
            )
            comparison_data = self.data_aggregator.get_comparison_data(
                device_id,
                (period_start, period_end),
                (prev_start, prev_end)
            )

            # 计算健康趋势
            if analysis_results.get("health"):
                current_score = analysis_results["health"].get("overall_score", 0)
                # 简化：假设上期健康分与当前相近
                prev_score = current_score + (comparison_data["comparison"]["alarm_count_change"] * -0.5)
                analysis_results["health"]["trend"] = integrator.get_health_trend(
                    current_score, prev_score
                )

        # 5. 构建 LLM 输入数据
        prompt_data = self._build_prompt_data(
            device_data, analysis_results, comparison_data, report_type
        )

        # 6. 生成报告
        report_content = await self._generate_with_llm(report_type, prompt_data)

        generation_time = time.time() - start_time

        # 7. 保存到数据库
        report_id = self._save_report(
            device_id, report_type, report_date,
            period_start, period_end,
            device_data, analysis_results,
            comparison_data, report_content,
            generation_time
        )

        print(f"[报告生成] {device_id} 报告生成完成，耗时 {generation_time:.2f}s，报告ID: {report_id}")

        return {
            "device_id": device_id,
            "report_type": report_type,
            "report_date": report_date.date(),
            "period": {"start": period_start, "end": period_end},
            "analysis_results": analysis_results.get("summary", {}),
            "report_content": report_content,
            "report_id": report_id
        }

    async def generate_device_report_stream(
        self,
        device_id: str,
        report_type: str,
        report_date: datetime = None
    ) -> AsyncGenerator[bytes, None]:
        """流式生成设备报告 (SSE)"""
        start_time = time.time()

        if report_date is None:
            report_date = datetime.now()

        yield f"event: start\ndata: {{\"code\": 200, \"msg\": \"开始生成报告\"}}\n\n".encode('utf-8')

        # 发送心跳
        for _ in range(2):
            yield ": heartbeat\n\n".encode('utf-8')
            await asyncio.sleep(0.05)

        try:
            # 1. 数据准备
            yield f"data: 正在加载数据...\n\n".encode('utf-8')

            period_start, period_end = self.data_aggregator.get_period(report_type, report_date)
            device_data = self.data_aggregator.aggregate_device_data(
                device_id, period_start, period_end
            )

            # 2. AI 分析
            yield f"data: 正在进行 AI 分析...\n\n".encode('utf-8')

            integrator = AnalysisIntegrator(device_id)
            analysis_results = integrator.analyze(device_data.get("history_data", {}))

            # 3. 对比数据
            comparison_data = None
            if report_type in ['weekly', 'monthly']:
                prev_start, prev_end = self.data_aggregator.get_previous_period(
                    report_type, period_start
                )
                comparison_data = self.data_aggregator.get_comparison_data(
                    device_id, (period_start, period_end), (prev_start, prev_end)
                )

            # 4. 构建提示词
            prompt_data = self._build_prompt_data(
                device_data, analysis_results, comparison_data, report_type
            )

            # 5. 流式生成
            yield f"data: 正在生成报告内容...\n\n".encode('utf-8')

            template = get_prompt_template(report_type)
            if not template:
                raise ValueError(f"未找到报告模板: {report_type}")

            prompt = template.replace(
                "{data_sources}",
                json.dumps(prompt_data, ensure_ascii=False, indent=2, default=str)
            )

            llm = self.get_llm()
            full_content = ""

            content_queue = threading_queue.Queue()
            done_event = threading.Event()

            def llm_worker():
                try:
                    for chunk in llm.chat.completions.create(
                        model=CONFIG["model"],
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        stream=True
                    ):
                        if chunk.choices[0].delta.content:
                            content_queue.put(('content', chunk.choices[0].delta.content))
                    content_queue.put(('done', None))
                except Exception as e:
                    content_queue.put(('error', str(e)))
                finally:
                    done_event.set()

            worker_thread = threading.Thread(target=llm_worker, daemon=True)
            worker_thread.start()

            last_activity = time.time()

            while not done_event.is_set() or not content_queue.empty():
                try:
                    msg_type, msg_data = await asyncio.to_thread(
                        content_queue.get, timeout=1.5
                    )
                except threading_queue.Empty:
                    if time.time() - last_activity > 1.0:
                        yield ": heartbeat\n\n".encode('utf-8')
                        last_activity = time.time()
                    continue

                if msg_type == 'content':
                    full_content += msg_data
                    last_activity = time.time()
                    lines = msg_data.split('\n')
                    for line in lines:
                        yield f"data: {line}\n".encode('utf-8')
                    yield "\n".encode('utf-8')

                elif msg_type == 'done':
                    break

                elif msg_type == 'error':
                    raise Exception(msg_data)

            generation_time = time.time() - start_time

            # 6. 保存报告
            report_id = self._save_report(
                device_id, report_type, report_date,
                period_start, period_end,
                device_data, analysis_results,
                comparison_data, full_content,
                generation_time
            )

            yield f"event: end\ndata: {json.dumps({'report_id': report_id, 'totalTime': generation_time}, ensure_ascii=False)}\n\n".encode('utf-8')

        except Exception as e:
            elapsed = time.time() - start_time
            yield f"event: error\ndata: {json.dumps({'code': 500, 'msg': f'生成失败: {str(e)}'}, ensure_ascii=False)}\n\n".encode('utf-8')
        finally:
            done_event.set()

    async def generate_batch_reports(
        self,
        report_type: str,
        report_date: datetime = None,
        device_ids: List[str] = None,
        workshop_id: str = None,
        max_concurrent: int = 5
    ) -> Dict:
        """
        批量生成报告

        Args:
            report_type: 报告类型
            report_date: 报告日期
            device_ids: 指定设备ID列表
            workshop_id: 指定车间ID
            max_concurrent: 最大并发数

        Returns:
            {
                "total": int,
                "success": int,
                "failed": int,
                "reports": List[Dict]
            }
        """
        if report_date is None:
            report_date = datetime.now()

        # 获取设备列表
        if device_ids:
            devices = [{"id": did} for did in device_ids]
        elif workshop_id:
            devices = self.data_aggregator.get_devices_by_workshop(workshop_id)
        else:
            devices = self.data_aggregator.get_all_devices()

        total = len(devices)
        success = 0
        failed = 0
        reports = []

        # 使用信号量控制并发
        semaphore = asyncio.Semaphore(max_concurrent)

        async def generate_one(device):
            nonlocal success, failed
            async with semaphore:
                try:
                    result = await self.generate_device_report(
                        device_id=device["id"],
                        report_type=report_type,
                        report_date=report_date
                    )
                    success += 1
                    return result
                except Exception as e:
                    failed += 1
                    print(f"[错误] 设备 {device['id']} 报告生成失败: {e}")
                    return {"device_id": device["id"], "error": str(e)}

        # 并发执行
        tasks = [generate_one(device) for device in devices]
        reports = await asyncio.gather(*tasks)

        return {
            "total": total,
            "success": success,
            "failed": failed,
            "reports": [r for r in reports if r and "report_id" in r]
        }

    def _build_prompt_data(
        self,
        device_data: Dict,
        analysis_results: Dict,
        comparison_data: Optional[Dict],
        report_type: str
    ) -> Dict:
        """构建 LLM 提示词的数据部分"""
        device_info = device_data.get("device_info", {})
        period = device_data.get("period", {})
        alarm_stats = device_data.get("alarm_stats", {})
        health = analysis_results.get("health", {})
        summary = analysis_results.get("summary", {})

        return {
            "device_info": {
                "device_id": device_data.get("device_id"),
                "device_name": device_data.get("device_name"),
                "device_code": device_info.get("device_code") if device_info else None,
                "workshop": device_info.get("workshop_name") if device_info else None,
                "production_line": device_info.get("production_line_name") if device_info else None
            },
            "period": {
                "start": period.get("start").isoformat() if period.get("start") else None,
                "end": period.get("end").isoformat() if period.get("end") else None,
                "type": report_type
            },
            "alarm_statistics": {
                "total_count": alarm_stats.get("total_count", 0),
                "alarm_types": alarm_stats.get("alarm_types", {}),
                "alarm_duration_seconds": alarm_stats.get("alarm_duration_seconds", 0),
                "alarm_rate": round(alarm_stats.get("alarm_rate", 0), 2),
                "top_alarms": alarm_stats.get("top_alarms", [])
            },
            "health_assessment": {
                "score": health.get("overall_score", 0) if health else 0,
                "status": health.get("status", "unknown") if health else "unknown",
                "parameter_scores": health.get("parameter_scores", {}) if health else {},
                "top_risks": health.get("top_risks", []) if health else [],
                "recommendations": health.get("recommendations", []) if health else []
            },
            "anomaly_detection": {
                "total_anomalies": summary.get("total_anomalies", 0),
                "severe_anomalies": summary.get("severe_anomalies", 0),
                "anomaly_summary": analysis_results.get("anomaly_summary", {}),
                "alarm_predictions": analysis_results.get("alarm_predictions", [])[:5]
            },
            "fault_prediction": {
                "predictions": analysis_results.get("fault_predictions", [])[:5],
                "high_risk_count": summary.get("high_risk_faults", 0),
                "risk_level": summary.get("risk_level", "low")
            },
            "maintenance_suggestions": {
                "urgent_actions": summary.get("urgent_actions", []),
                "recommendations": summary.get("maintenance_suggestions", [])
            },
            "comparison": comparison_data
        }

    async def _generate_with_llm(self, report_type: str, prompt_data: Dict) -> str:
        """调用 LLM 生成报告"""
        template = get_prompt_template(report_type)
        if not template:
            # 使用默认模板
            template = self._get_default_template(report_type)

        prompt = template.replace(
            "{data_sources}",
            json.dumps(prompt_data, ensure_ascii=False, indent=2, default=str)
        )

        llm = self.get_llm()
        response = await asyncio.to_thread(
            lambda: llm.chat.completions.create(
                model=CONFIG["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
        )

        return response.choices[0].message.content

    def _get_default_template(self, report_type: str) -> str:
        """获取默认模板"""
        type_name = {"daily": "日报", "weekly": "周报", "monthly": "月报"}.get(report_type, "报告")

        return f"""
请根据以下设备运行数据，生成一份专业的《设备预测性维护{type_name}》。

## 报告要求
1. 包含执行摘要（约100字）
2. 设备健康概览
3. 报警统计分析
4. 故障预测预警
5. 维护建议（分紧急/重要/常规）

## 输入数据
{{data_sources}}

## 输出格式
使用 Markdown 格式，表格清晰，数据准确。
"""

    def _save_report(
        self,
        device_id: str,
        report_type: str,
        report_date: datetime,
        period_start: datetime,
        period_end: datetime,
        device_data: Dict,
        analysis_results: Dict,
        comparison_data: Optional[Dict],
        report_content: str,
        generation_time: float = None
    ) -> int:
        """保存报告到数据库"""
        if not self.db.connect():
            print("[警告] 数据库连接失败，报告未保存")
            return None

        device_info = device_data.get("device_info", {})
        alarm_stats = device_data.get("alarm_stats", {})
        health = analysis_results.get("health", {})
        summary = analysis_results.get("summary", {})

        try:
            report_id = self.db.save_device_report(
                report_type=report_type,
                report_date=report_date.strftime("%Y-%m-%d"),
                period_start=period_start.isoformat() if period_start else None,
                period_end=period_end.isoformat() if period_end else None,
                device_id=device_id,
                device_name=device_data.get("device_name"),
                device_code=device_info.get("device_code") if device_info else None,
                workshop_id=device_info.get("workshop_id") if device_info else None,
                workshop=device_info.get("workshop_name") if device_info else None,
                production_line_id=device_info.get("production_line_id") if device_info else None,
                production_line=device_info.get("production_line_name") if device_info else None,
                alarm_count=alarm_stats.get("total_count", 0),
                alarm_types=alarm_stats.get("alarm_types"),
                alarm_duration_seconds=alarm_stats.get("alarm_duration_seconds", 0),
                alarm_rate=alarm_stats.get("alarm_rate", 0),
                health_score=health.get("overall_score") if health else None,
                health_status=health.get("status") if health else None,
                health_trend=health.get("trend") if health else None,
                parameter_health=health.get("parameter_scores") if health else None,
                fault_predictions=analysis_results.get("fault_predictions"),
                risk_level=summary.get("risk_level"),
                estimated_issues=summary.get("top_risks"),
                maintenance_suggestions=summary.get("maintenance_suggestions"),
                urgent_actions=summary.get("urgent_actions"),
                report_content=report_content,
                report_summary=report_content[:500] if report_content else None,
                comparison_data=comparison_data,
                generated_by="system",
                generation_time_seconds=generation_time,
                llm_model=CONFIG.get("model")
            )
            return report_id
        except Exception as e:
            print(f"[错误] 保存报告失败: {e}")
            return None
        finally:
            self.db.close()
