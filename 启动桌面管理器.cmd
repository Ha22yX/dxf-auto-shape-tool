@echo off
setlocal
title DXF Auto Shape Tool Launcher
cd /d "%~dp0"

set "PYTHON_CMD="
if exist "C:\Python314\python.exe" set "PYTHON_CMD=C:\Python314\python.exe"
if defined PYTHON_CMD goto run_launcher

for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_CMD set "PYTHON_CMD=%%P"
)
if defined PYTHON_CMD goto run_launcher

where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py"
if defined PYTHON_CMD goto run_launcher

echo Python was not found.
echo Please install Python or add it to PATH.
pause
exit /b 1

:run_launcher
"%PYTHON_CMD%" launcher.py
if errorlevel 1 (
    echo.
    echo Launcher exited with an error.
    pause
)
