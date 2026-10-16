$ErrorActionPreference = 'Stop'
$archiveDir = 'D:\file\mycard_archive'
$scriptPath = Join-Path $archiveDir 'offload.sh'
$bash = 'D:\Program Files\Git\usr\bin\bash.exe'
$keyPath = 'C:\ProgramData\KamiMan\MyCardOffload\id_ed25519'
$knownHosts = 'C:\ProgramData\KamiMan\MyCardOffload\known_hosts'
foreach ($required in @($scriptPath, $bash, $keyPath, $knownHosts)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing required file: $required" }
}
$action = New-ScheduledTaskAction -Execute $bash -Argument '--noprofile --norc /d/file/mycard_archive/offload.sh' -WorkingDirectory $archiveDir
$startup = New-ScheduledTaskTrigger -AtStartup
$periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 12) -StartWhenAvailable
$settings.Hidden = $true
Register-ScheduledTask -TaskName 'KamiMan-MyCard-Offload' -Action $action -Trigger @($startup, $periodic) -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'KamiMan-MyCard-Offload'
Write-Output 'MyCard offload task installed: startup and every 5 minutes.'
