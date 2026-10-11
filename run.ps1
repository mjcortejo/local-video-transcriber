#Requires -Version 5.1
<#
.SYNOPSIS
  Start Local Video Transcriber (API + web UI) in a psmux session.

.DESCRIPTION
  Ensures psmux is installed (winget), creates/attaches a multiplexer session with:
    - top pane: FastAPI/uvicorn (serves backend + frontend)
    - bottom pane: waits for health, opens the browser, keeps a status console
#>

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Session = "whisper"
$HostAddr = "127.0.0.1"
$Port = 8000
$Url = "http://${HostAddr}:${Port}"

function Refresh-Path {
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
    [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Get-Psmux {
  Refresh-Path
  $cmd = Get-Command psmux -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

function Ensure-Psmux {
  $psmux = Get-Psmux
  if ($psmux) { return $psmux }

  Write-Host "psmux not found. Installing with winget..."
  winget install --id marlocarlo.psmux -e --accept-package-agreements --accept-source-agreements
  Refresh-Path
  $psmux = Get-Psmux
  if (-not $psmux) {
    throw "psmux installed but not on PATH. Open a new terminal and run .\run.ps1 again."
  }
  return $psmux
}

function Ensure-Venv {
  $python = Join-Path $Root ".venv\Scripts\python.exe"
  if (-not (Test-Path $python)) {
    Write-Host "Creating virtualenv..."
    python -m venv (Join-Path $Root ".venv")
  }
  if (-not (Test-Path $python)) {
    throw "Could not create .venv. Is Python installed and on PATH?"
  }

  Write-Host "Ensuring Python dependencies..."
  & $python -m pip install --upgrade pip | Out-Null
  & $python -m pip install -r (Join-Path $Root "requirements.txt") | Out-Null
  return $python
}

function Invoke-Mux {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PsmuxPath,
    [Parameter(Mandatory = $true)]
    [string[]]$MuxArgs
  )
  & $PsmuxPath @MuxArgs
  if ($LASTEXITCODE -ne 0) {
    throw "psmux $($MuxArgs -join ' ') failed with exit code $LASTEXITCODE"
  }
}

function Test-MuxSession {
  param([string]$PsmuxPath, [string]$Name)
  & $PsmuxPath has-session -t $Name 2>$null | Out-Null
  return ($LASTEXITCODE -eq 0)
}

$psmux = Ensure-Psmux
$python = Ensure-Venv

Write-Host "Using psmux: $psmux"
Write-Host "Project:     $Root"
Write-Host "App URL:     $Url"

if (Test-MuxSession -PsmuxPath $psmux -Name $Session) {
  Write-Host "Session '$Session' already exists. Attaching..."
  & $psmux attach-session -t $Session
  exit $LASTEXITCODE
}

$serverCmd = @(
  "Set-Location -LiteralPath '$Root'"
  "`$env:PYTHONUTF8='1'"
  "& '$python' -m uvicorn app.main:app --host $HostAddr --port $Port --reload"
) -join "; "

$uiCmd = @(
  "Set-Location -LiteralPath '$Root'"
  "Write-Host 'Waiting for $Url ...'"
  "`$ok = `$false"
  "for (`$i = 0; `$i -lt 120; `$i++) {"
  "  try {"
  "    `$r = Invoke-WebRequest -Uri '$Url/api/health' -UseBasicParsing -TimeoutSec 2"
  "    if (`$r.StatusCode -eq 200) { `$ok = `$true; break }"
  "  } catch { Start-Sleep -Seconds 1 }"
  "}"
  "if (-not `$ok) { Write-Host 'Server did not become healthy in time.' -ForegroundColor Red; exit 1 }"
  "Write-Host 'Server is up. Opening browser...' -ForegroundColor Green"
  "Start-Process '$Url'"
  "Write-Host ''"
  "Write-Host 'Local Video Transcriber is running.'"
  "Write-Host '  UI/API : $Url'"
  "Write-Host '  Server : top pane (Ctrl+b then arrow keys to switch)'"
  "Write-Host '  Detach : Ctrl+b then d'"
  "Write-Host '  Stop   : close panes or: psmux kill-session -t $Session'"
  "Write-Host ''"
  "while (`$true) { Start-Sleep -Seconds 3600 }"
) -join "; "

Write-Host "Starting psmux session '$Session'..."
Invoke-Mux -PsmuxPath $psmux -MuxArgs @("new-session", "-d", "-s", $Session, "-n", "app", "-c", $Root)
Invoke-Mux -PsmuxPath $psmux -MuxArgs @("send-keys", "-t", "${Session}:app.0", $serverCmd, "Enter")
Invoke-Mux -PsmuxPath $psmux -MuxArgs @("split-window", "-t", "${Session}:app", "-v", "-c", $Root)
Invoke-Mux -PsmuxPath $psmux -MuxArgs @("send-keys", "-t", "${Session}:app.1", $uiCmd, "Enter")
Invoke-Mux -PsmuxPath $psmux -MuxArgs @("select-layout", "-t", "${Session}:app", "main-horizontal")
Invoke-Mux -PsmuxPath $psmux -MuxArgs @("select-pane", "-t", "${Session}:app.0")

Write-Host "Attaching. Detach with Ctrl+b then d."
& $psmux attach-session -t $Session
exit $LASTEXITCODE
