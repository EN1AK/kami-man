# deploy/git-push.ps1
#
# Push to remote from inside the Windows DSH sandbox.
#
# Background: Git for Windows' MSYS2 helpers (sh.exe / ssh.exe) cannot create a
# signal named pipe in the sandbox, so a plain `git push` fails with
# `couldn't create signal pipe, Win32 error 5`. Use the Windows-native OpenSSH
# client via the GIT_SSH environment variable instead (exec'd directly, no shell).
#
# Usage (from the repository root):
#   pwsh -File deploy/git-push.ps1                 # git push origin main
#   pwsh -File deploy/git-push.ps1 origin dev      # custom remote/branch
#   pwsh -File deploy/git-push.ps1 --set-upstream origin dev

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GitArgs
)

$env:GIT_SSH = 'C:\Windows\System32\OpenSSH\ssh.exe'

if (-not $GitArgs -or $GitArgs.Count -eq 0) {
    $GitArgs = @('origin', 'main')
}

& git push @GitArgs
exit $LASTEXITCODE
