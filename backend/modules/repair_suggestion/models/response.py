# cython: annotation_typing=False, infer_types=False, language_level=3
from pydantic import BaseModel, Field


class RepairSuggestionResponse(BaseModel):
    status: str = Field(..., description="状态: success/error")
    conclusion: str = Field(default="", description="故障处理总结，150-200字")
    context: str = Field(default="", description="返回内容")
    error_code: int = Field(default=0, description="错误码，0表示成功")
    error_message: str = Field(default="", description="错误信息")


class RepairOrderScoringResponse(BaseModel):
    score: float = Field(..., description="评分，0-5")
    explanation: str = Field(..., description="评分说明")


class TaskSuggestionResponse(BaseModel):
    status: str = Field(..., description="状态: success/error")
    conclusion: str = Field(default="", description="任务建议总结，150-200字")
    context: str = Field(default="", description="返回的完整任务建议内容")
    error_code: int = Field(default=0, description="错误码，0表示成功")
    error_message: str = Field(default="", description="错误信息")


class TaskScoringResponse(BaseModel):
    score: float = Field(..., description="评分，0-5，支持0.5分步进")
    explanation: str = Field(..., description="评分说明")
