<#
.SYNOPSIS
  Starts the FORGE-0 development stack on Windows: PostgreSQL (Docker), backend (FastAPI) and frontend (Vite).

.DESCRIPTION
  Works with Docker Desktop (docker on PATH) or Docker Engine inside WSL2. With WSL, a hidden
  `wsl -- sleep infinity` session is kept open so the distro (and dockerd) is not stopped while idle.

  Ports: API http://127.0.0.1:8010, UI http://127.0.0.1:5173, PostgreSQL 127.0.0.1:5433.
  Stop everything with scripts/stop.ps1. On low-memory machines prefer scripts/lite.ps1.
#>
param(
  [switch]$SkipFrontend,
  [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $Root 'data'
New-Item -ItemType Directory -Force $DataDir | Out-Null

if (-not (Test-Path (Join-Path $Root '.env'))) {
  Copy-Item (Join-Path $Root '.env.example') (Join-Path $Root '.env')
  Write-Host 'Created .env from .env.example'
}

# --- Docker -----------------------------------------------------------------------
$UseWsl = -not (Get-Command docker -ErrorAction SilentlyContinue)
if ($UseWsl) {
  if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) { throw 'Neither docker nor wsl is available.' }
  $pidFile = Join-Path $DataDir '.wsl-keepalive.pid'
  $alive = $false
  if (Test-Path $pidFile) {
    $alive = [bool](Get-Process -Id (Get-Content $pidFile) -ErrorAction SilentlyContinue)
  }
  if (-not $alive) {
    $proc = Start-Process wsl -ArgumentList '--', 'sleep', 'infinity' -WindowStyle Hidden -PassThru
    Set-Content $pidFile $proc.Id
    Write-Host "Started WSL keep-alive (pid $($proc.Id))"
  }
  $wslRoot = (wsl wslpath -a ($Root -replace '\\', '/')).Trim()
  wsl -- bash -lc "cd '$wslRoot' && docker compose up -d db"
} else {
  Push-Location $Root; docker compose up -d db; Pop-Location
}

Write-Host 'Waiting for PostgreSQL...'
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
  if ($UseWsl) { $state = wsl -- docker inspect -f '{{.State.Health.Status}}' forge0-db-1 }
  else { $state = docker inspect -f '{{.State.Health.Status}}' forge0-db-1 }
  if ($state -match 'healthy') { $ready = $true; break }
  Start-Sleep -Seconds 2
}
if (-not $ready) { throw 'PostgreSQL did not become healthy' }

# --- Backend ---------------------------------------------------------------------------
$Backend = Join-Path $Root 'backend'
$Python = Join-Path $Backend '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
  Write-Host 'Creating backend virtual environment'
  py -3 -m venv (Join-Path $Backend '.venv')
}
if (-not $SkipInstall) {
  & $Python -m pip install -q --upgrade pip
  & $Python -m pip install -q -e "$Backend[dev]"
}
Push-Location $Backend
& $Python -m alembic upgrade head
Pop-Location

$DevPids = Join-Path $DataDir 'dev-windows.pid'
$backendWin = Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$Backend'; & '$Python' -m uvicorn api.main:app --host 127.0.0.1 --port 8010" -WindowStyle Normal -PassThru
Set-Content $DevPids $backendWin.Id
Write-Host 'Backend starting on http://127.0.0.1:8010 (docs: /docs)'

# --- Frontend --------------------------------------------------------------------------
if (-not $SkipFrontend) {
  $Frontend = Join-Path $Root 'frontend'
  if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
    Push-Location $Frontend; npm ci --no-audit --no-fund; Pop-Location
  }
  $frontendWin = Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$Frontend'; npm run dev -- --host 127.0.0.1" -WindowStyle Normal -PassThru
  Add-Content $DevPids $frontendWin.Id
  Write-Host 'Frontend starting on http://127.0.0.1:5173'
}
