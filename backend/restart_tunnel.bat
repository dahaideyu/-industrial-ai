@echo off
REM 快速重启 cntlm 隧道
REM 用法: 双击运行或在命令行执行
REM 注：echo 输出统一用英文，避免旧版 PowerShell/cmd 控制台在非 UTF-8 代码页下
REM 出现中文乱码或（chcp 65001 时）字符重复显示的问题；REM 注释是中文没关系，
REM 因为注释不会被打印到控制台。

setlocal enabledelayedexpansion

echo [1/3] Stopping cntlm...
taskkill /IM cntlm.exe /F >nul 2>&1
timeout /t 2 /nobreak

echo [2/3] Starting cntlm tunnel...
start "cntlm tunnel" /min "D:\tools\Cntlm\cntlm.exe" -f -v -c "D:\tools\Cntlm\cntlm_bosch.ini"
timeout /t 3 /nobreak

echo [3/3] Verifying tunnel (port 15432)...
powershell -Command "Test-NetConnection 127.0.0.1 -Port 15432 -WarningAction SilentlyContinue | Select-Object TcpTestSucceeded"

echo.
echo ======================================
echo   cntlm tunnel restarted
echo ======================================
echo.
pause
