$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtimeDir = Join-Path $repoRoot '.venv/jhs-windows-poc'
$configPath = Join-Path $runtimeDir 'config.json'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Run setup.ps1 first.' }
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
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
$stopPath = Join-Path $runtimeDir 'stop.request'
$supervisorStarted = [DateTime]::UtcNow
$restartDelay = 5
try {
    while ($true) {
        if ((Test-Path -LiteralPath $stopPath) -and (Get-Item -LiteralPath $stopPath).LastWriteTimeUtc -ge $supervisorStarted) { break }
        $nodeExe = (Get-Command node.exe).Source
        $entry = Join-Path $PSScriptRoot 'bridge.cjs'
        $started = [DateTime]::UtcNow
        $child = Start-Process -FilePath $nodeExe -ArgumentList @(('"'+$entry+'"'),('"'+$configPath+'"')) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'service.out.log') -RedirectStandardError (Join-Path $runtimeDir 'service.err.log') -PassThru
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $($child.Id)"
        [pscustomobject]@{pid=$child.Id;created=$info.CreationDate.ToUniversalTime().ToFileTimeUtc().ToString();supervisor_pid=$PID} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimeDir 'service-state.json') -Encoding utf8
        $child.WaitForExit()
        Clear-OwnedHelpers $child.Id $started
        if ((Test-Path -LiteralPath $stopPath) -and (Get-Item -LiteralPath $stopPath).LastWriteTimeUtc -ge $supervisorStarted) { break }
        if (([DateTime]::UtcNow - $started).TotalSeconds -gt 300) { $restartDelay = 5 }
        $nextStart = [DateTime]::UtcNow.AddSeconds($restartDelay)
        while ([DateTime]::UtcNow -lt $nextStart) {
            if ((Test-Path -LiteralPath $stopPath) -and (Get-Item -LiteralPath $stopPath).LastWriteTimeUtc -ge $supervisorStarted) { break }
            Start-Sleep -Milliseconds 500
        }
        $restartDelay = [Math]::Min($restartDelay*2,60)
    }
} finally { $mutex.ReleaseMutex(); $mutex.Dispose() }