@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Get script directory
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Defaults
set "HOST=0.0.0.0"
set "PORT=9300"
set "RELOAD=false"
set "ENV_FILE=.env"
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
set "CMD=python app.py --env %ENV_FILE%"
if not "%MODEL%"=="" (
    set "CMD=%CMD% --model %MODEL%"
)

echo ========================================
echo   Chaowei Agent Backend
echo ========================================
echo Config file: %ENV_FILE%
echo Starting AI Report service (%HOST%:%PORT%)...
echo Command: %CMD%
echo.

call %CMD%
exit /b %ERRORLEVEL%
