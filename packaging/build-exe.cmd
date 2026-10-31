@echo off
setlocal
title Build DXF Auto Shape Tool EXE
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

set "PYTHON_CMD="
if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" set "PYTHON_CMD=%PROJECT_ROOT%\.venv\Scripts\python.exe"
if defined PYTHON_CMD goto build
if exist "C:\Python314\python.exe" set "PYTHON_CMD=C:\Python314\python.exe"
if defined PYTHON_CMD goto build

for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_CMD set "PYTHON_CMD=%%P"
)
if defined PYTHON_CMD goto build

where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py"
if defined PYTHON_CMD goto build

echo Python was not found.
pause
exit /b 1

:build
echo Using Python: %PYTHON_CMD%
"%PYTHON_CMD%" -m pip install -r "packaging\requirements-build.txt"
if errorlevel 1 goto fail

echo Building executable...
"%PYTHON_CMD%" -m PyInstaller --noconfirm --clean "packaging\dxf-auto-shape-tool.spec"
if errorlevel 1 goto fail

echo.
echo Build complete:
echo %PROJECT_ROOT%\dist\dxf-auto-shape-tool-v*.exe
if not defined CI pause
exit /b 0

:fail
echo.
echo Build failed.
if not defined CI pause
exit /b 1
