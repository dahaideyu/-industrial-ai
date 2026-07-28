# cython: annotation_typing=False, infer_types=False, language_level=3
"""
Pydantic 数据模型定义
"""

from datetime import date, datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class GenerateReportRequest(BaseModel):
    """单设备报告生成请求"""
    device_id: str = Field(..., description="设备ID")
    report_type: str = Field(..., pattern="^(daily|weekly|monthly)$",
                            description="报告类型: daily/weekly/monthly")
    report_date: Optional[date] = Field(None, description="报告日期，默认今天")


class BatchGenerateRequest(BaseModel):
    """批量报告生成请求"""
    report_type: str = Field(..., pattern="^(daily|weekly|monthly)$",
                            description="报告类型: daily/weekly/monthly")
    report_date: Optional[date] = Field(None, description="报告日期，默认今天")
    device_ids: Optional[List[str]] = Field(None, description="指定设备ID列表")
    workshop_id: Optional[str] = Field(None, description="指定车间ID")


class TriggerScheduledRequest(BaseModel):
    """手动触发定时任务请求"""
    report_type: str = Field(..., pattern="^(daily|weekly|monthly)$",
                            description="报告类型")
    report_date: Optional[date] = Field(None, description="报告日期")


class ReportSummary(BaseModel):
    """报告摘要"""
    id: int
    report_type: str
    report_date: date
    device_id: str
    device_name: Optional[str]
    workshop: Optional[str]
    health_score: Optional[float]
    health_status: Optional[str]
    alarm_count: int = 0
    risk_level: Optional[str]
    created_at: datetime


class ReportDetail(BaseModel):
    """报告详情"""
    id: int
    report_type: str
    report_date: date
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    device_id: str
    device_name: Optional[str]
    device_code: Optional[str]
    workshop_id: Optional[str]
    workshop: Optional[str]
    production_line_id: Optional[str]
    production_line: Optional[str]
    alarm_count: int = 0
    alarm_types: Optional[Dict[str, int]]
    alarm_duration_seconds: int = 0
    alarm_rate: float = 0
    health_score: Optional[float]
    health_status: Optional[str]
    health_trend: Optional[str]
    parameter_health: Optional[Dict[str, Any]]
    fault_predictions: Optional[List[Dict[str, Any]]]
    risk_level: Optional[str]
    maintenance_suggestions: Optional[List[str]]
    urgent_actions: Optional[List[str]]
    report_content: Optional[str]
    report_summary: Optional[str]
    comparison_data: Optional[Dict[str, Any]]
    generated_by: str = "system"
    generation_time_seconds: Optional[float]
    llm_model: Optional[str]
    created_at: datetime


class ReportResponse(BaseModel):
    """报告生成响应"""
    device_id: str
    report_type: str
    report_date: date
    period: Dict[str, datetime]
    analysis_summary: Dict[str, Any]
    report_content: str
    report_id: int


class ReportListResponse(BaseModel):
    """报告列表响应"""
    total: int
    items: List[ReportSummary]


class ReportStatsSummary(BaseModel):
    """报告统计汇总"""
    total_devices: int
    total_alarms: int
    avg_alarm_rate: float
    avg_health_score: float
    low_health_count: int  # 健康分 < 60 的设备数


class JobStatus(BaseModel):
    """任务状态"""
    id: int
    job_type: str
    job_status: str
    report_date: date
    total_devices: int
    processed_devices: int
    failed_devices: int
    trigger_type: str
    triggered_by: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]


class WorkshopSummary(BaseModel):
    """车间汇总"""
    id: int
    report_type: str
    report_date: date
    summary_level: str
    workshop_id: Optional[str]
    workshop_name: Optional[str]
    total_devices: int
    devices_reported: int
    avg_health_score: Optional[float]
    min_health_score: Optional[float]
    max_health_score: Optional[float]
    devices_critical: int
    devices_warning: int
    devices_fair: int
    devices_good: int
    devices_excellent: int
    total_alarms: int
    summary_content: Optional[str]
