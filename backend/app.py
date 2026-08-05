# cython: annotation_typing=False, infer_types=False, language_level=3
import os
import sys
import argparse
import logging
from contextlib import asynccontextmanager

# 确保无论从哪里启动（backend/ 或项目根目录），backend/ 下的包都能被正确导入
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


def parse_args():
    """
    解析命令行参数

    支持通过 --env 指定环境配置文件，通过 --model 指定模型供应商
    """
    parser = argparse.ArgumentParser(description="AI Report 服务")
    parser.add_argument("-e", "--env", type=str, default=None,
                        help="指定环境配置文件路径（如 .env.prod.shandong）")
    parser.add_argument("-m", "--model", type=str, default=None,
                        help="指定模型供应商（如 deepseek、qwen3、openai、local_qwen3）")
    parser.add_argument("--host", type=str, default=None,
                        help="监听地址，覆盖 FASTAPI_HOST（默认 0.0.0.0）")
    parser.add_argument("-p", "--port", type=int, default=None,
                        help="监听端口，覆盖 FASTAPI_PORT（默认 9300）")
    args, _ = parser.parse_known_args()
    return args


# 解析命令行参数
_args = parse_args()

# 统一的 .env 加载入口（详见 core/env.py），优先级：--env > deploy/docker/.env > backend/.env > 项目根/.env
from core.env import load_env
load_env(explicit_path=_args.env)

# -m 参数覆盖模型供应商
if _args.model:
    os.environ["PROVIDER"] = _args.model
    print(f"[启动] 模型供应商已覆盖为: {_args.model}")

# --host/--port 覆盖 FASTAPI_HOST/FASTAPI_PORT（run.bat -h/-p 走这里传进来）
if _args.host:
    os.environ["FASTAPI_HOST"] = _args.host
if _args.port:
    os.environ["FASTAPI_PORT"] = str(_args.port)

# 配置日志（集中式，级别从 LOG_LEVEL 环境变量读取，默认 INFO；可选 LOG_FORMAT=json 输出结构化日志）
from core.logging_config import setup_logging
setup_logging()
logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.response import success_response
from routes import health_router, report_router, analysis_router, jobs_router, document_router, alarms_router, system_jobs_router, device_config_router
from modules.auth import auth_router
from modules.maintenance_report import maintenance_report_router
from modules.device_param import device_param_router
from modules.report_management import report_management_router
from modules.lean_morning_daily import lean_morning_daily_router
from modules.quality_overview import quality_overview_router
from modules.device_efficiency import device_efficiency_router
from modules.device_maintenance import device_maintenance_router
from modules.maintenance_report.services.scheduler import get_scheduler
from core.scheduler import init_scheduler as init_report_scheduler

