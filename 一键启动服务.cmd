@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo 正在关闭旧的服务实例...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ids = @();" ^
  "try { $ids += Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess } catch {}" ^
  "$ids += Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'uvicorn|backend\.app|spawn_main' } | Select-Object -ExpandProperty ProcessId;" ^
  "$ids | Where-Object { $_ } | Sort-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"

echo 正在启动服务...
start "DXF 自动图形工具服务" cmd /k "chcp 65001 >nul && cd /d ""%~dp0"" && python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000"

echo.
echo 服务已启动: http://127.0.0.1:8000/
echo 如果浏览器没有自动打开，请复制上面的地址访问。
start "" "http://127.0.0.1:8000/"

endlocal
