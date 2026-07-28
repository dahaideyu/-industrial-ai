@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM ============================================
REM Chaowei Agent 一键启动（仅前端 + 后端，不涉及 Docker）
REM 用法: start.bat [--env 配置文件] [--model 模型名]
REM 依赖的数据库/Redis/MinIO 等基础设施需自行准备好（外部服务器或已起的 Docker 容器）
REM 需要连 Docker 一起起的完整环境，用同目录下的 start_docker.bat
REM ============================================

set "ENV_FILE=%~dp0deploy\docker\.env"
set "MODEL_ARG="

:parse_args
if "%~1"=="" goto start
if "%~1"=="--env" (
    set "ENV_FILE=%~2"
    shift
    shift
    goto parse_args
)
if "%~1"=="--model" (
    set "MODEL_ARG=--model %~2"
    shift
    shift
    goto parse_args
)
shift
goto parse_args

:start
if not exist "%ENV_FILE%" (
    echo [错误] 配置文件不存在: %ENV_FILE%
    pause
    exit /b 1
)

cd /d "%~dp0"

echo ============================================
echo   Chaowei Agent - 启动前端 + 后端
echo ============================================
echo.

echo [1/2] 启动后端 (端口 9300)...
if "%MODEL_ARG%"=="" (
    start "Backend" cmd /k "uv run python backend\app.py"
) else (
    start "Backend" cmd /k "uv run python backend\app.py %MODEL_ARG%"
)

echo [2/2] 启动前端 (端口 5173)...
start "Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo ============================================
echo   后端 API:  http://localhost:9300
echo   API 文档:  http://localhost:9300/docs
echo   前端页面:  http://localhost:5173
echo ============================================
echo.
echo 关闭对应 cmd 窗口即可停止服务
