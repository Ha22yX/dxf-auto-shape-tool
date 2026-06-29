@echo off
chcp 65001 >nul
setlocal

title DXF 自动图形工具服务
cd /d "%~dp0"

echo ========================================
echo DXF 自动图形工具服务
echo ========================================
echo.

echo 正在关闭旧的服务实例...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ids = @();" ^
  "try { $ids += Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess } catch {}" ^
  "$ids += Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'uvicorn|backend\.app|spawn_main' } | Select-Object -ExpandProperty ProcessId;" ^
  "$ids | Where-Object { $_ } | Sort-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"

echo.
where python >nul 2>nul
if errorlevel 1 (
    echo 没有找到 python，请先安装 Python 或把 Python 加入 PATH。
    echo.
    pause
    exit /b 1
)

python -c "import uvicorn" >nul 2>nul
if errorlevel 1 (
    echo 没有找到 uvicorn，请先安装依赖:
    echo pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo 正在启动服务...
echo 访问地址: http://127.0.0.1:8000/
echo 关闭这个窗口即可停止服务。
echo.

start "" powershell -WindowStyle Hidden -NoProfile -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8000/'"

python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000

echo.
echo 服务已停止。如果是异常退出，请把上面的错误信息发给我。
pause
endlocal
