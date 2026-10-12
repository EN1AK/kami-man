param([string]$DebuggerDir, [string]$ShortcutPath, [string]$SshHost = 'ubuntu@150.109.237.67', [string]$AppId = 'wx64479c83c7630409')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtimeDir = Join-Path $repoRoot '.venv/jhs-windows-poc'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
if (-not $DebuggerDir) { $DebuggerDir = Join-Path $runtimeDir 'WMPFDebugger-main' }
if (-not (Test-Path -LiteralPath (Join-Path $DebuggerDir 'package.json'))) {
    git clone --depth 1 https://github.com/evi0s/WMPFDebugger.git $DebuggerDir
    if ($LASTEXITCODE -ne 0) { throw 'Debugger download failed.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $DebuggerDir 'node_modules/frida/build/frida_binding.node'))) {
    Push-Location $DebuggerDir
    try { npm.cmd exec --yes --package=yarn@1.22.22 -- yarn install --frozen-lockfile --non-interactive; if ($LASTEXITCODE -ne 0) { throw 'Locked debugger dependencies could not be installed.' } }
    finally { Pop-Location }
}
$indexPath = Join-Path $DebuggerDir 'src/index.ts'
$index = [IO.File]::ReadAllText($indexPath).Replace('new WebSocketServer({ port: options.debugPort })','new WebSocketServer({ host: "127.0.0.1", port: options.debugPort })').Replace('new WebSocketServer({ port: options.cdpPort })','new WebSocketServer({ host: "127.0.0.1", port: options.cdpPort })')
$sessionLine = '    const fridaSession = await fridaServer(options, logger);'
$detachLine = '    fridaSession.detached.connect(() => process.exit(1));'
if (-not $index.Contains($detachLine)) {
    if (-not $index.Contains($sessionLine)) { throw 'Upstream session lifecycle changed; review before using this setup.' }
    $index = $index.Replace($sessionLine, $sessionLine + [Environment]::NewLine + $detachLine)
}
if (-not $index.Contains('host: "127.0.0.1", port: options.debugPort') -or -not $index.Contains('host: "127.0.0.1", port: options.cdpPort')) { throw 'Debugger loopback binding could not be applied.' }
[IO.File]::WriteAllText($indexPath,$index,[Text.UTF8Encoding]::new($false))
$hookPath = Join-Path $DebuggerDir 'frida/hook.js'
$hook = [IO.File]::ReadAllText($hookPath).Replace('ws://localhost:9421','ws://127.0.0.1:9421')
$hook = $hook.Replace('1005, 1007, 1008, 1011, 1012, 1027','1005, 1007, 1008, 1011, 1012, 1023, 1027')
if (-not $hook.Contains('1012, 1023, 1027')) { throw 'Upstream launch-scene code changed; review before using this setup.' }
[IO.File]::WriteAllText($hookPath,$hook,[Text.UTF8Encoding]::new($false))
if (-not $ShortcutPath) {
    $prefix = [string]([char]0x96c6) + [char]0x6362 + [char]0x793e
    $ShortcutPath = (Get-ChildItem -LiteralPath ([Environment]::GetFolderPath('Desktop')) -Filter '*.lnk' | Where-Object BaseName -Like ($prefix+'*') | Select-Object -First 1).FullName
}
if (-not $ShortcutPath -or -not (Test-Path -LiteralPath $ShortcutPath)) { throw 'Create a Jihuanshe desktop shortcut from the mini-program menu first.' }
$configPath = Join-Path $runtimeDir 'config.json'
if (Test-Path -LiteralPath $configPath) { $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json -AsHashtable }
else { $randomBytes = [byte[]]::new(32); [Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes); $config = @{token=[Convert]::ToHexString($randomBytes).ToLowerInvariant()} }
$config.debuggerDir = (Resolve-Path -LiteralPath $DebuggerDir).Path
$config.shortcut = (Resolve-Path -LiteralPath $ShortcutPath).Path
$config.sshHost = $SshHost
$config.appId = $AppId
$config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8
Write-Output 'Debugger prepared. Private config saved; the existing bridge token was preserved.'