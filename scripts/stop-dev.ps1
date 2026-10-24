$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$statePath = Join-Path $env:TEMP ("orion-dev-" + (Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($repo))) -Algorithm SHA256).Hash.Substring(0, 12) + '.json')
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'No ORION dev process state found; no processes stopped.'; exit 0 }
$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
if ([IO.Path]::GetFullPath($state.repo) -ne $repo) { throw 'ORION process state points to a different repository; refusing to stop processes.' }
$entries = @($state.managed_processes)
if (-not $entries.Count) { $entries = @($state.roots) | ForEach-Object { [pscustomobject]@{pid=$_.pid;name='powershell';started_at_utc=$_.started_at_utc} } }
$stopped = 0
foreach ($entry in @($entries | Sort-Object started_at_utc -Descending)) {
  $process = Get-Process -Id ([int]$entry.pid) -ErrorAction SilentlyContinue
  if (-not $process -or $process.ProcessName -ne $entry.name) { continue }
  try { $actualStart = $process.StartTime.ToUniversalTime() } catch { continue }
  $recordedStart = [DateTime]::Parse($entry.started_at_utc).ToUniversalTime()
  if ([Math]::Abs(($actualStart - $recordedStart).TotalSeconds) -gt 2) { continue }
  Stop-Process -Id ([int]$entry.pid) -Force -ErrorAction SilentlyContinue
  Write-Host "Stopped ORION process $($entry.pid) ($($entry.name))."
  $stopped++
}
Remove-Item -LiteralPath $statePath -Force
if (-not $stopped) { Write-Host 'No recorded ORION launcher processes were still running.' }
