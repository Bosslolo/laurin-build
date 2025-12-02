# Auto-start script for Laurin Application
# This script checks if the app is running and starts it if not
# Designed to run on system startup

$ErrorActionPreference = "SilentlyContinue"

# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Function to check if port is in use
function Test-Port {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    return $null -ne $connection
}

# Check if ports are already in use
$port5003Running = Test-Port -Port 5003
$port5004Running = Test-Port -Port 5004

if ($port5003Running -and $port5004Running) {
    # App is already running, exit silently
    exit 0
}

# Wait a bit for system to fully start (network, services, etc.)
Start-Sleep -Seconds 60

# Check Windows Firewall rules (run silently, may need admin)
try {
    $firewallRule5003 = Get-NetFirewallRule -DisplayName "Laurin App Port 5003" -ErrorAction SilentlyContinue
    $firewallRule5004 = Get-NetFirewallRule -DisplayName "Laurin App Port 5004" -ErrorAction SilentlyContinue

    if (-not $firewallRule5003) {
        New-NetFirewallRule -DisplayName "Laurin App Port 5003" -Direction Inbound -LocalPort 5003 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue | Out-Null
    }

    if (-not $firewallRule5004) {
        New-NetFirewallRule -DisplayName "Laurin App Port 5004" -Direction Inbound -LocalPort 5004 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue | Out-Null
    }
} catch {
    # Firewall rules may require admin, continue anyway
}

# Activate virtual environment and start the app
$venvPython = Join-Path $scriptDir "venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    # Log error if needed (for debugging)
    # Write-EventLog -LogName Application -Source "LaurinApp" -EventId 1001 -EntryType Error -Message "Virtual environment not found at $venvPython" -ErrorAction SilentlyContinue
    exit 1
}

# Start port 5004 in background
$port5004Script = Join-Path $scriptDir "run_app_simple.py"
$logFile5004 = Join-Path $scriptDir "instance\app_5004.log"
$logFile5004Err = Join-Path $scriptDir "instance\app_5004.err.log"
Start-Process -FilePath $venvPython -ArgumentList $port5004Script, "5004" -WindowStyle Hidden -RedirectStandardOutput $logFile5004 -RedirectStandardError $logFile5004Err

# Wait a moment before starting port 5003
Start-Sleep -Seconds 3

# Start port 5003 in background
$logFile5003 = Join-Path $scriptDir "instance\app_5003.log"
$logFile5003Err = Join-Path $scriptDir "instance\app_5003.err.log"
Start-Process -FilePath $venvPython -ArgumentList $port5004Script, "5003" -WindowStyle Hidden -RedirectStandardOutput $logFile5003 -RedirectStandardError $logFile5003Err

exit 0

