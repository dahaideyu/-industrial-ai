# cython: annotation_typing=False, infer_types=False, language_level=3
from pydantic import BaseModel, Field


class RepairSuggestionRequest(BaseModel):
    device_name: str = Field(..., description="设备型号")
    device_type: str = Field(..., description="设备类型")
    fault_description: str = Field(..., description="故障现象描述")


class RepairOrderScoringRequest(BaseModel):
    is_have_pic: bool = Field(..., description="是否有图片")
    is_have_video: bool = Field(..., description="是否有视频")
    handleAnalysis: str = Field(..., description="根因分析")
    handleAction: str = Field(..., description="处理措施")
    is_replace_spare: bool = Field(..., description="是否更换备件")
    is_have_spare_record: bool = Field(..., description="是否有备件更换记录")


class TaskSuggestionRequest(BaseModel):
    procedure: str = Field(..., description="工序")
    task_type: str = Field(..., description="任务分类")
    task_description: str = Field(..., description="任务描述")


class TaskScoringRequest(BaseModel):
    plan_end_time: str = Field(..., description="期望完成日期")
    close_time: str = Field(..., description="关闭日期")
    task_description: str = Field(..., description="任务问题描述")
    handle_action: str = Field(..., description="处理措施")
    is_upload_file: bool = Field(..., description="是否上传文件")
