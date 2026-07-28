# cython: annotation_typing=False, infer_types=False, language_level=3
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from contextlib import asynccontextmanager
from fastapi import FastAPI
from config import Config
from models import (
    RepairSuggestionRequest,
    RepairSuggestionResponse,
    RepairOrderScoringRequest,
    RepairOrderScoringResponse,
    TaskSuggestionRequest,
    TaskSuggestionResponse,
    TaskScoringRequest,
    TaskScoringResponse,
)
from services import RAGFlowService, ScoringService
from scheduler import setup_scheduler

# 配置日志目录
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 配置日志
log_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 每小时一个日志文件
file_handler = TimedRotatingFileHandler(
    filename=os.path.join(LOG_DIR, "app.log"),
    when='H',
    interval=1,
    backupCount=168,  # 保留7天的日志
    encoding='utf-8'
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.DEBUG)

# 配置根日志记录器
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.handlers = []  # 清除默认处理器
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时设置定时任务
    scheduler = setup_scheduler()
    yield
    # 关闭时停止调度器
    scheduler.shutdown()


app = FastAPI(title="超威知识库服务", lifespan=lifespan)

ragflow_service = RAGFlowService()
scoring_service = ScoringService()


@app.post("/api/repair-suggestion", response_model=RepairSuggestionResponse)
async def get_repair_suggestion(request: RepairSuggestionRequest):
    """获取维修建议"""
    logger.info("=" * 60)
    logger.info("[API] 收到维修建议请求")
    logger.info(f"[API] 设备型号: {request.device_name}")
    logger.info(f"[API] 设备类型: {request.device_type}")
    logger.info(f"[API] 故障现象: {request.fault_description}")
    try:
        # 1. 查询历史维修单
        logger.info("[API] 第一步：查询历史维修单")
        history_content, history_err = await ragflow_service.query_history_repair_orders(
            request.device_name,
            request.device_type,
            request.fault_description
        )
        if history_err:
            logger.warning(f"[API] 历史维修单查询失败: {history_err}")
        else:
            logger.debug(f"[API] 历史维修单查询结果: {history_content}")

        # 2. 查询设备文档
        logger.info("[API] 第二步：查询设备文档")
        doc_content, doc_err = await ragflow_service.query_device_docs(
            request.device_name,
            request.device_type,
            request.fault_description
        )
        if doc_err:
            logger.warning(f"[API] 设备文档查询失败: {doc_err}")
        else:
            logger.debug(f"[API] 设备文档查询结果: {doc_content}")

        # 3. 生成最终建议
        logger.info("[API] 第三步：生成维修建议")
        from services import DeepSeekService
        deepseek = DeepSeekService()
        conclusion, suggestion, suggest_err = await deepseek.generate_repair_suggestion(
            request.device_name,
            request.device_type,
            request.fault_description,
            history_content if not history_err else None,
            doc_content if not doc_err else None,
        )

        if suggest_err:
            logger.error(f"[API] 生成建议失败: {suggest_err}")
            return RepairSuggestionResponse(
                status="error",
                conclusion="",
                context="",
                error_code=1,
                error_message=suggest_err,
            )

        logger.info("[API] 维修建议生成成功")
        logger.info("=" * 60)
        return RepairSuggestionResponse(
            status="success",
            conclusion=conclusion or "",
            context=suggestion or "",
            error_code=0,
            error_message="",
        )

    except Exception as e:
        logger.exception("[API] 获取维修建议异常")
        logger.info("=" * 60)
        return RepairSuggestionResponse(
            status="error",
            conclusion="",
            context="",
            error_code=2,
            error_message=str(e),
        )


@app.post("/api/repair-order-scoring", response_model=RepairOrderScoringResponse)
async def score_repair_order(request: RepairOrderScoringRequest):
    """维修单智能评分"""
    logger.info("=" * 60)
    logger.info("[API] 收到维修单评分请求")
    logger.debug(f"[API] 请求参数: {request.model_dump()}")
    score, explanation = await scoring_service.score_repair_order(
        is_have_pic=request.is_have_pic,
        is_have_video=request.is_have_video,
        handle_analysis=request.handleAnalysis,
        handle_action=request.handleAction,
        is_replace_spare=request.is_replace_spare,
        is_have_spare_record=request.is_have_spare_record,
    )
    logger.info(f"[API] 评分完成 - 得分: {score}")
    logger.info("=" * 60)
    return RepairOrderScoringResponse(score=score, explanation=explanation)


@app.post("/api/task-suggestion", response_model=TaskSuggestionResponse)
async def get_task_suggestion(request: TaskSuggestionRequest):
    """获取精益改善任务建议"""
    logger.info("=" * 60)
    logger.info("[API] 收到任务建议请求")
    logger.info(f"[API] 工序: {request.procedure}")
    logger.info(f"[API] 任务分类: {request.task_type}")
    logger.info(f"[API] 任务描述: {request.task_description}")
    try:
        # 1. 查询知识库
        logger.info("[API] 第一步：查询知识库")
        doc_content, doc_err = await ragflow_service.query_task_knowledge(
            request.procedure,
            request.task_type,
            request.task_description,
        )
        if doc_err:
            logger.warning(f"[API] 知识库查询失败: {doc_err}")
        else:
            logger.debug(f"[API] 知识库查询结果: {doc_content}")

        # 2. 生成任务建议
        logger.info("[API] 第二步：生成任务改善建议")
        from services import DeepSeekService
        deepseek = DeepSeekService()
        conclusion, context, suggest_err = await deepseek.generate_task_suggestion(
            request.procedure,
            request.task_type,
            request.task_description,
            doc_content if not doc_err else None,
        )

        if suggest_err:
            logger.error(f"[API] 生成任务建议失败: {suggest_err}")
            return TaskSuggestionResponse(
                status="error",
                conclusion="",
                context="",
                error_code=1,
                error_message=suggest_err,
            )

        logger.info("[API] 任务建议生成成功")
        logger.info("=" * 60)
        return TaskSuggestionResponse(
            status="success",
            conclusion=conclusion or "",
            context=context or "",
            error_code=0,
            error_message="",
        )

    except Exception as e:
        logger.exception("[API] 获取任务建议异常")
        logger.info("=" * 60)
        return TaskSuggestionResponse(
            status="error",
            conclusion="",
            context="",
            error_code=2,
            error_message=str(e),
        )


@app.post("/api/task-scoring", response_model=TaskScoringResponse)
async def score_task(request: TaskScoringRequest):
    """精益改善任务智能评分"""
    logger.info("=" * 60)
    logger.info("[API] 收到任务评分请求")
    logger.debug(f"[API] 请求参数: {request.model_dump()}")
    score, explanation = await scoring_service.score_task(
        plan_end_time=request.plan_end_time,
        close_time=request.close_time,
        task_description=request.task_description,
        handle_action=request.handle_action,
        is_upload_file=request.is_upload_file,
    )
    logger.info(f"[API] 任务评分完成 - 得分: {score}")
    logger.info("=" * 60)
    return TaskScoringResponse(score=score, explanation=explanation)


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=Config.HOST, port=Config.PORT, reload=True)
