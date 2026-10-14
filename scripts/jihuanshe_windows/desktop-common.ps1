$desktopDll = Join-Path $PSScriptRoot '../../.venv/jhs-windows-poc/virtual-desktop/VirtualDesktopAccessor.dll'
$desktopDllHash = '8740C572A1C000E3B87FFEB1E4C397EAE9AF3BD4A2ABDC3BCFFACAB4493F8FF5'
if (-not (Test-Path -LiteralPath $desktopDll)) { throw 'Run configure-desktop.ps1 -Install first.' }
if ((Get-FileHash -LiteralPath $desktopDll -Algorithm SHA256).Hash -ne $desktopDllHash) { throw 'Virtual desktop component checksum mismatch.' }
if (-not ('KamiJhs.Desktop' -as [type])) { Add-Type -Path (Join-Path $PSScriptRoot 'desktop-window.cs') }
[KamiJhs.Desktop]::Load($desktopDll)