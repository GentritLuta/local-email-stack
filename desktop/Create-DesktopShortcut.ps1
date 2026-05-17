# Create-DesktopShortcut.ps1
# Places a "LocalEmailStack" shortcut on the current user's desktop pointing at
# Launch-LocalEmailStack.ps1, with the orbit-logo icon embedded.
#
# Idempotent - re-running just refreshes the shortcut.

[CmdletBinding()]
param(
  [string]$Name = "LocalEmailStack"
)

$ErrorActionPreference = "Stop"

$Root        = Split-Path -Parent $PSCommandPath
$Launcher    = Join-Path $Root "Launch-LocalEmailStack.ps1"
$Icon        = Join-Path $Root "src-tauri\icons\icon.ico"
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$LnkPath     = Join-Path $DesktopPath "$Name.lnk"

if (-not (Test-Path $Launcher)) { throw "Launcher not found: $Launcher" }
if (-not (Test-Path $Icon))     { throw "Icon not found: $Icon - run Generate-Icon.ps1 first." }

# Build the powershell.exe invocation that runs the launcher silently.
$pwsh = (Get-Command powershell.exe).Source
$args = "-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Launcher`""

$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($LnkPath)
$lnk.TargetPath       = $pwsh
$lnk.Arguments        = $args
$lnk.WorkingDirectory = $Root
$lnk.IconLocation     = "$Icon,0"
$lnk.Description      = "LocalEmailStack - self-hosted cold-email control panel"
$lnk.WindowStyle      = 7   # minimized - the launcher actually opens Edge in app mode
$lnk.Save()

# Some Windows versions need a property refresh to pick up the icon immediately
$pinFolder = Join-Path $env:APPDATA "Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"
# (no-op if not present)

Write-Host "[ok] Desktop shortcut: $LnkPath"
Write-Host "  -> runs: $pwsh $args"
Write-Host "  -> icon: $Icon"
