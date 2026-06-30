@echo off
setlocal
title DXF Auto Shape Tool Launcher
cd /d "%~dp0"

set "PYTHON_CMD="
set "PYTHONW_CMD="

if exist "C:\Python314\pythonw.exe" set "PYTHONW_CMD=C:\Python314\pythonw.exe"
if exist "C:\Python314\python.exe" set "PYTHON_CMD=C:\Python314\python.exe"
if defined PYTHONW_CMD goto run_launcher_hidden

for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_CMD (
        set "PYTHON_CMD=%%P"
        for %%D in ("%%~dpP.") do (
            if exist "%%~fD\pythonw.exe" set "PYTHONW_CMD=%%~fD\pythonw.exe"
        )
    )
)
if defined PYTHONW_CMD goto run_launcher_hidden
if defined PYTHON_CMD goto run_launcher

where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py"
if defined PYTHON_CMD goto run_launcher

echo Python was not found.
echo Please install Python or add it to PATH.
pause
exit /b 1

:run_launcher_hidden
start "" "%PYTHONW_CMD%" "%~dp0launcher.py"
exit /b 0

:run_launcher
"%PYTHON_CMD%" launcher.py
if errorlevel 1 (
    echo.
    echo Launcher exited with an error.
    pause
)
