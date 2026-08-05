@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Get script directory
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Defaults
REM HOST/PORT 留空＝不覆盖，实际监听地址/端口由 .env 的 FASTAPI_HOST/FASTAPI_PORT 决定
REM （单一配置来源）；只有显式传 -h/-p 才会覆盖 .env。
set "HOST="
set "PORT="
set "RELOAD=false"
set "ENV_FILE=%SCRIPT_DIR%.env"
set "MODEL="

REM Parse args
:parse_args
if "%~1"=="" goto args_done

if /I "%~1"=="-h" (
    set "HOST=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--host" (
    set "HOST=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="-p" (
    set "PORT=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--port" (
    set "PORT=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="-r" (
    set "RELOAD=true"
    shift
    goto parse_args
)
if /I "%~1"=="--reload" (
    set "RELOAD=true"
    shift
    goto parse_args
)
if /I "%~1"=="-e" (
    set "ENV_FILE=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--env" (
    set "ENV_FILE=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="-m" (
    set "MODEL=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--model" (
    set "MODEL=%~2"
    shift
    shift
    goto parse_args
)

echo Unknown argument: %~1
exit /b 1

:args_done
REM Activate venv if present
if exist "venv\Scripts\activate.bat" (
    echo [venv] Activating virtual environment
    call "venv\Scripts\activate.bat"
)

REM Build startup command
REM 只有显式传了 -h/-p 才追加 --host/--port（覆盖 .env）；不传就让 app.py
REM 自己读 FASTAPI_HOST/FASTAPI_PORT，不在这里另设一份默认值跟 .env 打架。
set "CMD=python app.py --env %ENV_FILE%"
if not "%HOST%"=="" (
    set "CMD=%CMD% --host %HOST%"
)
if not "%PORT%"=="" (
    set "CMD=%CMD% --port %PORT%"
)
if not "%MODEL%"=="" (
    set "CMD=%CMD% --model %MODEL%"
)

echo ========================================
echo   Chaowei Agent Backend
echo ========================================
echo Config file: %ENV_FILE%
echo Starting AI Report service（host/port 未显式指定时以 .env 的 FASTAPI_HOST/FASTAPI_PORT 为准）...
echo Command: %CMD%
echo.

call %CMD%
exit /b %ERRORLEVEL%
