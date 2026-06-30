@echo off
setlocal
title Build DXF Auto Shape Tool EXE
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

set "PYTHON_CMD="
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
"%PYTHON_CMD%" -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    "%PYTHON_CMD%" -m pip install pyinstaller
    if errorlevel 1 goto fail
)

echo Building executable...
"%PYTHON_CMD%" -m PyInstaller --noconfirm --clean "packaging\dxf-auto-shape-tool.spec"
if errorlevel 1 goto fail

echo.
echo Build complete:
echo %PROJECT_ROOT%\dist\DXF Auto Shape Tool EXE was generated.
pause
exit /b 0

:fail
echo.
echo Build failed.
pause
exit /b 1
