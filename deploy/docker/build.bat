@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================
REM Offline image bundle builder for app, worker, lean runtime and PostgreSQL.
REM Usage: build.bat [version/tag]
REM Example: build.bat 1.0.0
REM Image names must match the image fields in docker-compose.yml.
REM ============================================

set "IMAGE_NAME=industrial-ai"
set "VERSION=%~1"
if "%VERSION%"=="" set "VERSION=latest"

set "APP_IMAGE=%IMAGE_NAME%:%VERSION%"
set "WORKER_IMAGE=%IMAGE_NAME%-worker:%VERSION%"
set "LEAN_IMAGE=%IMAGE_NAME%-lean:%VERSION%"
set "TAR_FILE=%IMAGE_NAME%-%VERSION%-bundle.tar"

REM Read the PostgreSQL image from docker-compose.yml.
set "PG_IMAGE="
for /f "tokens=2 delims= " %%i in ('findstr /r /c:"image: *timescale/timescaledb" "%~dp0docker-compose.yml"') do set "PG_IMAGE=%%i"
if "%PG_IMAGE%"=="" (
    echo ERROR: Cannot find the timescale/timescaledb image in docker-compose.yml.
    pause
    exit /b 1
)

echo ============================================
echo Industrial AI offline bundle builder
echo App image:      %APP_IMAGE%
echo Worker image:   %WORKER_IMAGE%
echo Lean image:     %LEAN_IMAGE%
echo Database image: %PG_IMAGE%
echo ============================================
echo.

REM 0. Encrypt prompt files with the pre-configured fixed key.
echo [0/5] Encrypting prompt files...
python "%~dp0..\..\scripts\encrypt_prompts.py"
if errorlevel 1 (
    echo ERROR: Prompt encryption failed. Check PROMPT_ENCRYPT_KEY.
    pause
    exit /b 1
)
echo.

REM 1. Build the complete application image.
echo [1/5] Building app image %APP_IMAGE% with Cython...
docker build --platform linux/arm64 -f "%~dp0Dockerfile" --build-arg COMPILE_SOURCE=true --build-arg VITE_ENABLE_SQL_QA=true -t %APP_IMAGE% "%~dp0..\.."
if errorlevel 1 (
    echo ERROR: App image build failed.
    pause
    exit /b 1
)
echo.

REM 2. Build the worker image.
echo [2/5] Building worker image %WORKER_IMAGE%...
docker build --platform linux/arm64 -f "%~dp0Dockerfile" --target final-worker --build-arg COMPILE_SOURCE=true -t %WORKER_IMAGE% "%~dp0..\.."
if errorlevel 1 (
    echo ERROR: Worker image build failed.
    pause
    exit /b 1
)
echo.

REM 3. Build the lean backend image.
echo [3/5] Building lean image %LEAN_IMAGE%...
docker build --platform linux/arm64 -f "%~dp0Dockerfile" --target final-base --build-arg COMPILE_SOURCE=true -t %LEAN_IMAGE% "%~dp0..\.."
if errorlevel 1 (
    echo ERROR: Lean image build failed.
    pause
    exit /b 1
)
echo.

REM 4. Pull the PostgreSQL/TimescaleDB image when missing locally.
echo [4/5] Checking database image %PG_IMAGE%...
docker image inspect %PG_IMAGE% >nul 2>&1
if errorlevel 1 (
    docker pull %PG_IMAGE%
    if errorlevel 1 (
        echo ERROR: Database image pull failed. Check the registry mirror.
        pause
        exit /b 1
    )
) else (
    echo Database image already exists locally; skipping pull.
)
echo.

REM 5. Export all images into one tar archive.
echo [5/5] Exporting images to %TAR_FILE%...
docker save -o %TAR_FILE% %APP_IMAGE% %WORKER_IMAGE% %LEAN_IMAGE% %PG_IMAGE%
if errorlevel 1 (
    echo ERROR: Image export failed.
    pause
    exit /b 1
)

echo ============================================
echo Bundle completed.
echo.
echo Image archive: %TAR_FILE%
echo.
echo Deployment steps:
echo   1. Upload %TAR_FILE% to the server.
echo   2. docker load -i %TAR_FILE%
echo   3. Create deploy/docker/.env from .env.example.
echo   4. cd deploy/docker
echo      To use the bundled local PostgreSQL:
echo        set IMAGE_TAG=%VERSION%
echo        docker compose --profile local-db up -d
echo      To keep using an external PostgreSQL:
echo        set IMAGE_TAG=%VERSION%
echo        docker compose up -d
echo   Do not add --build; reuse the images loaded from the archive.
echo ============================================
pause
