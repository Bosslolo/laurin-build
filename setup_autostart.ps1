# Setup script to configure automatic startup for Laurin Application
# Run this script once to configure auto-start

Write-Host "Setting up automatic startup for Laurin Application..." -ForegroundColor Cyan
Write-Host ""

# Check if running as administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "WARNING: Not running as Administrator." -ForegroundColor Yellow
    Write-Host "Some features may require administrator privileges." -ForegroundColor Yellow
    Write-Host ""
}

# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $scriptDir "start_app_auto.ps1"

# Method 1: Add to Windows Startup folder (simpler, no admin needed)
Write-Host "Method 1: Adding to Startup folder..." -ForegroundColor Cyan
$startupFolder = [Environment]::GetFolderPath("Startup")
$startupShortcut = Join-Path $startupFolder "Laurin App.lnk"

try {
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($startupShortcut)
    $Shortcut.TargetPath = "powershell.exe"
    $Shortcut.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`""
    $Shortcut.WorkingDirectory = $scriptDir
    $Shortcut.Save()
    Write-Host "  [OK] Added shortcut to Startup folder" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Failed to create startup shortcut: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# Method 2: Create Task Scheduler task (more robust, requires admin)
if ($isAdmin) {
    Write-Host "Method 2: Creating Task Scheduler task..." -ForegroundColor Cyan
    
    $taskName = "LaurinAppAutoStart"
    $taskDescription = "Automatically starts Laurin Application on system startup"
    
    # Remove existing task if it exists
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "  Removed existing task" -ForegroundColor Yellow
    }
    
    try {
        # Create action
        $action = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`"" `
            -WorkingDirectory $scriptDir
        
        # Create trigger (on system startup, delay 1 minute)
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $trigger.Delay = "PT1M"  # 1 minute delay
        
        # Create settings
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable:$false
        
        # Create principal (run as current user)
        $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
        
        # Register the task
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $taskDescription | Out-Null
        
        Write-Host "  [OK] Created Task Scheduler task: $taskName" -ForegroundColor Green
        Write-Host "      The app will start automatically 1 minute after system startup" -ForegroundColor Gray
    } catch {
        Write-Host "  [ERROR] Failed to create scheduled task: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "Method 2: Skipping Task Scheduler (requires Administrator)" -ForegroundColor Yellow
    Write-Host "  To use Task Scheduler, run this script as Administrator" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "The application will now start automatically when you:" -ForegroundColor Cyan
Write-Host "  - Log in to Windows (Startup folder method)" -ForegroundColor White
if ($isAdmin) {
    Write-Host "  - Restart your computer (Task Scheduler method)" -ForegroundColor White
}
Write-Host ""
Write-Host "To test auto-start:" -ForegroundColor Cyan
Write-Host "  1. Restart your computer" -ForegroundColor White
Write-Host "  2. Wait 1-2 minutes after login" -ForegroundColor White
Write-Host "  3. Check http://localhost:5003 or http://localhost:5004" -ForegroundColor White
Write-Host ""
Write-Host "To disable auto-start:" -ForegroundColor Cyan
Write-Host "  - Remove the shortcut from: $startupFolder" -ForegroundColor White
if ($isAdmin) {
    Write-Host "  - Or run: Unregister-ScheduledTask -TaskName LaurinAppAutoStart -Confirm:`$false" -ForegroundColor White
}
Write-Host ""

