$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$statePath = Join-Path $env:TEMP ("orion-dev-" + (Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($repo))) -Algorithm SHA256).Hash.Substring(0, 12) + '.json')
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'No ORION dev process state found; no processes stopped.'; exit 0 }
$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
if ([IO.Path]::GetFullPath($state.repo) -ne $repo) { throw 'ORION process state points to a different repository; refusing to stop processes.' }
$all = @(Get-CimInstance Win32_Process)
$selected = @{}
$cutoff = [DateTime]::Parse($state.started_at_utc).ToUniversalTime()
foreach ($root in @($state.roots)) {
  $rootProcess = $all | Where-Object ProcessId -eq ([int]$root.pid) | Select-Object -First 1
  if (-not $rootProcess -or $rootProcess.Name -notmatch '^powershell(\.exe)?$' -or $rootProcess.CommandLine -notlike "*$repo*") { continue }
  $rootCreated = [Management.ManagementDateTimeConverter]::ToDateTime($rootProcess.CreationDate).ToUniversalTime()
  $rootCutoff = [DateTime]::Parse($root.started_at_utc).ToUniversalTime()
  if ($rootCreated -lt $rootCutoff.AddSeconds(-2)) { continue }
  $selected[[int]$root.pid] = $rootProcess
  $changed = $true
  while ($changed) {
    $changed = $false
    foreach ($process in $all) {
      $pidValue = [int]$process.ProcessId
      if ($selected.ContainsKey($pidValue) -or -not $selected.ContainsKey([int]$process.ParentProcessId)) { continue }
      $created = [Management.ManagementDateTimeConverter]::ToDateTime($process.CreationDate).ToUniversalTime()
      if ($created -lt $cutoff.AddSeconds(-2)) { continue }
      $selected[$pidValue] = $process
      $changed = $true
    }
  }
}
foreach ($process in @($selected.Values | Sort-Object CreationDate -Descending)) {
  Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction SilentlyContinue
  Write-Host "Stopped ORION process $($process.ProcessId) ($($process.Name))."
}
Remove-Item -LiteralPath $statePath -Force
if (-not $selected.Count) { Write-Host 'No matching processes from this ORION launch were still running.' }
