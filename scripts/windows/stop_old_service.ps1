$ids = @()

try {
    $conns = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $ids += $conn.OwningProcess
    }
} catch {
}

$procs = Get-CimInstance Win32_Process
foreach ($proc in $procs) {
    if ($proc.Name -like "python*" -and (
        $proc.CommandLine -like "*uvicorn*" -or
        $proc.CommandLine -like "*backend.app*" -or
        $proc.CommandLine -like "*spawn_main*"
    )) {
        $ids += $proc.ProcessId
    }
}

$seen = @{}
foreach ($id in $ids) {
    if ($id -and -not $seen.ContainsKey($id)) {
        $seen[$id] = $true
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
}
