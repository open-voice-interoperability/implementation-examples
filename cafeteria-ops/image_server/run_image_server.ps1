# Starts the local image service (image_server.py) on port 8320 if it isn't
# already running. It stays up across stack restarts -- loading the model
# takes a while -- so reset_and_run_stack.ps1 calls this rather than
# restarting it. Stop it with:  .\run_image_server.ps1 -Stop
#
# One-time setup (its environment lives outside the OneDrive-synced repo):
#   uv venv --python 3.11 "$env:LOCALAPPDATA\cafeteria-ops\image-venv"
#   uv pip install --python "$env:LOCALAPPDATA\cafeteria-ops\image-venv\Scripts\python.exe" torch --index-url https://download.pytorch.org/whl/cu128
#   uv pip install --python "$env:LOCALAPPDATA\cafeteria-ops\image-venv\Scripts\python.exe" -r requirements.txt
# and accept the FLUX.1-schnell terms at huggingface.co/black-forest-labs/FLUX.1-schnell
# (HF_API_KEY in ..\.env is used for the download).
param([switch]$Stop, [int]$Port = 8320)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "cafeteria-ops\image-venv\Scripts\python.exe"
$listening = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue

if ($Stop) {
    if ($listening) {
        $listening | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force }
        Write-Host "Stopped the image service on port $Port"
    } else {
        Write-Host "The image service isn't running"
    }
    return
}
if ($listening) { Write-Host "Image service already running on port $Port"; return }
if (-not (Test-Path $python)) { Write-Host "Image service not set up (no $python) -- skipping"; return }

# The model download needs the Hugging Face token from cafeteria-ops\.env.
$envFile = Join-Path (Split-Path -Parent $here) ".env"
if (Test-Path $envFile) {
    $line = Select-String -Path $envFile -Pattern '^\s*HF_API_KEY\s*=\s*(\S+)' | Select-Object -First 1
    if ($line) { $env:HF_TOKEN = $line.Matches[0].Groups[1].Value.Trim('"', "'") }
}

$logDir = Join-Path (Split-Path -Parent $here) "logs\startup"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Start-Process -FilePath $python -ArgumentList "`"$(Join-Path $here 'image_server.py')`"" -WorkingDirectory $here -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir "image_server.out.log") -RedirectStandardError (Join-Path $logDir "image_server.err.log")
Write-Host "Started the image service on port $Port (the model takes a minute or two to load; see logs\startup\image_server.err.log)"
