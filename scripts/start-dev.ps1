$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backend = Join-Path $repo 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$commit = (git -C $repo rev-parse --short HEAD).Trim()
$buildTime = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
$statePath = Join-Path $env:TEMP ("orion-dev-" + (Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($repo))) -Algorithm SHA256).Hash.Substring(0, 12) + '.json')

if (-not (Test-Path -LiteralPath $python)) { throw "Backend virtualenv missing: $python" }
foreach ($port in @(8001, 5173)) {
  $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    throw "Port $port is busy (PID $($listener.OwningProcess), $($owner.Name)): $($owner.CommandLine). Stop that process or ask its owner; ORION will not switch ports."
  }
}

Write-Host "ORION repository: $repo"
Write-Host "ORION commit: $commit"
$backendCommand = "`$env:ORION_COMMIT='$commit'; `$env:ORION_BUILD_TIME='$buildTime'; Set-Location '$backend'; & '$python' -m uvicorn app.main:app --host 127.0.0.1 --port 8001"
$frontendCommand = "`$env:VITE_COMMIT='$commit'; `$env:VITE_API_BASE='http://127.0.0.1:8001'; Set-Location '$repo'; npm run dev -- --port 5173 --strictPort"
$startedAt = [DateTime]::UtcNow
$backendShell = Start-Process powershell.exe -PassThru -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $backendCommand)
$frontendShell = Start-Process powershell.exe -PassThru -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $frontendCommand)
$started = [ordered]@{repo=$repo; commit=$commit; started_at_utc=$startedAt.ToString('o'); roots=@(
  @{pid=$backendShell.Id; started_at_utc=$backendShell.StartTime.ToUniversalTime().ToString('o')},
  @{pid=$frontendShell.Id; started_at_utc=$frontendShell.StartTime.ToUniversalTime().ToString('o')}
)}
$started | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8

$deadline = [DateTime]::UtcNow.AddSeconds(45)
$version = $null
while ([DateTime]::UtcNow -lt $deadline) {
  foreach ($root in $started.roots) {
    $process = Get-Process -Id $root.pid -ErrorAction SilentlyContinue
    if (-not $process) { throw "ORION launcher window PID $($root.pid) exited before both servers became ready. Check its visible error." }
  }
  try {
    $version = Invoke-RestMethod 'http://127.0.0.1:8001/api/version' -TimeoutSec 2
    break
  } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $version) { throw "Backend did not answer /api/version on port 8001 within 45 seconds. Inspect the visible backend window." }
if ($version.commit -ne $commit) { throw "Backend version mismatch on port 8001: expected $commit, got $($version.commit). Stop without using another port." }
$frontendReady = $false
try { $frontendReady = (Invoke-WebRequest 'http://127.0.0.1:5173' -TimeoutSec 3 -UseBasicParsing).StatusCode -eq 200 } catch { }
if (-not $frontendReady) { throw 'Frontend did not answer on port 5173. Inspect the visible frontend window.' }

$processes = @(Get-CimInstance Win32_Process)
$managed = @{}
foreach ($root in $started.roots) {
  $managed[[int]$root.pid] = [pscustomobject]@{pid=[int]$root.pid; name='powershell'; started_at_utc=$root.started_at_utc}
}
foreach ($port in @(8001, 5173)) {
  $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $listener) { throw "No process is listening on expected port $port." }
  $process = $processes | Where-Object ProcessId -eq $listener.OwningProcess | Select-Object -First 1
  if ($port -eq 8001 -and ($process.CommandLine -notlike "*$backend*" -or $process.CommandLine -notlike '*uvicorn app.main:app*')) { throw "Unexpected backend listener on 8001 (PID $($listener.OwningProcess)); refusing to record it." }
  if ($port -eq 5173 -and $process.CommandLine -notlike "*$repo*vite*") { throw "Unexpected frontend listener on 5173 (PID $($listener.OwningProcess)); refusing to record it." }
  $pidValue = [int]$listener.OwningProcess
  while ($pidValue -gt 0 -and -not $managed.ContainsKey($pidValue)) {
    $process = $processes | Where-Object ProcessId -eq $pidValue | Select-Object -First 1
    $runtime = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if (-not $process -or -not $runtime) { break }
    $created = $runtime.StartTime.ToUniversalTime()
    if ($pidValue -notin @($started.roots | ForEach-Object { [int]$_.pid }) -and $created -lt $startedAt.AddSeconds(-2)) { break }
    $managed[$pidValue] = [pscustomobject]@{pid=$pidValue; name=$runtime.ProcessName; started_at_utc=$created.ToString('o')}
    $pidValue = [int]$process.ParentProcessId
  }
}
$started.managed_processes = @($managed.Values)
$started | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding utf8
Write-Host "Backend:  http://127.0.0.1:8001 (commit $($version.commit))"
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "Process state: $statePath (stop with scripts/stop-dev.ps1)"
