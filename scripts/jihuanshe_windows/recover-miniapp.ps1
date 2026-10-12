param([Parameter(Mandatory)][string]$ShortcutPath, [switch]$LaunchOnly)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $ShortcutPath)) { exit 1 }
Add-Type -TypeDefinition @"
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
public static class JhsMiniappWindow {
    public delegate bool EnumCallback(IntPtr window, IntPtr parameter);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumCallback callback, IntPtr parameter);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr window, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
    public static void Close(string prefix) {
        EnumWindows((window, parameter) => {
            var title = new StringBuilder(512);
            GetWindowText(window, title, title.Capacity);
            if (!title.ToString().StartsWith(prefix, StringComparison.Ordinal)) return true;
            uint processId; GetWindowThreadProcessId(window, out processId);
            try {
                var process = Process.GetProcessById((int)processId);
                if (process.ProcessName == "WeChatAppEx" || process.ProcessName == "Weixin")
                    PostMessage(window, 0x0010, IntPtr.Zero, IntPtr.Zero);
            } catch {}
            return true;
        }, IntPtr.Zero);
    }
}
"@
$miniappPrefix = [string]([char]0x96c6) + [char]0x6362 + [char]0x793e
if (-not $LaunchOnly) { [JhsMiniappWindow]::Close($miniappPrefix); Start-Sleep -Milliseconds 800 }
Start-Process -FilePath $ShortcutPath