# ============================================================
# 应用生命周期管理
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global ENABLE_KNOWLEDGE_BASE
    # 启动时
    logger.info("应用启动中...")

    # 清理超过 7 天的旧日志
    from core.job_logger import cleanup_old_logs
    cleanup_old_logs(keep_days=7)

    # 启动报告调度器（如果启用）
    raw_scheduler_env = os.getenv("ENABLE_REPORT_SCHEDULER", "false")
    enable_scheduler = raw_scheduler_env.lower() == "true"
    logger.info(f"ENABLE_REPORT_SCHEDULER 读取值: '{raw_scheduler_env}'，解析结果: {enable_scheduler}")
    scheduler = None

    if enable_scheduler:
        try:
            # 初始化自定义调度器（精益早会、质量、设备效率报告）
            init_report_scheduler()

            # 启动 maintenance_report 调度器
            scheduler = get_scheduler()
            scheduler.start()
            logger.info("报告调度器已启动")
            jobs = scheduler.get_scheduled_jobs()
            logger.info(f"当前已调度任务数: {len(jobs)}")
            for job in jobs:
                logger.info(f"  - {job['id']}: {job['name']} (下次执行: {job.get('next_run', '-')})")
        except Exception as e:
            logger.error(f"报告调度器启动失败: {e}", exc_info=True)
    else:
        logger.info("报告调度器未启用（ENABLE_REPORT_SCHEDULER 不是 true）")

    # SQL-QA 模块初始化（仅在启用时）
    if ENABLE_SQL_QA:
        try:
            from backend.core.agentic_qa.database import init_db as init_sqlqa_db
            init_sqlqa_db()
            logger.info("[Agentic QA] 数据库初始化完成")
        except Exception as e:
            logger.error(f"[Agentic QA] 数据库初始化失败: {e}", exc_info=True)

        try:
            from backend.services.agentic_qa.vanna.agent import init_vanna_agent
            logger.info("[Agentic QA] 正在初始化 Vanna Agent...")
            init_vanna_agent()
            logger.info("[Agentic QA] Vanna Agent 初始化完成")
        except Exception as e:
            logger.warning(f"[Agentic QA] Vanna Agent 初始化失败（不影响主流程）: {e}")

        try:
            from backend.core.agentic_qa.graph_client import get_graph_client
            from backend.core.agentic_qa.graph_importer import import_to_neo4j, load_mapping
            from backend.core.agentic_qa.config import settings as sqlqa_settings
            from backend.services.agentic_qa.db.mysql import db as mysql_db

            client = get_graph_client()
            if client.is_available():
                logger.info("[Agentic QA] 正在导入知识图谱到 Neo4j...")
                mapping = load_mapping(sqlqa_settings.graph_mapping_path)
                result = import_to_neo4j(client, mysql_db, mapping)
                if result.get("success"):
                    logger.info(
                        f"[Agentic QA] 知识图谱导入完成: {result['nodes_created']} 节点, "
                        f"{result['relationships_created']} 关系"
                    )
                else:
                    logger.warning(f"[Agentic QA] 知识图谱导入部分失败: {result.get('errors', [])}")
            else:
                logger.info("[Agentic QA] Neo4j 不可用，跳过知识图谱导入")
        except Exception as e:
            logger.warning(f"[Agentic QA] 知识图谱初始化失败（不影响主流程）: {e}")

    # 认证模块初始化（创建 sys_user 表 + 种入默认管理员账号）
    try:
        from modules.auth.service import ensure_user_table
        ensure_user_table()
        logger.info("认证模块初始化完成（sys_user 表 + 默认管理员账号）")
    except Exception as e:
        logger.error(f"认证模块初始化失败: {e}", exc_info=True)

    # 报告持久化数据库初始化（所有模块共用，始终初始化）
    try:
        from backend.core.database import init_db as init_report_db
        init_report_db()
        logger.info("报告持久化数据库初始化完成（ai_analysis_report）")
    except Exception as e:
        logger.error(f"报告持久化数据库初始化失败: {e}", exc_info=True)

    # 知识库管理模块初始化（仅在启用时）
    if ENABLE_KNOWLEDGE_BASE:
        try:
            from backend.core.knowledge_management.database import init_db
            init_db()
            logger.info("知识库管理模块数据库初始化完成")
        except Exception as e:
            logger.error(f"知识库管理模块初始化失败: {e}")
            ENABLE_KNOWLEDGE_BASE = False

    yield

    # 关闭时
    logger.info("应用关闭中...")
    if scheduler:
        scheduler.stop()
        logger.info("报告调度器已停止")


