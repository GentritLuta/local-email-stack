# setup-rtx.ps1 - stand up the local AI operator on the RTX machine.
# Run once on the RTX (as the user who will operate it). Idempotent.
# ASCII only (Windows PowerShell 5.1 mis-parses non-ASCII). No em dashes.

param(
  [string]$Model = "qwen3-coder:30b",   # already installed on the HK RTX 4070 (see rtx-control kit)
  [string]$VpsHost = "188.209.157.127",
  [string]$VpsUser = "Administrator",
  [int]$EveryMinutes = 60
)
$ErrorActionPreference = "Stop"
function Say($m) { Write-Host ("==> " + $m) }

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Python (needed for the monitor scripts)
Say "Checking Python"
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { Write-Host "!! Install Python 3.12 from https://www.python.org and re-run."; exit 1 }
Say ("Python: " + (& python --version 2>&1))

# 2. Ollama (local model server)
Say "Checking Ollama"
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  Say "Installing Ollama via winget"
  winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
  Write-Host "!! If ollama is not on PATH yet, open a new terminal and re-run this script."
}
Say ("Pulling model " + $Model + " (this can take a while)")
ollama pull $Model

# 3. SSH key to the VPS
Say "Checking SSH access to the VPS"
$key = Join-Path $env:USERPROFILE ".ssh\id_ed25519_hostinger"
if (-not (Test-Path $key)) {
  Write-Host ("!! SSH key not found at " + $key)
  Write-Host "!! Copy id_ed25519_hostinger (+ .pub) from the laptop's ~/.ssh into this machine's ~/.ssh, then re-run."
  exit 1
}
Say "Testing VPS SSH"
$test = ssh -i $key -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "$VpsUser@$VpsHost" "hostname" 2>&1
Say ("VPS says: " + $test)

# 4. Environment for the operator (persisted for the scheduled task)
Say "Writing operator env"
[Environment]::SetEnvironmentVariable("OLLAMA_MODEL", $Model, "User")
[Environment]::SetEnvironmentVariable("VPS_HOST", $VpsHost, "User")
[Environment]::SetEnvironmentVariable("VPS_USER", $VpsUser, "User")
[Environment]::SetEnvironmentVariable("SSH_KEY", $key, "User")

# 5. Scheduled sweep of the VPS
Say "Registering the operator sweep task (every $EveryMinutes min)"
$pyExe = (Get-Command python).Source
$mon = Join-Path $Here "vps_monitor.py"
$action = New-ScheduledTaskAction -Execute $pyExe -Argument ('"' + $mon + '"') -WorkingDirectory $Here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd
Register-ScheduledTask -TaskName "RTX-operator-sweep" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Say "Registered RTX-operator-sweep"

# 6. Smoke test
Say "Local model health"
& python (Join-Path $Here "local_model.py")
Say "One monitor sweep (dry proof)"
& python $mon

Write-Host ""
Write-Host "DONE. The operator now sweeps the VPS every $EveryMinutes min and writes briefs to ~/aureon-operator-reports."
Write-Host "To STEER it from your laptop, see README.md (Open WebUI chat, or RDP + run vps_monitor.py on demand)."
