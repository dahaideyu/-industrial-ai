@echo off
setlocal enabledelayedexpansion

REM %~dp0 锚定本脚本所在目录（deploy/docker/），不依赖调用者当前工作目录
set SCRIPT_DIR=%~dp0
set ENV_FILE=%SCRIPT_DIR%.env
set MODEL_ARG=

:parse_args
if "%~1"=="" goto start
if "%~1"=="--env" (
    set ENV_FILE=%SCRIPT_DIR%%~2
    shift
    shift
    goto parse_args
)
if "%~1"=="--model" (
    set MODEL_ARG=--model %~2
    shift
    shift
    goto parse_args
)
shift
goto parse_args

:start
if not exist "%ENV_FILE%" (
    echo [ERROR] Config not found: %ENV_FILE%
    pause
    exit /b 1
)

REM 后续 backend\/frontend\ 等相对路径都是相对仓库根目录的，先切过去
cd /d "%SCRIPT_DIR%..\.."

echo ============================================
echo   Chaowei Agent - Local Dev Mode
echo ============================================
echo.

REM Override Docker container names to localhost for local dev
REM 2026-07: 本机模式下 PG 改连外部独立服务器（10.1.2.227）
set KNB_PG_HOST=10.1.2.227
set KNB_MINIO_ENDPOINT=localhost:9000
REM 2026-07: Docker Redis 容器在 host 暴露的是 16379 端口（非默认 6379）
REM 注意：必须设 REDIS_URL（新名），不能只设 KNB_REDIS_URL（兼容旧名），
REM 因为 .env 里的 REDIS_URL 优先级更高，会把 KNB_REDIS_URL 覆盖掉。
set REDIS_URL=redis://localhost:16379/1
set KNB_REDIS_URL=redis://localhost:16379/1

echo Infra connections:
echo   PostgreSQL: 10.1.2.227:5432
echo   Redis:      localhost:16379
echo   MinIO:      localhost:9000
echo.

echo [1/3] Starting backend on port 9300...
if "%MODEL_ARG%"=="" (
    start "Backend" cmd /k "uv run python backend\app.py"
) else (
    start "Backend" cmd /k "uv run python backend\app.py %MODEL_ARG%"
)

echo [2/3] Starting frontend on port 5173...
start "Frontend" cmd /k "cd frontend && npm run dev"

echo [3/3] Starting Celery worker (async tasks)...
start "Celery" cmd /k "celery -A backend.services.knowledge_management.tasks.celery_app worker -Q kb_convert,kb_extract,kb_review,kb_sync,kb_plc,kb_eval --pool=threads --concurrency=2 --loglevel=info"

echo.
echo ============================================
echo   Backend:  http://localhost:9300
echo   API Docs: http://localhost:9300/docs
echo   Frontend: http://localhost:5173
echo   Celery:   Worker running (check window)
echo ============================================
echo.
echo Close the cmd windows to stop services.

endlocal
