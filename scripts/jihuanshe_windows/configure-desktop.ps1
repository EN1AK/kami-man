param([switch]$Install, [switch]$Bind, [switch]$Disable)
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '../../.venv/jhs-windows-poc'
$configPath = Join-Path $runtime 'config.json'
if ($Install) {
    $dir = Join-Path $runtime 'virtual-desktop'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $uri = 'https://github.com/Ciantic/VirtualDesktopAccessor/releases/download/2024-12-16-windows11/VirtualDesktopAccessor.dll'
    Invoke-WebRequest $uri -OutFile (Join-Path $dir 'VirtualDesktopAccessor.dll')
    Invoke-WebRequest 'https://raw.githubusercontent.com/Ciantic/VirtualDesktopAccessor/2024-12-16-windows11/LICENSE.txt' -OutFile (Join-Path $dir 'LICENSE.txt')
}
if ($Disable) {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json -AsHashtable
    $config.autoOpen = $false
    $config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8
    Write-Output 'Automatic mini-program reopening disabled. Restart the bridge to apply.'
    exit
}
. (Join-Path $PSScriptRoot 'desktop-common.ps1')
$windows = @([KamiJhs.Desktop]::Inspect())
if ($Bind) {
    if ($windows.Count -eq 0) { throw 'Open Jihuanshe on its dedicated virtual desktop before binding.' }
    if (@($windows | Where-Object Pinned).Count) { throw 'Unpin the mini-program from all desktops before binding.' }
    $ids = @($windows.DesktopId | Select-Object -Unique)
    if ($ids.Count -ne 1 -or [guid]$ids[0] -eq [guid]::Empty) { throw 'Cannot identify a unique mini-program desktop.' }
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json -AsHashtable
    $config.desktopId = $ids[0]
    $config.autoOpen = $true
    $config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8
    Write-Output 'Mini-program desktop bound. Restart the bridge to enable automatic reopening.'
}
[pscustomobject]@{desktopCount=[KamiJhs.Desktop]::Count();currentDesktop=([KamiJhs.Desktop]::CurrentNumber()+1);miniappWindows=$windows} | ConvertTo-Json -Depth 4