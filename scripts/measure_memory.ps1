<#
.SYNOPSIS
  Reports memory used by the FORGE-0 development stack (host processes, the WSL VM and containers).

.DESCRIPTION
  Read-only. Attributes host processes to FORGE-0 by command line (D:\Forge-0 paths, uvicorn
  api.main, vite, the WSL keep-alive) and reports the WSL VM's private memory, which is what WSL
  actually holds on the host regardless of how much is in use inside the VM.
#>
param([string]$Label = 'snapshot')

$ErrorActionPreference = 'SilentlyContinue'
$Root = (Split-Path -Parent $PSScriptRoot)
$os = Get-CimInstance Win32_OperatingSystem
$procs = Get-CimInstance Win32_Process
$forge = $procs | Where-Object {
  $_.CommandLine -and (
    $_.CommandLine -like "*$Root*" -or
    $_.CommandLine -match 'uvicorn api\.main|vite|esbuild' -or
    ($_.Name -eq 'wsl.exe' -and $_.CommandLine -match 'sleep infinity|cat > /dev/null')
  ) -and $_.Name -notmatch 'claude' -and $_.ProcessId -ne $PID -and $_.CommandLine -notmatch 'measure_memory\.ps1'
}
$rows = foreach ($p in $forge) {
  $gp = Get-Process -Id $p.ProcessId
  if (-not $gp) { continue }
  $kind = switch -Regex ($p.CommandLine) {
    '^"?[^"]*powershell\.exe' { 'console window'; break }
    'uvicorn' { 'backend (uvicorn)'; break }
    'vite' { 'frontend (vite)'; break }
    'esbuild' { 'frontend (esbuild)'; break }
    'sleep infinity|cat > /dev/null' { 'wsl keep-alive'; break }
    default { $p.Name }
  }
  [pscustomobject]@{ Kind = $kind; PID = $p.ProcessId; WorkingSetMB = [math]::Round($gp.WorkingSet64 / 1MB); PrivateMB = [math]::Round($gp.PrivateMemorySize64 / 1MB) }
}
$vm = Get-Process vmmemWSL
$wslPrivate = if ($vm) { [math]::Round($vm.PrivateMemorySize64 / 1MB) } else { 0 }
$wslWs = if ($vm) { [math]::Round($vm.WorkingSet64 / 1MB) } else { 0 }

"=== FORGE-0 memory: $Label ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))"
"Host RAM: {0:N2} GB total, {1:N2} GB available" -f ($os.TotalVisibleMemorySize / 1MB), ($os.FreePhysicalMemory / 1MB)
"WSL VM (vmmemWSL): private {0} MB, working set {1} MB" -f $wslPrivate, $wslWs
$rows | Sort-Object PrivateMB -Descending | Format-Table -AutoSize | Out-String -Width 120
"FORGE-0 host processes: {0} MB private, {1} MB working set" -f (($rows | Measure-Object PrivateMB -Sum).Sum), (($rows | Measure-Object WorkingSetMB -Sum).Sum)

$dockerCmd = if (Get-Command docker -ErrorAction SilentlyContinue) { @('docker') } else { @('wsl', '--', 'docker') }
if ($vm -or $dockerCmd[0] -eq 'docker') {
  "Containers:"
  & $dockerCmd[0] $dockerCmd[1..9] stats --no-stream --format '  {{.Name}}: {{.MemUsage}}' 2>$null
  if ($dockerCmd[0] -eq 'wsl') {
    "WSL guest memory (MB):"
    wsl -- free -m 2>$null | Select-Object -First 2 | ForEach-Object { "  $_" }
  }
}