# ============================================================
# FastAPI 应用初始化
# ============================================================
app = FastAPI(
    title="Industrial Intelligence API",
    description="AI 设备监控与分析平台后端",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 全局异常处理：确保所有 500 响应都返回带 msg 的 JSON
# （FastAPI 默认返回 {"detail": "..."} 没有 msg 字段，
#  前端 axios 拦截器找不到 msg 就回退成 "Request failed with status code 500"）
# ============================================================
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        content={"code": exc.status_code, "msg": str(exc.detail)},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理异常: {request.method} {request.url.path}", exc_info=True)
    return JSONResponse(
        content={"code": 500, "msg": f"服务器内部错误: {exc}"},
        status_code=500,
    )

# ============================================================
# 注册路由
# ============================================================
app.include_router(auth_router)  # 认证模块
app.include_router(health_router)
app.include_router(report_router)
app.include_router(analysis_router)
app.include_router(jobs_router)
app.include_router(system_jobs_router)  # 系统管理 · 统一 Job 管理
app.include_router(device_config_router)  # 系统管理 · 设备列表管理
app.include_router(document_router)
app.include_router(alarms_router)  # 报警记录查询
app.include_router(maintenance_report_router)  # 预测性维护报告模块
app.include_router(device_param_router)  # 设备参数查询模块
app.include_router(report_management_router)  # 报告管理模块
app.include_router(lean_morning_daily_router)  # 精益早会日报模块
app.include_router(quality_overview_router)  # 质量概览报告模块
app.include_router(device_efficiency_router)  # 设备效率报告模块
app.include_router(device_maintenance_router)  # 设备运维报告模块

# ============================================================
# Agentic QA 智能问答平台（可选模块，通过 ENABLE_SQL_QA 控制）
# ============================================================
ENABLE_SQL_QA = os.getenv("ENABLE_SQL_QA", "false").lower() == "true"
logger.info(f"ENABLE_SQL_QA 读取值: '{os.getenv('ENABLE_SQL_QA', 'false')}'，解析结果: {ENABLE_SQL_QA}")

# 知识库管理模块开关
ENABLE_KNOWLEDGE_BASE = os.getenv("ENABLE_KNOWLEDGE_BASE", "false").lower() == "true"
logger.info(f"ENABLE_KNOWLEDGE_BASE 读取值: '{os.getenv('ENABLE_KNOWLEDGE_BASE', 'false')}'，解析结果: {ENABLE_KNOWLEDGE_BASE}")

if ENABLE_SQL_QA:
    try:
        os.environ["SQL_QA_UNIFIED_AUTH"] = "true"
        logger.info("[Agentic QA] 统一认证模式已启用")

        # Agentic QA 配置已合并到 .env（AQA_ 前缀），无需单独加载 .env.sqlqa

        from backend.routes.agentic_qa.routes import router as sqlqa_router
        from backend.routes.agentic_qa.admin import router as sqlqa_admin_router
        from backend.routes.agentic_qa.websocket import router as sqlqa_ws_router
        from backend.routes.agentic_qa.sessions import router as sqlqa_sessions_router
        # 注意：不导入 auth.py，避免 /api/auth/login 路径冲突

        app.include_router(sqlqa_router, prefix="/api")
        app.include_router(sqlqa_admin_router, prefix="/api")
        app.include_router(sqlqa_ws_router, prefix="/api")
        app.include_router(sqlqa_sessions_router, prefix="/api")
        logger.info("[Agentic QA] 路由注册完成")
    except Exception as e:
        logger.error(f"[Agentic QA] 路由注册失败（主应用仍可正常运行）: {e}", exc_info=True)
        ENABLE_SQL_QA = False

# ============================================================
# 知识库管理模块（可选模块，通过 ENABLE_KNOWLEDGE_BASE 控制）
# ============================================================
ENABLE_KNOWLEDGE_QA = False  # 知识库问答依赖知识库管理，独立记录（管理注册成功但问答自己失败时不该报"全都行"）
if ENABLE_KNOWLEDGE_BASE:
    try:
        from backend.routes.knowledge_management.routes import router as kb_router
        app.include_router(kb_router, prefix="/api")

        # 知识库问答（依赖知识库管理）
        try:
            from backend.routes.knowledge_qa.routes import router as kbqa_router
            app.include_router(kbqa_router, prefix="/api/kb-qa", tags=["kb-qa"])
            ENABLE_KNOWLEDGE_QA = True
            logger.info("[知识库问答] 路由注册完成")
        except Exception as e:
            logger.error(f"[知识库问答] 路由注册失败: {e}", exc_info=True)

        logger.info("[知识库管理] 路由注册完成")
    except Exception as e:
        logger.error(f"[知识库管理] 路由注册失败（主应用仍可正常运行）: {e}", exc_info=True)
        # 之前这里没有把开关拨回 False：注册失败时 ENABLE_KNOWLEDGE_BASE 仍是 True，
        # /api/features 会谎报"已启用"——跟 ENABLE_SQL_QA 失败时的处理方式(第283行)保持一致
        ENABLE_KNOWLEDGE_BASE = False


@app.get("/api/features")
def get_feature_flags():
    """暴露可选模块的真实启用状态（路由注册是否成功），供前端导航栏据此灰化/隐藏对应入口，
    避免用户点进一个后端根本没注册路由的死链接。"""
    return success_response(data={
        "sql_qa": ENABLE_SQL_QA,
        "knowledge_base": ENABLE_KNOWLEDGE_BASE,
        "knowledge_qa": ENABLE_KNOWLEDGE_QA,
    })


# ============================================================
# 启动入口（开发调试用，生产使用 uvicorn）
# ============================================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("FASTAPI_PORT", 9300))
    host = os.getenv("FASTAPI_HOST", "0.0.0.0")
    uvicorn.run("backend.app:app", host=host, port=port, reload=False)
