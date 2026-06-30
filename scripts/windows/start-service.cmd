@echo off
setlocal
title DXF Auto Shape Tool Service
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

echo ========================================
echo DXF Auto Shape Tool Service
echo ========================================
echo.

echo Stopping old service instances...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%stop_old_service.ps1"

set "PYTHON_CMD="
if exist "C:\Python314\python.exe" set "PYTHON_CMD=C:\Python314\python.exe"
if defined PYTHON_CMD goto check_deps

for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_CMD set "PYTHON_CMD=%%P"
)
if defined PYTHON_CMD goto check_deps

where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py"
if defined PYTHON_CMD goto check_deps

goto no_python

:check_deps
echo Using Python: %PYTHON_CMD%
"%PYTHON_CMD%" -c "import uvicorn" >nul 2>nul
if errorlevel 1 goto no_uvicorn

echo.
echo Starting service...
echo URL: http://127.0.0.1:8000/
echo Close this window to stop the service.
echo.

start "" powershell -WindowStyle Hidden -NoProfile -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8000/'"

"%PYTHON_CMD%" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000

echo.
echo Service stopped. If it exited unexpectedly, send me the error above.
pause
exit /b

:no_python
echo Python was not found.
echo Please install Python or add it to PATH.
pause
exit /b 1

:no_uvicorn
echo uvicorn was not found.
echo Run this command first:
echo pip install -r requirements.txt
pause
exit /b 1
