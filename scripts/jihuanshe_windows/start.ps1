param([switch]$Stop, [switch]$Status, [switch]$AutoStart, [switch]$RemoveAutoStart)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtimeDir = Join-Path $repoRoot '.venv/jhs-windows-poc'
$configPath = Join-Path $runtimeDir 'config.json'
$taskName = 'KamiMan-Jihuanshe-Bridge'
$pwshExe = (Get-Command pwsh.exe).Source
$supervisor = Join-Path $PSScriptRoot 'supervise.ps1'
if ($RemoveAutoStart) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue; Write-Output 'Logon startup removed.'; exit }
if ($AutoStart) {
    $userId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $pwshExe -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$supervisor+'"') -WorkingDirectory $repoRoot
    $trigger = @(
        (New-ScheduledTaskTrigger -AtLogOn -User $userId)
        (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1))
    )
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Output 'Logon startup and a one-minute supervisor watchdog registered.'
    exit
}
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Run setup.ps1 first.' }
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$headers = @{Authorization='Bearer '+$config.token}
function Get-BridgeSupervisor {
    $statePath = Join-Path $runtimeDir 'service-state.json'
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($state.supervisor_pid)"
        if ($parent -and $parent.CommandLine -and $parent.CommandLine.Contains($supervisor)) { return $parent }
    } catch {}
    return $null
}
if ($Status) {
    $health = Invoke-RestMethod http://127.0.0.1:8791/health -Headers $headers
    $health | Add-Member -NotePropertyName supervisor_alive -NotePropertyValue ([bool](Get-BridgeSupervisor))
    $health | Add-Member -NotePropertyName miniapp_auto_open -NotePropertyValue ($config.autoOpen -eq $true)
    $health | Add-Member -NotePropertyName miniapp_desktop_id -NotePropertyValue $config.desktopId
    $health | ConvertTo-Json
    exit
}
if ($Stop) {
    Set-Content -LiteralPath (Join-Path $runtimeDir 'stop.request') -Value 'stop' -Encoding ascii
    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 500
        $listener = Get-NetTCPConnection -State Listen -LocalPort 8791 -ErrorAction SilentlyContinue
        $supervisorAlive = $false
        $statePath = Join-Path $runtimeDir 'service-state.json'
        if (Test-Path -LiteralPath $statePath) {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($state.supervisor_pid)"
            $supervisorAlive = $parent -and $parent.CommandLine -and $parent.CommandLine.Contains($supervisor)
        }
    } while (($listener -or $supervisorAlive) -and (Get-Date) -lt $deadline)
    if ($listener -or $supervisorAlive) { throw 'Bridge did not stop in time. Inspect service.out.log before stopping unrelated processes.' }
    Write-Output 'Bridge and owned helper processes stopped.'
    exit
}
Remove-Item -LiteralPath (Join-Path $runtimeDir 'stop.request') -Force -ErrorAction SilentlyContinue
$bridgeRunning = $false
try { $health = Invoke-RestMethod http://127.0.0.1:8791/health -Headers $headers -TimeoutSec 2; $bridgeRunning = $true } catch {}
if ($bridgeRunning -and (Get-BridgeSupervisor)) { Write-Output 'Bridge and supervisor are already running.'; exit }
if ($bridgeRunning) { Write-Output 'Restoring supervision of the existing bridge.' }
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) { Start-ScheduledTask -TaskName $taskName }
else { Start-Process -FilePath $pwshExe -ArgumentList @('-NoProfile','-NonInteractive','-File',('"'+$supervisor+'"')) -WorkingDirectory $repoRoot -WindowStyle Hidden | Out-Null }
Write-Output 'Bridge supervisor started. Session recovery runs in the background.'