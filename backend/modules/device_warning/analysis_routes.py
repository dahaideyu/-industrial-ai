# cython: annotation_typing=False, infer_types=False, language_level=3
import json
import math

from fastapi import APIRouter, Body
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from modules.device_warning.services.device_analyzer import analyze_device
from core.response import success_response, error_response

router = APIRouter(prefix="/api", tags=["analysis"])


class DeviceAnalysisRequest(BaseModel):
    module: str = Field(default="all", description="分析模块（anomaly/health/fault/energy/all）")
    hours: int = Field(default=24, ge=1, le=168, description="加载过去N小时的数据")
    device_id: str | None = Field(default=None, description="设备ID（留空使用默认）")
    format: str = Field(default="json", description="输出格式（json/text）")


@router.get("/device_analysis/modules")
def list_device_modules():
    """列出所有可用的设备分析模块"""
    modules = {
        "anomaly": "异常检测与报警预警",
        "health": "设备健康看板",
        "fault": "故障预测",
        "energy": "能耗优化分析",
        "all": "完整分析（包含所有模块）"
    }
    return success_response(data=modules)


@router.post("/device_analysis")
def device_analysis(data: DeviceAnalysisRequest = Body(...)):
    """
    设备分析接口
    """
    print(f"\n{'='*60}")
    print(f"[请求] POST /api/device_analysis")
    print(f"{'='*60}")
    print(f"[调试] 分析模块: {data.module}")
    print(f"[调试] 数据范围: 最近 {data.hours} 小时")
    print(f"[调试] 设备ID: {data.device_id or '默认'}")
    print(f"[调试] 输出格式: {data.format}")

    results, error_msg, status_code = analyze_device(
        module=data.module,
        hours=data.hours,
        device_id=data.device_id
    )

    if error_msg:
        return error_response(msg=error_msg, code=status_code, status_code=status_code)

    if data.format == "text":
        text_output = json.dumps(results, ensure_ascii=False, indent=2, default=str)
        return PlainTextResponse(content=text_output, media_type="text/plain; charset=utf-8")

    # 预序列化：处理 Timestamp、NaN、Enum 等不可 JSON 序列化的类型
    serialized = json.loads(json.dumps(results, default=str))
    return success_response(data=serialized, msg="分析完成")
