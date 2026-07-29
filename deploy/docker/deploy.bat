@echo off
chcp 65001 >nul
REM ============================================
REM Industrial AI Windows 一键部署脚本
REM 用法: deploy.bat [操作]
REM   操作: up（默认）| build | down | restart | status | logs
REM 说明: up/restart 不带 --build —— 镜像已存在（docker load 或此前构建过）
REM       时直接复用，与 build.bat 离线打包流程一致；镜像不存在时 compose
REM       会按 build 配置自动构建。改了代码要重新构建镜像用 deploy.bat build。
REM ============================================

setlocal enabledelayedexpansion

set ACTION=%1
if "%ACTION%"=="" set ACTION=up

echo ==========================================
echo   Industrial AI - Windows Docker 部署
echo   操作: %ACTION%
echo ==========================================

REM 检查 Docker
docker --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker 未安装，请先安装 Docker Desktop for Windows
    pause
    exit /b 1
)

docker compose version >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker Compose 未安装
    pause
    exit /b 1
)

REM 检查 .env（%~dp0 锚定本脚本所在目录，不依赖调用者当前工作目录）
if not exist "%~dp0.env" (
    echo ❌ .env 文件不存在，请先配置: %~dp0.env
    pause
    exit /b 1
)

if "%ACTION%"=="up" goto do_up
if "%ACTION%"=="build" goto do_build
if "%ACTION%"=="down" goto do_down
if "%ACTION%"=="restart" goto do_restart
if "%ACTION%"=="status" goto do_status
if "%ACTION%"=="logs" goto do_logs
echo ❌ 未知操作: %ACTION%
echo 可选: up ^| build ^| down ^| restart ^| status ^| logs
pause
exit /b 1

:do_up
echo.
echo 🚀 启动全部服务（复用已有镜像，缺失时自动构建）...
docker compose -f "%~dp0docker-compose.yml" up -d
echo.
echo ⏳ 等待服务就绪（30秒）...
timeout /t 30 /nobreak >nul
echo.
echo 📊 服务状态:
docker compose -f "%~dp0docker-compose.yml" ps
echo.
echo ==========================================
echo   ✅ 部署完成！
echo ==========================================
echo.
echo   应用: http://localhost:9300
echo   MinIO Console: http://localhost:9001
echo.
goto end

:do_down
echo.
echo 🛑 停止全部服务...
docker compose -f "%~dp0docker-compose.yml" down
echo ✅ 已停止
goto end

:do_build
echo.
echo 🔨 重新构建镜像...
docker compose -f "%~dp0docker-compose.yml" build
if errorlevel 1 (
    echo ❌ 构建失败
    goto end
)
echo ✅ 构建完成，运行 deploy.bat restart 使用新镜像
goto end

:do_restart
echo.
echo 🔄 重启全部服务（复用已有镜像）...
docker compose -f "%~dp0docker-compose.yml" down
docker compose -f "%~dp0docker-compose.yml" up -d
echo ✅ 重启完成
goto end

:do_status
echo.
docker compose -f "%~dp0docker-compose.yml" ps
goto end

:do_logs
docker compose -f "%~dp0docker-compose.yml" logs -f
goto end

:end
pause
