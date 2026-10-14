param([Parameter(Mandatory)][string]$ShortcutPath, [Parameter(Mandatory)][guid]$TargetDesktopId, [switch]$LaunchOnly)
$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'desktop-common.ps1')
    $result = [KamiJhs.Desktop]::Recover($TargetDesktopId, $ShortcutPath, $LaunchOnly.IsPresent)
    [pscustomobject]@{placed=$result.Placed;desktop_unchanged=$result.DesktopUnchanged;foreground_unchanged=$result.ForegroundUnchanged;focus_events=$result.FocusEvents;moves=$result.Moves} | ConvertTo-Json -Compress
} catch {
    $reason = $_.Exception.GetBaseException().Message
    if ($reason -eq 'desktop_missing') { Write-Output '{"error":"desktop_missing"}'; exit 20 }
    if ($reason -eq 'wechat_unavailable') { Write-Output '{"error":"wechat_unavailable"}'; exit 22 }
    Write-Output '{"error":"desktop_recovery_failed"}'
    exit 21
}