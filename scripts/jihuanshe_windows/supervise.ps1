$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtimeDir = Join-Path $repoRoot '.venv/jhs-windows-poc'
$configPath = Join-Path $runtimeDir 'config.json'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Run setup.ps1 first.' }
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$entry = Join-Path $PSScriptRoot 'bridge.cjs'
$statePath = Join-Path $runtimeDir 'service-state.json'
$stopPath = Join-Path $runtimeDir 'stop.request'
if (Test-Path -LiteralPath $stopPath) { exit }
function Get-ExistingBridge {
    if (-not (Test-Path -LiteralPath $statePath)) { return $null }
    try {
        $previous = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $($previous.pid)"
        if (-not $info -or $info.Name -ne 'node.exe' -or -not $info.CommandLine) { return $null }
        if (-not $info.CommandLine.Contains($entry) -or -not $info.CommandLine.Contains($configPath)) { return $null }
        if ($info.CreationDate.ToUniversalTime().ToFileTimeUtc().ToString() -ne [string]$previous.created) { return $null }
        return Get-Process -Id $info.ProcessId -ErrorAction Stop
    } catch { return $null }
}
function Write-SupervisorEvent([string]$EventName) {
    Add-Content -LiteralPath (Join-Path $runtimeDir 'supervisor.log') -Value ([DateTime]::UtcNow.ToString('o')+' '+$EventName) -Encoding utf8
}
$mutex = [Threading.Mutex]::new($false, 'Local\KamiManJihuansheBridge')
try { $ownsMutex = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
if (-not $ownsMutex) { $mutex.Dispose(); exit }
function Clear-OwnedHelpers([int]$BrokerId, [DateTime]$BrokerStarted) {
    $tsNode = Join-Path $config.debuggerDir 'node_modules/ts-node/dist/bin.js'
    $debugEntry = Join-Path $config.debuggerDir 'src/index.ts'
    $helpers = Get-CimInstance Win32_Process -Filter "ParentProcessId = $BrokerId"
    foreach ($helper in $helpers) {
        if ($helper.CreationDate.ToUniversalTime() -lt $BrokerStarted -or -not $helper.CommandLine) { continue }
        $isDebugger = $helper.Name -eq 'node.exe' -and $helper.CommandLine.Contains($tsNode) -and $helper.CommandLine.Contains($debugEntry)
        $isTunnel = $helper.Name -eq 'ssh.exe' -and $helper.CommandLine.Contains('127.0.0.1:8791:127.0.0.1:8791') -and $helper.CommandLine.Contains($config.sshHost)
        if ($isDebugger -or $isTunnel) { Stop-Process -Id $helper.ProcessId -ErrorAction SilentlyContinue }
    }
}
$restartDelay = 5
try {
    while ($true) {
        if (Test-Path -LiteralPath $stopPath) { break }
        $child = Get-ExistingBridge
        if ($child) { Write-SupervisorEvent 'bridge_adopted' }
        else {
            $nodeExe = (Get-Command node.exe).Source
            $child = Start-Process -FilePath $nodeExe -ArgumentList @(('"'+$entry+'"'),('"'+$configPath+'"')) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'service.out.log') -RedirectStandardError (Join-Path $runtimeDir 'service.err.log') -PassThru
            Write-SupervisorEvent 'bridge_started'
        }
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $($child.Id)"
        if (-not $info) { Write-SupervisorEvent 'bridge_exited_early'; Start-Sleep -Seconds 5; continue }
        $started = $info.CreationDate.ToUniversalTime()
        [pscustomobject]@{pid=$child.Id;created=$started.ToFileTimeUtc().ToString();supervisor_pid=$PID} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
        $child.WaitForExit()
        Write-SupervisorEvent 'bridge_exited'
        Clear-OwnedHelpers $child.Id $started
        if (Test-Path -LiteralPath $stopPath) { break }
        if (([DateTime]::UtcNow - $started).TotalSeconds -gt 300) { $restartDelay = 5 }
        $nextStart = [DateTime]::UtcNow.AddSeconds($restartDelay)
        while ([DateTime]::UtcNow -lt $nextStart) {
            if (Test-Path -LiteralPath $stopPath) { break }
            Start-Sleep -Milliseconds 500
        }
        $restartDelay = [Math]::Min($restartDelay*2,60)
    }
} finally { $mutex.ReleaseMutex(); $mutex.Dispose() }