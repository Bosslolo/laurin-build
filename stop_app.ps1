# Stop script for Laurin Application
# Stops all running instances of the Flask app

Write-Host "Stopping Laurin Application..." -ForegroundColor Cyan

# Find and stop Python processes running run_app_simple.py
$processes = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*run_app_simple.py*" -or 
    (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)" | Select-Object -ExpandProperty CommandLine) -like "*run_app_simple.py*"
}

if ($processes) {
    $processes | ForEach-Object {
        Write-Host "  Stopping process ID: $($_.Id)" -ForegroundColor Yellow
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Stopped all instances" -ForegroundColor Green
} else {
    Write-Host "No running instances found" -ForegroundColor Yellow
}

# Also check for processes using ports 5003 and 5004
$port5003 = Get-NetTCPConnection -LocalPort 5003 -ErrorAction SilentlyContinue
$port5004 = Get-NetTCPConnection -LocalPort 5004 -ErrorAction SilentlyContinue

if ($port5003) {
    $pid5003 = $port5003.OwningProcess
    Write-Host "  Stopping process on port 5003 (PID: $pid5003)" -ForegroundColor Yellow
    Stop-Process -Id $pid5003 -Force -ErrorAction SilentlyContinue
}

if ($port5004) {
    $pid5004 = $port5004.OwningProcess
    Write-Host "  Stopping process on port 5004 (PID: $pid5004)" -ForegroundColor Yellow
    Stop-Process -Id $pid5004 -Force -ErrorAction SilentlyContinue
}

Write-Host "Done!" -ForegroundColor Green

