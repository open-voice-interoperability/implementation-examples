$ErrorActionPreference = "Stop"

# ---- EDIT THIS ----
$VenvPython = "C:\Users\dahl\OneDrive\Open Voice Network\GitHub\implementation-examples\.venv\Scripts\python.exe"
# -------------------

if (-not (Test-Path $VenvPython)) {
    throw "Python executable not found: $VenvPython"
}

Write-Host "Using Python:" $VenvPython -ForegroundColor Cyan

# 1) Clear pip index overrides in current shell
Remove-Item Env:PIP_INDEX_URL -ErrorAction SilentlyContinue
Remove-Item Env:PIP_EXTRA_INDEX_URL -ErrorAction SilentlyContinue

# 2) Clear persistent User env vars
[Environment]::SetEnvironmentVariable("PIP_INDEX_URL", $null, "User")
[Environment]::SetEnvironmentVariable("PIP_EXTRA_INDEX_URL", $null, "User")

# 3) Try to clear Machine env vars (may require admin; ignore if not permitted)
try {
    [Environment]::SetEnvironmentVariable("PIP_INDEX_URL", $null, "Machine")
    [Environment]::SetEnvironmentVariable("PIP_EXTRA_INDEX_URL", $null, "Machine")
} catch {
    Write-Host "No Machine-level env permission (this is OK)." -ForegroundColor Yellow
}

# 4) Remove pip config keys that force custom indexes
$configKeys = @(
    "global.index-url",
    "global.extra-index-url",
    "install.index-url",
    "install.extra-index-url"
)

function Unset-PipConfigKeyIfPresent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    try {
        & $VenvPython -m pip config unset $Key 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Unset pip config key: $Key" -ForegroundColor DarkGray
        }
    } catch {
        $message = $_ | Out-String
        if ($message -match "No such key") {
            Write-Host "pip config key not set (skipping): $Key" -ForegroundColor DarkGray
            return
        }
        throw
    }
}

foreach ($key in $configKeys) {
    Unset-PipConfigKeyIfPresent -Key $key
}

# 5) Clean pip.ini files if they contain index settings / TestPyPI refs
$pipIniCandidates = @(
    "$env:APPDATA\pip\pip.ini",
    "$env:PROGRAMDATA\pip\pip.ini"
)

foreach ($ini in $pipIniCandidates) {
    if (Test-Path $ini) {
        $backup = "$ini.bak.$(Get-Date -Format 'yyyyMMddHHmmss')"
        Copy-Item $ini $backup -Force
        $content = Get-Content $ini
        $filtered = $content | Where-Object {
            $_ -notmatch '^\s*(index-url|extra-index-url)\s*=' -and
            $_ -notmatch 'test\.pypi\.org/simple'
        }
        Set-Content -Path $ini -Value $filtered -Encoding UTF8
        Write-Host "Cleaned: $ini (backup: $backup)" -ForegroundColor Yellow
    }
}

# 6) Repair bootstrap tools, then force install build stack from real PyPI
& $VenvPython -m ensurepip --upgrade --default-pip
& $VenvPython -m pip install --upgrade pip setuptools wheel --index-url https://pypi.org/simple

# 7) Verify
& $VenvPython -m pip --version
& $VenvPython -m pip config list -v

# 8) Install package with PyPI primary + TestPyPI extra
& $VenvPython -m pip install events --index-url https://pypi.org/simple --extra-index-url https://test.pypi.org/simple

Write-Host "`nDone. If another terminal still has old env vars, open a fresh terminal and retry." -ForegroundColor Green