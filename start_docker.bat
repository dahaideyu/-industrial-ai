@echo off
chcp 65001 >nul
REM ============================================
REM Chaowei Agent 一键启动（全套 Docker 服务，测试用）
REM 用法: start_docker.bat
REM 需要更细分的操作（down/restart/status/logs、离线打包镜像、
REM 纯 venv 本地混合开发）请去 deploy\docker\ 下用 deploy.bat / build.bat / start.bat
REM 只想启动前后端、不涉及 Docker，用同目录下的 start.bat
REM ============================================

docker --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Docker，请先安装 Docker Desktop
    pause
    exit /b 1
)

if not exist "%~dp0deploy\docker\.env" (
    echo [错误] 配置文件不存在: deploy\docker\.env，请先参考 deploy\docker\.env.example 创建
    pause
    exit /b 1
)

echo ============================================
echo   Chaowei Agent - 一键启动全套服务
echo ============================================
echo.
echo 构建并启动中（首次会拉取/构建镜像，较慢）...
docker compose -f "%~dp0deploy\docker\docker-compose.yml" up -d --build
if errorlevel 1 (
    echo [错误] 启动失败，可用 deploy\docker\deploy.bat status/logs 排查
    pause
    exit /b 1
)

echo.
echo ============================================
echo   已启动
echo   应用: http://localhost:9300
echo   查看状态/日志/停止: cd deploy\docker ^&^& deploy.bat status / logs / down
echo ============================================
pause
