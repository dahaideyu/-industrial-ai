# cython: annotation_typing=False, infer_types=False, language_level=3
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from modules.daily_report.services.report_generator import generate_report_stream
from core.response import success_response

router = APIRouter(prefix="/api", tags=["report"])


class AiReportRequest(BaseModel):
    model_config = {"extra": "allow"}
    reportCode: str
    data: dict | None = None


@router.post("/ai_report")
async def ai_report(request: AiReportRequest):
    """
    流式接口：接收质量周报 Payload，流式返回 AI 生成的报告（格式由提示词模板决定）。
    返回格式：SSE (Server-Sent Events) 格式
    """
    print(f"\n{'='*60}")
    print(f"[请求] POST /api/ai_report")
    print(f"{'='*60}")
    print(f"[调试] reportCode: {request.reportCode}")

    # 获取原始请求体，不受 Pydantic 模型限制
    from fastapi import Request
    # 注意：这里不能直接获取原始 body，因为已经在上面被 Pydantic 消费了
    # 使用 model_dump 保留所有显式传入的字段
    payload = request.model_dump()

    print(f"[调试] payload 顶级字段: {list(payload.keys())}")
    if "data" in payload:
        data_val = payload["data"]
        if isinstance(data_val, dict):
            print(f"[调试] data 字段下的键: {list(data_val.keys())}")
            print(f"[调试] data 内容长度: {len(str(data_val))} 字符")
        else:
            print(f"[警告] data 字段类型: {type(data_val)}，值: {data_val}")

    if "reportCode" not in payload:
        print(f"[警告] 缺少 reportCode 字段")
        raise HTTPException(status_code=400, detail="缺少 reportCode 字段")

    return StreamingResponse(
        generate_report_stream(payload),
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


@router.get("/templates")
def list_templates():
    """列出所有可用的报告模板"""
    from modules.daily_report.prompts import list_available_templates
    templates = list_available_templates()
    return success_response(data=templates)
