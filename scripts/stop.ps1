<#
.SYNOPSIS
  Stops everything the FORGE-0 full development mode (scripts/dev.ps1) started.

.DESCRIPTION
  Ends the backend and frontend windows opened by dev.ps1 (whole process trees), any stray
  uvicorn/Vite/esbuild process started from this checkout (Vite survives its console window),
  the WSL keep-alive and the PostgreSQL container. Nothing outside this checkout is touched.
  For lite mode use `scripts/lite.ps1 stop`.
#>
param([switch]$KeepDatabase)
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $Root 'data'

function Stop-Tree([int]$ProcessId, [string]$What) {
  if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
    taskkill /T /F /PID $ProcessId 2>$null | Out-Null
    Write-Host "Stopped $What (pid $ProcessId)"
  }
}

$windows = Join-Path $DataDir 'dev-windows.pid'
if (Test-Path $windows) {
  foreach ($line in Get-Content $windows) { if ($line -match '^\d+$') { Stop-Tree ([int]$line) 'dev window' } }
  Remove-Item $windows
}

# Safety net: processes from this checkout that outlived their window.
$frontend = Join-Path $Root 'frontend'
$backend = Join-Path $Root 'backend'
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and (
    ($_.Name -eq 'node.exe' -and $_.CommandLine -like "*$frontend*vite*") -or
    ($_.Name -eq 'esbuild.exe' -and $_.ExecutablePath -like "$frontend*") -or
    ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*uvicorn*api.main:app*' -and
      ($_.ExecutablePath -like "$backend*" -or $_.CommandLine -like "*$backend*"))
  )
} | ForEach-Object { Stop-Tree $_.ProcessId $_.Name }

$pidFile = Join-Path $DataDir '.wsl-keepalive.pid'
if (Test-Path $pidFile) {
  Stop-Tree ([int](Get-Content $pidFile)) 'WSL keep-alive'
  Remove-Item $pidFile
}

if (-not $KeepDatabase) {
  if (Get-Command docker -ErrorAction SilentlyContinue) {
    Push-Location $Root; docker compose stop db; Pop-Location
  } else {
    $wslRoot = (wsl wslpath -a ($Root -replace '\\', '/')).Trim()
    wsl -- bash -lc "cd '$wslRoot' && docker compose stop db"
  }
}
