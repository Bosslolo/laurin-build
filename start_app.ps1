# PowerShell script to start the Flask application with network access
# Enables access from tablets/phones on http://10.100.5.89:5003 and http://10.100.5.89:5004

Write-Host "Starting Laurin Application with Network Access..." -ForegroundColor Cyan

# Load environment variables from production.env if present
$scriptDir = $PWD
$envFile = Join-Path $scriptDir "production.env"
$allowedKeys = @(
    "PAYPAL_CLIENT_ID",
    "PAYPAL_CLIENT_SECRET",
    "PAYPAL_IPN_URL",
    "PAYPAL_ENV",
    "PAYPAL_POLL_INTERVAL_SECONDS"
)
if (Test-Path $envFile) {
    Write-Host "Loading PayPal environment variables from production.env..." -ForegroundColor Cyan
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $key = $line.Substring(0, $idx).Trim()
        if ($allowedKeys -notcontains $key) { return }
        $value = $line.Substring($idx + 1).Trim()
        if ($key.Length -gt 0) {
            Set-Item -Path ("Env:" + $key) -Value $value
        }
    }
}

# Force local SQLite usage for standalone mode
$localDbPath = Join-Path $scriptDir "instance\local.db"
$sqliteUrl = "sqlite:///" + ($localDbPath -replace '\\', '/')
Set-Item -Path Env:DATABASE_URL -Value $sqliteUrl

# Get current IP address
$currentIP = "10.100.5.89"
Write-Host "Using IP address: $currentIP" -ForegroundColor Yellow

# Check Windows Firewall rules
Write-Host "Checking Windows Firewall rules..." -ForegroundColor Cyan
try {
    $firewallRule5003 = Get-NetFirewallRule -DisplayName "Laurin App Port 5003" -ErrorAction SilentlyContinue
    $firewallRule5004 = Get-NetFirewallRule -DisplayName "Laurin App Port 5004" -ErrorAction SilentlyContinue

    if (-not $firewallRule5003) {
        Write-Host "   Adding firewall rule for port 5003..." -ForegroundColor Yellow
        New-NetFirewallRule -DisplayName "Laurin App Port 5003" -Direction Inbound -LocalPort 5003 -Protocol TCP -Action Allow -ErrorAction Stop | Out-Null
        Write-Host "   Firewall rule added for port 5003" -ForegroundColor Green
    } else {
        Write-Host "   Firewall rule already exists for port 5003" -ForegroundColor Green
    }

    if (-not $firewallRule5004) {
        Write-Host "   Adding firewall rule for port 5004..." -ForegroundColor Yellow
        New-NetFirewallRule -DisplayName "Laurin App Port 5004" -Direction Inbound -LocalPort 5004 -Protocol TCP -Action Allow -ErrorAction Stop | Out-Null
        Write-Host "   Firewall rule added for port 5004" -ForegroundColor Green
    } else {
        Write-Host "   Firewall rule already exists for port 5004" -ForegroundColor Green
    }
} catch {
    Write-Host "   WARNING: Could not configure firewall rules. You may need to run as Administrator." -ForegroundColor Yellow
    Write-Host "   You can manually add firewall rules or run this script as Administrator." -ForegroundColor Yellow
}

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
& .\venv\Scripts\Activate.ps1

Write-Host "Starting Flask application on ports 5003 and 5004..." -ForegroundColor Cyan
Write-Host ""

# Get script directory and paths
$venvPython = Join-Path $scriptDir "venv\Scripts\python.exe"
$port5004Script = Join-Path $scriptDir "run_app_simple.py"
$port5003Script = Join-Path $scriptDir "run_app_simple.py"
$logFile5004 = Join-Path $scriptDir "instance\app_5004.log"
$logFile5004Err = Join-Path $scriptDir "instance\app_5004.err.log"
$logFile5003 = Join-Path $scriptDir "instance\app_5003.log"
$logFile5003Err = Join-Path $scriptDir "instance\app_5003.err.log"

# Ensure instance directory exists
$instanceDir = Join-Path $scriptDir "instance"
if (-not (Test-Path $instanceDir)) {
    New-Item -ItemType Directory -Path $instanceDir -Force | Out-Null
}

# Start port 5004 in hidden window
Write-Host "Starting port 5004 in background (hidden)..." -ForegroundColor Yellow
Start-Process -FilePath $venvPython -ArgumentList $port5004Script, "5004" -WindowStyle Hidden -RedirectStandardOutput $logFile5004 -RedirectStandardError $logFile5004Err

# Wait a moment before starting port 5003
Start-Sleep -Seconds 3

# Start port 5003 in hidden window
Write-Host "Starting port 5003 in background (hidden)..." -ForegroundColor Yellow
Start-Process -FilePath $venvPython -ArgumentList $port5003Script, "5003" -WindowStyle Hidden -RedirectStandardOutput $logFile5003 -RedirectStandardError $logFile5003Err

Write-Host ""
Write-Host "Access URLs:" -ForegroundColor Cyan
Write-Host "   Port 5003: http://10.100.5.89:5003 or http://localhost:5003" -ForegroundColor White
Write-Host "   Port 5004: http://10.100.5.89:5004 or http://localhost:5004" -ForegroundColor White
Write-Host ""
Write-Host "Both Flask apps are running in the background (hidden windows)." -ForegroundColor Green
Write-Host "Logs are saved to:" -ForegroundColor Cyan
Write-Host "   Port 5003 (stdout): $logFile5003" -ForegroundColor White
Write-Host "   Port 5003 (stderr): $logFile5003Err" -ForegroundColor White
Write-Host "   Port 5004 (stdout): $logFile5004" -ForegroundColor White
Write-Host "   Port 5004 (stderr): $logFile5004Err" -ForegroundColor White
Write-Host ""
Write-Host "To stop the apps, run: .\stop_app.ps1" -ForegroundColor Yellow
Write-Host ""

