<#
.SYNOPSIS
  FORGE-0 lightweight development mode for memory-constrained machines.

.DESCRIPTION
  start   PostgreSQL (tuned, capped at 256 MB) + ONE hidden backend process that also serves the
          prebuilt dashboard. No Vite, no Node at runtime, no extra console windows.
          Dashboard and API: http://127.0.0.1:8010
  stop    Stops the backend (and its WSL keep-alive) and the PostgreSQL container.
          -ReclaimWslCache additionally drops the WSL page cache so Windows gets the memory back.
  status  Shows process state, health and a memory breakdown.

  Lite mode runs one investigation at a time (WORKER_THREADS=1), one sandbox container at a time
  (SANDBOX_MAX_CONCURRENT=1, 384 MB each) and a 3-connection database pool. The full mode
  (scripts/dev.ps1, Vite with hot reload) is unchanged.

.EXAMPLE
  .\scripts\lite.ps1 start
  .\scripts\lite.ps1 status
  .\scripts\lite.ps1 stop -ReclaimWslCache
#>
param(
  [ValidateSet('start', 'stop', 'status')]
  [string]$Command = 'start',
  [switch]$Rebuild,
  [switch]$ReclaimWslCache
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$DataDir = Join-Path $Root 'data'
$LogDir = Join-Path $DataDir 'logs'
$PidFile = Join-Path $DataDir 'lite-backend.pid'
$Python = Join-Path $Backend '.venv\Scripts\python.exe'
$Port = 8010
$UseWsl = -not (Get-Command docker -ErrorAction SilentlyContinue)

function Invoke-Docker([string[]]$DockerArgs) {
  if ($UseWsl) { & wsl -- docker @DockerArgs } else { & docker @DockerArgs }
}

function Invoke-Compose([string[]]$ComposeArgs) {
  $files = @('-f', 'docker-compose.yml', '-f', 'docker-compose.lite.yml')
  if ($UseWsl) {
    $wslRoot = (wsl wslpath -a ($Root -replace '\\', '/')).Trim()
    $joined = ($files + $ComposeArgs) -join ' '
    wsl -- bash -lc "cd '$wslRoot' && docker compose $joined"
  } else {
    Push-Location $Root
    try { docker compose @files @ComposeArgs } finally { Pop-Location }
  }
}

function Get-LiteBackend {
  if (Test-Path $PidFile) {
    $p = Get-Process -Id ([int](Get-Content $PidFile)) -ErrorAction SilentlyContinue
    if ($p) { return $p }
  }
  # Fall back to a uvicorn started from this checkout on the lite port (e.g. after a lost pid file).
  $match = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*uvicorn*api.main:app*--port $Port*" -and $_.ExecutablePath -like "$Backend*" } |
    Select-Object -First 1
  if ($match) { return Get-Process -Id $match.ProcessId -ErrorAction SilentlyContinue }
  return $null
}

function Test-Health {
  try { return (Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/system/health" -TimeoutSec 3) } catch { return $null }
}

function Stop-Lite {
  $proc = Get-LiteBackend
  if ($proc) {
    # /T also ends the backend's WSL keep-alive (which exits on its own when the backend dies).
    taskkill /T /F /PID $proc.Id | Out-Null
    Write-Host "Stopped backend (pid $($proc.Id))"
  } else {
    Write-Host 'Backend not running'
  }
  Remove-Item $PidFile -ErrorAction SilentlyContinue
  Invoke-Compose @('stop', 'db') | Out-Null
  Write-Host 'Stopped PostgreSQL container'
  if ($ReclaimWslCache -and $UseWsl) {
    $before = [math]::Round((Get-Process vmmemWSL -ErrorAction SilentlyContinue).PrivateMemorySize64 / 1MB)
    # Drops only clean page cache inside the VM; running containers and data are unaffected.
    wsl -- sudo -n sh -c 'sync; echo 1 > /proc/sys/vm/drop_caches' 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Could not drop the WSL page cache (passwordless sudo required)' }
    Start-Sleep -Seconds 5
    $after = [math]::Round((Get-Process vmmemWSL -ErrorAction SilentlyContinue).PrivateMemorySize64 / 1MB)
    Write-Host "WSL VM private memory: $before MB -> $after MB (Windows reclaims freed pages gradually)"
  }
}

switch ($Command) {
  'status' {
    $proc = Get-LiteBackend
    if ($proc) { Write-Host "Backend: running (pid $($proc.Id))" } else { Write-Host 'Backend: not running' }
    $health = Test-Health
    if ($health) {
      Write-Host ("Health: {0} | database {1} | sandbox {2} | provider {3}{4}" -f $health.status, $health.database.ok, $health.sandbox.ok, $health.provider.active, $(if ($health.provider.simulated) { ' (simulated)' } else { '' }))
    }
    & (Join-Path $PSScriptRoot 'measure_memory.ps1') -Label 'lite status'
  }

  'stop' { Stop-Lite }

  'start' {
    New-Item -ItemType Directory -Force $LogDir | Out-Null
    if (-not (Test-Path (Join-Path $Root '.env'))) {
      Copy-Item (Join-Path $Root '.env.example') (Join-Path $Root '.env')
      Write-Host 'Created .env from .env.example'
    }
    if (Get-LiteBackend) {
      Write-Host "Already running: http://127.0.0.1:$Port  (use 'stop' first to restart)"
      return
    }
    $busy = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($busy) { throw "Port $Port is in use by pid $($busy[0].OwningProcess); stop it first (e.g. the full dev backend)." }

    # 1. Backend environment (one-time).
    if (-not (Test-Path $Python)) {
      Write-Host 'Creating backend virtual environment (one-time)'
      py -3 -m venv (Join-Path $Backend '.venv')
      & $Python -m pip install -q --upgrade pip
      & $Python -m pip install -q -e "$Backend"
    }

    # 2. Dashboard: build once; rebuild only when sources changed (or -Rebuild).
    $index = Join-Path $Frontend 'dist\index.html'
    $stale = -not (Test-Path $index)
    if (-not $stale) {
      $built = (Get-Item $index).LastWriteTime
      $newest = Get-ChildItem (Join-Path $Frontend 'src'), (Join-Path $Frontend 'index.html') -Recurse -File |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
      $stale = $newest.LastWriteTime -gt $built
    }
    if ($stale -or $Rebuild) {
      Write-Host 'Building dashboard (one-time Node process)...'
      Push-Location $Frontend
      try {
        if (-not (Test-Path 'node_modules')) { npm ci --no-audit --no-fund | Out-Null }
        npm run build | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Dashboard build failed' }
      } finally { Pop-Location }
    }

    # 3. PostgreSQL (tuned + capped), started last so no slow step sits between it and the backend:
    #    an idle WSL distro is stopped after a few seconds, taking dockerd with it. The backend's
    #    keep-alive takes over immediately, and it also waits for the database on startup.
    Invoke-Compose @('up', '-d', 'db') | Out-Null
    Write-Host -NoNewline 'Waiting for PostgreSQL'
    $ready = $false
    for ($i = 0; $i -lt 45; $i++) {
      $state = Invoke-Docker @('inspect', '-f', '{{.State.Health.Status}}', 'forge0-db-1') 2>$null
      if ("$state" -match 'healthy') { $ready = $true; break }
      Write-Host -NoNewline '.'
      Start-Sleep -Seconds 2
    }
    Write-Host ''
    if (-not $ready) { throw 'PostgreSQL did not become healthy' }

    # 4. Backend: one hidden, fully detached process (created through WMI, so it inherits no
    #    console or pipe handles from this script and survives the terminal being closed).
    #    The settings below override .env for this process only.
    $settings = [ordered]@{
      SERVE_FRONTEND_DIR    = 'frontend/dist'
      WORKER_THREADS        = '1'
      SANDBOX_MAX_CONCURRENT = '1'
      SANDBOX_MEMORY        = '384m'
      DB_POOL_SIZE          = '3'
      LOG_LEVEL             = 'WARNING'
      SANDBOX_WSL_KEEPALIVE = 'true'
    }
    $sets = ($settings.GetEnumerator() | ForEach-Object { "set $($_.Key)=$($_.Value)&&" }) -join ' '
    $out = Join-Path $LogDir 'backend.out.log'
    $err = Join-Path $LogDir 'backend.err.log'
    $cmdLine = "cmd.exe /d /c `"cd /d `"$Backend`" && $sets `"$Python`" -m uvicorn api.main:app --host 127.0.0.1 --port $Port --no-access-log > `"$out`" 2> `"$err`"`""
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmdLine; CurrentDirectory = $Backend; ProcessStartupInformation = $startup }
    if ($created.ReturnValue -ne 0) { throw "Could not start the backend (Win32_Process.Create returned $($created.ReturnValue))" }
    $backendPid = [int]$created.ProcessId
    Set-Content $PidFile $backendPid

    Write-Host -NoNewline 'Starting backend'
    $health = $null
    for ($i = 0; $i -lt 120; $i++) {
      if (-not (Get-Process -Id $backendPid -ErrorAction SilentlyContinue)) { throw "Backend exited; see $LogDir\backend.err.log" }
      $health = Test-Health
      if ($health) { break }
      Write-Host -NoNewline '.'
      Start-Sleep -Seconds 1
    }
    Write-Host ''
    if (-not $health) { throw "Backend did not become healthy; see $LogDir\backend.err.log" }
    Write-Host "FORGE-0 lite is running: http://127.0.0.1:$Port  (pid $backendPid)"
    Write-Host ("database {0} | sandbox {1} | provider {2}{3}" -f $health.database.ok, $health.sandbox.ok, $health.provider.active, $(if ($health.provider.simulated) { ' (simulated)' } else { '' }))
    Write-Host 'Stop with: .\scripts\lite.ps1 stop'
  }
}
