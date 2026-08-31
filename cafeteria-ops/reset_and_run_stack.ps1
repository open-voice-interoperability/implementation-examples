param(
    [switch]$ClearPycache = $true,
    [switch]$UseNoBytecode = $true,
    [int]$PortClearTimeoutSeconds = 12,
    [int]$ServiceStartTimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $root ".venv\Scripts\python.exe"
$pythonExe = [System.IO.Path]::GetFullPath($pythonExe)

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

$services = @(
    @{ Name = "convener"; Port = 8300; Script = "convener_service\convener.py" },
    @{ Name = "menu_designer"; Port = 8301; Script = "agents\menu_designer\menu_designer_agent.py" },
    @{ Name = "nutrition"; Port = 8302; Script = "agents\nutrition_specialist\nutrition_agent.py" },
    @{ Name = "recipe_portion"; Port = 8303; Script = "agents\recipe_portion_specialist\recipe_portion_agent.py" },
    @{ Name = "menu_optimization"; Port = 8304; Script = "agents\menu_optimization_specialist\menu_optimization_agent.py" },
    @{ Name = "inventory"; Port = 8305; Script = "agents\inventory_specialist\inventory_agent.py" },
    @{ Name = "procurement"; Port = 8306; Script = "agents\procurement_specialist\procurement_agent.py" },
    @{ Name = "shopping_list"; Port = 8310; Script = "agents\shopping_list_specialist\shopping_list_agent.py" }
)

$ports = $services | ForEach-Object { $_.Port }
$startupLogDir = Join-Path $root "logs\startup"
New-Item -ItemType Directory -Path $startupLogDir -Force | Out-Null

function Get-ListeningEntriesForPorts {
    param([int[]]$TargetPorts)

    return Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $TargetPorts -contains $_.LocalPort }
}

function Wait-ForPortsToClear {
    param(
        [int[]]$TargetPorts,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $remaining = Get-ListeningEntriesForPorts -TargetPorts $TargetPorts
        if (-not $remaining) {
            return $true
        }
        Start-Sleep -Milliseconds 300
    }

    return -not (Get-ListeningEntriesForPorts -TargetPorts $TargetPorts)
}

function Wait-ForServicePort {
    param(
        [int]$Port,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
        if ($listener) {
            return $true
        }
        Start-Sleep -Milliseconds 300
    }

    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

Write-Host "[1/5] Stopping processes listening on ports $($ports -join ', ')"
$owningProcIds = Get-ListeningEntriesForPorts -TargetPorts $ports |
    Select-Object -ExpandProperty OwningProcess -Unique

foreach ($procId in $owningProcIds) {
    try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "  - Stopped PID $procId"
    }
    catch {
        Write-Host "  - Could not stop PID $procId ($($_.Exception.Message))"
    }
}

if (-not (Wait-ForPortsToClear -TargetPorts $ports -TimeoutSeconds $PortClearTimeoutSeconds)) {
    Write-Host "  - Warning: Some ports are still in LISTEN after $PortClearTimeoutSeconds seconds" -ForegroundColor Yellow
    $stillListening = Get-ListeningEntriesForPorts -TargetPorts $ports |
        Sort-Object LocalPort, OwningProcess |
        Select-Object LocalAddress, LocalPort, OwningProcess
    $stillListening | Format-Table -AutoSize | Out-String | Write-Host
}

if ($ClearPycache) {
    Write-Host "[2/5] Clearing __pycache__ folders"
    Get-ChildItem -Path $root -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
else {
    Write-Host "[2/5] Skipping __pycache__ cleanup"
}

Write-Host "[3/5] Starting services"
$started = @{}
foreach ($svc in $services) {
    $scriptPath = Join-Path $root $svc.Script
    if (-not (Test-Path $scriptPath)) {
        throw "Service script not found: $scriptPath"
    }

    $args = @()
    if ($UseNoBytecode) {
        $args += "-B"
    }
    # Use service-relative script path so Start-Process argument splitting does not break on workspace spaces.
    $args += $svc.Script

    $stdoutLog = Join-Path $startupLogDir ("{0}.out.log" -f $svc.Name)
    $stderrLog = Join-Path $startupLogDir ("{0}.err.log" -f $svc.Name)
    Remove-Item $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue

    $proc = Start-Process -FilePath $pythonExe -ArgumentList $args -WorkingDirectory $root -WindowStyle Minimized -PassThru -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
    $started[$svc.Port] = [PSCustomObject]@{
        Name = $svc.Name
        Proc = $proc
        Stdout = $stdoutLog
        Stderr = $stderrLog
    }

    Write-Host "  - Started $($svc.Name) on port $($svc.Port) (PID $($proc.Id))"
}

Write-Host "[4/5] Waiting for listeners"
foreach ($svc in $services) {
    $ready = Wait-ForServicePort -Port $svc.Port -TimeoutSeconds $ServiceStartTimeoutSeconds
    if ($ready) {
        Write-Host "  - Port $($svc.Port) ready"
        continue
    }

    $info = $started[$svc.Port]
    $procState = "unknown"
    try {
        $null = Get-Process -Id $info.Proc.Id -ErrorAction Stop
        $procState = "running"
    }
    catch {
        $procState = "exited"
    }

    Write-Host "  - Port $($svc.Port) did not open in $ServiceStartTimeoutSeconds sec (process $procState, PID $($info.Proc.Id))" -ForegroundColor Yellow

    if (Test-Path $info.Stderr) {
        $errTail = Get-Content $info.Stderr -Tail 8 -ErrorAction SilentlyContinue
        if ($errTail) {
            Write-Host "    stderr tail:"
            $errTail | ForEach-Object { Write-Host "      $_" }
        }
    }
}

Write-Host "[5/5] Verifying listeners"
$listeners = Get-ListeningEntriesForPorts -TargetPorts $ports |
    Sort-Object LocalPort, OwningProcess

$listenerGroups = $listeners | Group-Object LocalPort
$hadIssue = $false

foreach ($svc in $services) {
    $group = $listenerGroups | Where-Object { [int]$_.Name -eq $svc.Port }
    $count = if ($group) { $group.Count } else { 0 }

    if ($count -eq 1) {
        $pidValue = $group.Group[0].OwningProcess
        Write-Host "  [OK] Port $($svc.Port): PID $pidValue"
    }
    elseif ($count -eq 0) {
        Write-Host "  [FAIL] Port $($svc.Port): no listener"
        $hadIssue = $true
    }
    else {
        $pidList = ($group.Group | Select-Object -ExpandProperty OwningProcess) -join ", "
        Write-Host "  [FAIL] Port $($svc.Port): multiple listeners ($pidList)"
        $hadIssue = $true
    }
}

if ($hadIssue) {
    Write-Host "Reset completed with issues. Review listeners above." -ForegroundColor Yellow
    exit 1
}

Write-Host "Stack reset complete. All ports have exactly one listener." -ForegroundColor Green
exit 0
