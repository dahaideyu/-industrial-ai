# cython: annotation_typing=False, infer_types=False, language_level=3
"""
报告管理路由
提供报告查询、下载、调试等功能
"""
import os
import sys
import json
import time
import logging
from typing import Optional, Union, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# 确保 backend 目录在路径中（与 app.py 保持一致）
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(os.path.dirname(current_dir))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from core.response import success_response, error_response
from core.database import query_reports, get_report_detail, query_reports_distinct_by_date
from core.singletons import get_report_generator_singleton

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["report_management"])


def _load_historical_context(
    report_code: str,
    workshop_id: int,
    procedure_id: int,
    report_date: str,
    days: int = 6,
) -> str:
    """
    从 SQLite 查询前 N 天的同维度历史报告，按日期倒序拼接
    每个日期只取最新一条记录（去重）

    Args:
        report_code: 报告类型编码
        workshop_id: 车间 ID
        procedure_id: 工序 ID
        report_date: 当前报告日期（YYYY-MM-DD）
        days: 往前拉取天数，默认 6

    Returns:
        历史报告内容字符串，无历史记录时返回空串
    """
    logger.info("=" * 70)
    logger.info("[历史数据] 开始加载历史报告上下文")
    logger.info("=" * 70)
    logger.info("  报告类型: %s", report_code)
    logger.info("  车间ID: %s", workshop_id)
    logger.info("  工序ID: %s", procedure_id)
    logger.info("  报告日期: %s", report_date)
    logger.info("  查询天数: %s 天", days)

    # 计算日期范围：前 days 天到前 1 天
    try:
        current_date = datetime.strptime(report_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        logger.warning("[历史数据] report_date 格式无效: %s，无法计算日期范围", report_date)
        return ""

    date_from = (current_date - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to = report_date  # 不含当天

    logger.info("  日期范围: %s ~ %s (不含当天)", date_from, date_to)
    logger.info("")

    # 按日期去重查询同维度记录（每个日期只取最新一条）
    logger.info("[历史数据] 执行数据库查询（按日期去重）...")
    records = query_reports_distinct_by_date(
        report_code=report_code,
        workshop_id=workshop_id,
        procedure_id=procedure_id,
        report_date_from=date_from,
        report_date_to=date_to,
        status=0,
        limit=days,
    )

    logger.info("[历史数据] 查询结果: 找到 %s 个不同日期的历史记录", len(records))

    if not records:
        logger.info("[历史数据] 无历史记录，跳过加载")
        logger.info("=" * 70)
        return ""

    # 显示找到的历史记录
    logger.info("")
    logger.info("  ┌─────────────────────────────────────────────┐")
    logger.info("  │         找到的历史记录                        │")
    logger.info("  └─────────────────────────────────────────────┘")
    for idx, record in enumerate(records, 1):
        record_date = record.get("report_date", "")
        record_status = "成功" if record.get("status") == 0 else "失败"
        logger.info("  [%d] 日期: %s, 状态: %s", idx, record_date, record_status)
    logger.info("")

    # 按日期倒序拼接报告内容（query_reports_distinct_by_date 已包含 markdown_content）
    context_parts = []
    for idx, record in enumerate(records, 1):
        record_date = record.get("report_date", "")
        logger.info("[历史数据] 处理第 %d/%d 条记录: %s", idx, len(records), record_date)

        if not record_date:
            logger.info("  ⚠️  记录中无 report_date 字段，跳过")
            continue

        content = record.get("markdown_content", "")
        if content:
            content_len = len(content)
            logger.info("  ✅ 提取报告内容: %d 字符", content_len)
            context_parts.append(f"### {record_date}\n{content}")
        else:
            logger.info("  ⚠️  报告内容为空，跳过")

    logger.info("")
    logger.info("[历史数据] 处理完成:")
    logger.info("  成功提取: %d 份报告", len(context_parts))

    if not context_parts:
        logger.info("  结果: 没有可用于拼接的历史报告内容")
        logger.info("=" * 70)
        return ""

    historical_context = "\n\n".join(context_parts)
    logger.info("  总字符数: %d 字符", len(historical_context))
    logger.info("  报告日期: %s", ", ".join([p.split("\n")[0].replace("### ", "") for p in context_parts]))
    logger.info("")
    logger.info("[历史数据] ✅ 历史报告上下文加载完成")
    logger.info("=" * 70)

    return historical_context


class ReportQueryRequest(BaseModel):
    """报告查询请求"""
    report_code: Optional[str] = None
    workshop_id: Optional[int] = None
    date_type: Optional[str] = None
    once_qualified_flag: Optional[int] = None
    class_id: Optional[int] = None
    procedure_id: Optional[int] = None
    report_date: Optional[str] = None
    page: int = 1
    page_size: int = 20


class ReportDetailRequest(BaseModel):
    """报告详情请求"""
    report_code: str
    report_date: str


class DocumentDownloadRequest(BaseModel):
    """文档下载请求"""
    document_id: str


@router.post("/reports/query")
async def query_reports_list(request: ReportQueryRequest):
    """
    分页查询报告列表

    支持按 report_code、workshop_id、date_type 等条件筛选
    """
    try:
        result = query_reports(
            report_code=request.report_code,
            workshop_id=request.workshop_id,
            date_type=request.date_type,
            once_qualified_flag=request.once_qualified_flag,
            class_id=request.class_id,
            procedure_id=request.procedure_id,
            report_date=request.report_date,
            page=request.page,
            page_size=request.page_size
        )
        return success_response(data=result)
    except Exception as e:
        logger.error(f"查询报告列表失败: {e}", exc_info=True)
        return error_response(msg=f"查询失败: {str(e)}")


@router.post("/reports/detail")
async def get_report_detail_api(request: ReportDetailRequest):
    """
    查询报告详情

    根据 report_code 和 report_date 查询报告详情
    """
    try:
        result = get_report_detail(
            report_code=request.report_code,
            report_date=request.report_date
        )
        if result is None:
            return error_response(msg="报告不存在", code=404, status_code=404)
        return success_response(data=result)
    except Exception as e:
        logger.error(f"查询报告详情失败: {e}", exc_info=True)
        return error_response(msg=f"查询失败: {str(e)}")


@router.post("/document/download")
async def download_document(request: DocumentDownloadRequest):
    """
    代理下载 RAGFlow 文档

    通过后端代理下载 RAGFlow 中的文档，避免前端跨域问题
    """
    try:
        from backend.clients.ragflow_client import get_ragflow_client

        client = get_ragflow_client()
        content = client.download_document(request.document_id)

        if content is None:
            return error_response(msg="文档下载失败", code=404, status_code=404)

        from fastapi.responses import Response
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={request.document_id}"}
        )
    except Exception as e:
        logger.error(f"下载文档失败: {e}", exc_info=True)
        return error_response(msg=f"下载失败: {str(e)}")


@router.get("/env/debug")
async def env_debug():
    """
    环境配置调试

    显示当前环境变量配置（敏感信息已脱敏）
    """
    import os

    config = {
        "PROVIDER": os.getenv("PROVIDER", "未设置"),
        "MODEL": os.getenv("MODEL", "未设置"),
        "UPSTREAM_MOCK": os.getenv("UPSTREAM_MOCK", "false"),
        "UPSTREAM_BASE_URL": os.getenv("UPSTREAM_BASE_URL", "未设置"),
        "RAGFLOW_BASE_URL": os.getenv("RAGFLOW_BASE_URL", "未设置"),
        "ENABLE_REPORT_SCHEDULER": os.getenv("ENABLE_REPORT_SCHEDULER", "false"),
    }

    # 脱敏处理
    if config["UPSTREAM_BASE_URL"] and config["UPSTREAM_BASE_URL"] != "未设置":
        config["UPSTREAM_BASE_URL"] = config["UPSTREAM_BASE_URL"][:20] + "..."
    if config["RAGFLOW_BASE_URL"] and config["RAGFLOW_BASE_URL"] != "未设置":
        config["RAGFLOW_BASE_URL"] = config["RAGFLOW_BASE_URL"][:20] + "..."

    return success_response(data=config)


class MultiReportsRequest(BaseModel):
    """多报告生成请求"""
    reportCode: str
    data: Optional[dict] = None
    meta: Optional[dict] = None
    response: Optional[Union[list, dict]] = None


@router.post("/multi_reports_stream")
async def generate_multi_reports_stream(request: MultiReportsRequest):
    """
    多报告生成接口（流式）：根据配置生成多份报告
    生成完成后自动保存到 SQLite
    """
    payload = request.model_dump(exclude_unset=True)
    report_code = payload.get('reportCode')

    # 1. 获取请求原始数据
    if payload.get('data'):
        data = payload['data']
    else:
        data = {
            'meta': payload.get('meta', {}),
            'response': payload.get('response', []),
        }

    # 确保 reportCode 保存到 data 中（用于持久化到数据库）
    if 'reportCode' not in data:
        data['reportCode'] = report_code

    if not report_code:
        return error_response(msg="缺少 reportCode 字段", code=400, status_code=400)

    raw_json = json.dumps(data, ensure_ascii=False)
    logger.info("[阶段1/获取原始数据] reportCode=%s, 原始数据=%d 字符", report_code, len(raw_json))

    # 自动加载历史数据（如果 data 中没有 historicalContext）
    meta = data.get('meta', {}) if isinstance(data.get('meta'), dict) else {}
    historical_context_raw = meta.get('historicalContext')
    if not historical_context_raw:
        try:
            workshop_id = data.get('workshopId') or data.get('workshop_id') or meta.get('workshopId') or meta.get('workshop_id')
            procedure_id = data.get('procedureId') or data.get('procedure_id') or meta.get('procedureId') or meta.get('procedure_id')
            report_date = data.get('reportDate') or data.get('report_date') or meta.get('reportDate') or meta.get('report_date') or meta.get('period')
            if workshop_id and procedure_id and report_date:
                historical_context = _load_historical_context(
                    report_code=report_code,
                    workshop_id=int(workshop_id),
                    procedure_id=int(procedure_id),
                    report_date=report_date,
                )
                if historical_context:
                    if 'meta' not in data or not isinstance(data.get('meta'), dict):
                        data['meta'] = {}
                    data['meta']['historicalContext'] = historical_context
                    logger.info("[历史数据] 已注入历史报告上下文 (%d 字符)", len(historical_context))
        except Exception as e:
            logger.warning("[历史数据] 加载失败，跳过: %s", e)

    try:
        generator = get_report_generator_singleton()

        # 2. 开始去除空值
        from backend.utils.data_cleaner import clean_raw_data
        from backend.utils.data_preprocessor import preprocess_sources

        cleaned = clean_raw_data(data)
        after_clean = json.dumps(cleaned, ensure_ascii=False)
        logger.info("[阶段2/去除空值] 清洗后=%d 字符", len(after_clean))

        # 3. 开始 reduce
        response_list = cleaned.get("response", [])
        # 兼容 dict 格式的 response（前端可能发送 {data: [...], query: {...}}）
        if isinstance(response_list, dict):
            response_list = response_list.get("data", [])
        prepped_names = []
        if isinstance(response_list, list):
            preprocess_sources(response_list)
            prepped_names = [
                item.get("sourceKey", "?") for item in response_list
                if isinstance(item, dict) and isinstance(item.get("data"), dict)
                and item["data"].get("_preprocessed")
            ]

        after_reduce = json.dumps(cleaned, ensure_ascii=False)
        logger.info("[阶段3/reduce] reduce后=%d 字符 (缩减 %.1f%%), reduce了 %d 个",
                    len(after_reduce),
                    (1 - len(after_reduce) / len(raw_json)) * 100 if raw_json else 0,
                    len(prepped_names))

        # 打印每个被 reduce 的 sourceKey 的内容（前200字符）
        for item in response_list:
            if isinstance(item, dict) and isinstance(item.get("data"), dict) and item["data"].get("_preprocessed"):
                sk = item.get("sourceKey", "?")
                data_preview = json.dumps(item["data"], ensure_ascii=False)[:200]
                logger.info("  [%s] %s...", sk, data_preview)

        preprocessed_data_json = json.dumps(cleaned, ensure_ascii=False, indent=2)

        async def stream_generator():
            """流式生成器"""
            start_time = time.time()
            reports_data = []
            current_report = None
            has_error = False
            error_msg = ""

            for event in generator.generate_reports_stream(
                data, report_code, preprocessed_data_json=preprocessed_data_json or None
            ):
                # 发送心跳，保持连接
                yield ": heartbeat\n\n".encode('utf-8')

                # 收集报告内容用于持久化
                event_type = event.get('event')
                if event_type == 'report_start':
                    current_report = {
                        'report_name': event.get('report_name', ''),
                        'template': event.get('template', ''),
                        'content': '',
                        'citations': []
                    }
                elif event_type == 'content' and current_report is not None:
                    current_report['content'] += event.get('content', '')
                elif event_type == 'citations' and current_report is not None:
                    current_report['citations'] = event.get('citations', [])
                elif event_type == 'report_end' and current_report is not None:
                    current_report['content'] = event.get('total', current_report['content'])
                    current_report['citations'] = event.get('citations', current_report.get('citations', []))
                    reports_data.append(current_report)
                    current_report = None
                elif event_type == 'error':
                    has_error = True
                    error_msg = event.get('error', '未知错误')
                elif event_type == 'end':
                    elapsed_time = time.time() - start_time
                    total_content_length = sum(len(r.get('content', '')) for r in reports_data)
                    logger.info("[完成] %d 份报告, 总长=%d 字符, 耗时=%.2f 秒", len(reports_data), total_content_length, elapsed_time)

                    # 保存到数据库
                    from core.database import upsert_report
                    from core.response import success_response

                    agent_response = {
                        "reports": reports_data,
                        "totalTime": elapsed_time,
                        "preprocessedData": json.loads(preprocessed_data_json) if preprocessed_data_json else {}
                    }

                    period_label = meta.get("periodLabel", meta.get("period", ""))
                    date_type = meta.get("periodType", meta.get("dateType", "day"))
                    title = f"{period_label} 报告" if period_label else f"{report_code} 报告"

                    markdown_content = reports_data[0]['content'] if len(reports_data) > 0 else ""
                    summary_markdown = reports_data[1]['content'] if len(reports_data) > 1 else ""
                    kb_report_markdown = reports_data[2]['content'] if len(reports_data) > 2 else ""

                    knowledge_base_payload = ""
                    if len(reports_data) > 2 and reports_data[2].get('citations'):
                        knowledge_base_payload = json.dumps(reports_data[2]['citations'], ensure_ascii=False)

                    workshop_id = data.get('workshopId') or data.get('workshop_id') or meta.get('workshopId') or meta.get('workshop_id')
                    procedure_id = data.get('procedureId') or data.get('procedure_id') or meta.get('procedureId') or meta.get('procedure_id')
                    report_date = data.get('reportDate') or data.get('report_date') or meta.get('reportDate') or meta.get('report_date') or meta.get('period')

                    try:
                        upsert_report(
                            report_code=report_code,
                            title=title,
                            period_label=period_label,
                            request_payload=data,
                            agent_response_raw=agent_response,
                            status=1 if has_error else 0,
                            error_message=error_msg,
                            workshop_id=workshop_id,
                            date_type=date_type,
                            procedure_id=procedure_id,
                            report_date=report_date,
                            markdown_content=markdown_content,
                            summary_markdown=summary_markdown,
                            kb_report_markdown=kb_report_markdown,
                            knowledge_base_payload=knowledge_base_payload,
                            agent_response_processed=preprocessed_data_json,
                        )
                    except Exception as db_err:
                        logger.error("[持久化] 保存报告失败: %s", db_err, exc_info=True)

                # 发送事件（统一使用 utf-8 编码）
                if event_type == 'start':
                    yield f"event: start\n".encode('utf-8')
                    yield f"data: {json.dumps({'count': event['count']}, ensure_ascii=False)}\n\n".encode('utf-8')

                elif event_type == 'report_start':
                    yield f"event: report_start\n".encode('utf-8')
                    start_data = {
                        'report_name': event['report_name'],
                        'template': event.get('template', ''),
                        'index': event['index'],
                        'count': event['count']
                    }
                    yield f"data: {json.dumps(start_data, ensure_ascii=False)}\n\n".encode('utf-8')

                elif event_type == 'content':
                    content = event['content']
                    yield f"event: content\n".encode('utf-8')
                    yield f"data: {json.dumps({'content': content, 'index': event['index'], 'count': event['count']}, ensure_ascii=False)}\n\n".encode('utf-8')

                elif event_type == 'citations':
                    yield f"event: citations\n".encode('utf-8')
                    yield f"data: {json.dumps({'citations': event['citations'], 'index': event['index'], 'count': event['count']}, ensure_ascii=False)}\n\n".encode('utf-8')

                elif event_type == 'report_end':
                    yield f"event: report_end\n".encode('utf-8')
                    end_data = {
                        'report_name': event['report_name'],
                        'template': event.get('template', ''),
                        'total': event.get('total', ''),
                        'index': event['index'],
                        'count': event['count'],
                        'citations': event.get('citations', [])
                    }
                    yield f"data: {json.dumps(end_data, ensure_ascii=False)}\n\n".encode('utf-8')

                elif event_type == 'error':
                    yield f"event: error\n".encode('utf-8')
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode('utf-8')

                elif event_type == 'end':
                    elapsed_time = time.time() - start_time
                    yield f"event: end\n".encode('utf-8')
                    yield f"data: {json.dumps({'totalTime': elapsed_time}, ensure_ascii=False)}\n\n".encode('utf-8')

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
                "Connection": "keep-alive",
                "X-Content-Type-Options": "nosniff"
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"报告生成失败: {str(e)}", code=500, status_code=500)