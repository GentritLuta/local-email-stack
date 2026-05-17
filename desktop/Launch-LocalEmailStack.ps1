# Launch-LocalEmailStack.ps1
# Smart launcher used by the desktop shortcut.
#
# Strategy (best → fallback):
#   1. If `target\release\local-email-stack.exe` exists (real Tauri build), run it.
#   2. Else if Node is installed:
#        - ensure `npm install` has been run
#        - start `vite` on port 5173 if it isn't already listening
#        - open the dashboard in Edge app-mode (looks like a native window,
#          no browser chrome) — backed by the in-app mock layer when Rust + Docker
#          aren't installed yet.
#   3. Else: show a friendly toast pointing at DESKTOP_APP.md.

[CmdletBinding()]
param(
  [switch]$NoWindow,
  [int]$DevPort = 5173
)

$ErrorActionPreference = "Stop"

$Root      = Split-Path -Parent $PSCommandPath
$Frontend  = Join-Path $Root "frontend"
$TauriExe  = Join-Path $Root "src-tauri\target\release\local-email-stack.exe"
$LogDir    = Join-Path $Root "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

function Write-Log([string]$msg) {
  $line = "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $msg
  Add-Content -Path (Join-Path $LogDir "launcher.log") -Value $line -Encoding utf8
  if (-not $NoWindow) { Write-Host $line }
}

function Test-Listener([int]$port) {
  $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Find-Edge {
  $candidates = @(
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
  )
  foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
  return $null
}

# ─── Path 1: real Tauri .exe present? ───────────────────────────────────────
if (Test-Path $TauriExe) {
  Write-Log "Launching native Tauri .exe at $TauriExe"
  Start-Process -FilePath $TauriExe
  exit 0
}

Write-Log "Native .exe not built yet — falling back to dev-mode launch"

# ─── Path 2: dev-mode via Edge app-window ───────────────────────────────────
$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue)?.Source
$nodeCmd = (Get-Command node.exe -ErrorAction SilentlyContinue)?.Source
if (-not $npmCmd -or -not $nodeCmd) {
  $msg = @"
LocalEmailStack needs Node.js to run in dev mode (or Rust + cargo to build the native .exe).

Install:
  • Node 20 LTS:  https://nodejs.org/
  • Rust:         https://rustup.rs/   (only for the production .exe)
  • Docker:       https://www.docker.com/products/docker-desktop/   (for the actual pipeline)

Then re-run this shortcut.
See: $Root\..\DESKTOP_APP.md
"@
  Write-Log $msg
  if (-not $NoWindow) {
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    [System.Windows.Forms.MessageBox]::Show($msg, "LocalEmailStack", "OK", "Information") | Out-Null
  }
  exit 1
}

# Install deps once
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
  Write-Log "First-run: npm install (this can take 1–3 minutes)"
  Start-Process -FilePath $npmCmd -ArgumentList @("install","--silent","--no-audit","--no-fund") `
    -WorkingDirectory $Frontend -Wait -WindowStyle Hidden
}

# Start Vite if it isn't already running on $DevPort
if (-not (Test-Listener $DevPort)) {
  Write-Log "Starting Vite dev server on port $DevPort"
  Start-Process -FilePath $npmCmd `
                -ArgumentList @("run","dev","--","--host","127.0.0.1","--port",$DevPort) `
                -WorkingDirectory $Frontend `
                -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $LogDir "dev-server.log") `
                -RedirectStandardError  (Join-Path $LogDir "dev-server.err")
  # Wait for the listener
  $deadline = (Get-Date).AddSeconds(30)
  while ((Get-Date) -lt $deadline -and -not (Test-Listener $DevPort)) {
    Start-Sleep -Milliseconds 250
  }
  if (-not (Test-Listener $DevPort)) {
    Write-Log "Vite failed to start within 30s — see $LogDir\dev-server.log"
    exit 1
  }
}

$Url  = "http://127.0.0.1:$DevPort/"
$Edge = Find-Edge

if ($Edge) {
  Write-Log "Opening in Edge app-mode → $Url"
  # --app puts Edge in chrome-less window mode (looks like a native app).
  # --user-data-dir keeps app state separate from the user's normal Edge profile.
  $profileDir = Join-Path $env:LOCALAPPDATA "LocalEmailStack\EdgeProfile"
  if (-not (Test-Path $profileDir)) { New-Item -ItemType Directory -Path $profileDir -Force | Out-Null }
  Start-Process -FilePath $Edge -ArgumentList @(
    "--app=$Url",
    "--user-data-dir=$profileDir",
    "--no-first-run",
    "--no-default-browser-check",
    "--window-size=1440,900"
  )
} else {
  Write-Log "Edge not found — opening in default browser"
  Start-Process $Url
}
