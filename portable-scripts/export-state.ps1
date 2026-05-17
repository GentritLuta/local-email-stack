# export-state.ps1 — full LocalEmailStack backup to a single .zip
#
# Same shape as the Settings → Portable → Export button in the desktop app,
# but usable headless (cron, scripted machine swaps).
#
# Usage:
#   .\export-state.ps1 -Output C:\backups\les-2026-05-17.zip [-IncludeModels]
#   .\export-state.ps1 -Output \\nas\share\les.zip -Repo C:\Users\me\local-email-stack
#
# Restore on another PC: .\import-state.ps1 -Source <path> -Repo <new-folder>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)] [string]$Output,
  [string]$Repo = (Resolve-Path "$PSScriptRoot\..").Path,
  [switch]$IncludeModels
)

$ErrorActionPreference = "Stop"

$Volumes = @(
  "local-email-stack_postgres_data",
  "local-email-stack_n8n_data",
  "local-email-stack_twenty_data",
  "local-email-stack_minio_data",
  "local-email-stack_qdrant_data",
  "local-email-stack_redis_data",
  "local-email-stack_nocodb_data",
  "local-email-stack_grafana_data",
  "local-email-stack_prometheus_data",
  "local-email-stack_loki_data",
  "local-email-stack_searxng_data",
  "local-email-stack_federation_repo",
  "local-email-stack_traefik_certs"
)
if ($IncludeModels) {
  $Volumes += "local-email-stack_ollama_models"
}

$WorkDir = Join-Path $env:TEMP "les-export-$([guid]::NewGuid().ToString('n'))"
$BundleDir = Join-Path $WorkDir "bundle"
New-Item -ItemType Directory -Path $BundleDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $BundleDir "repo") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $BundleDir "env") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $BundleDir "volumes") -Force | Out-Null

Write-Host "▶ Copying repo from $Repo"
$ExcludeDirs = @("target", "node_modules", ".git", "dist", "build", "__pycache__")
robocopy $Repo (Join-Path $BundleDir "repo") /MIR /XD $ExcludeDirs | Out-Null

$EnvPath = Join-Path $Repo "bootstrap.env"
if (Test-Path $EnvPath) {
  Copy-Item $EnvPath (Join-Path $BundleDir "env\bootstrap.env")
  Write-Host "  ✓ bootstrap.env included (sensitive — encrypt before sharing)"
}

$Existing = docker volume ls --format "{{.Name}}"
$Chosen = @()
foreach ($v in $Volumes) {
  if ($Existing -contains $v) {
    $Target = Join-Path $BundleDir "volumes\$v.tar.gz"
    Write-Host "▶ Exporting volume $v"
    $TargetDir = Split-Path $Target -Parent
    $TargetName = Split-Path $Target -Leaf
    $Bind = "${TargetDir}:/backup"
    docker run --rm -v "${v}:/data:ro" -v $Bind busybox tar czf "/backup/$TargetName" -C /data . | Out-Null
    $Chosen += $v
  } else {
    Write-Host "  ⚠ Volume $v not present, skipping"
  }
}

$Meta = @{
  version          = "0.4.0"
  created_at       = (Get-Date).ToString("o")
  source_machine   = $env:COMPUTERNAME
  bundle_id        = "les-$([int][double]::Parse((Get-Date -UFormat %s)))"
  includes_models  = [bool]$IncludeModels
  volumes          = $Chosen
} | ConvertTo-Json -Depth 5
Set-Content -Path (Join-Path $BundleDir "META.json") -Value $Meta -Encoding utf8

Write-Host "▶ Compressing bundle to $Output"
if (Test-Path $Output) { Remove-Item $Output -Force }
Compress-Archive -Path "$BundleDir\*" -DestinationPath $Output -CompressionLevel Optimal

Remove-Item -Recurse -Force $WorkDir
$SizeMb = (Get-Item $Output).Length / 1MB
Write-Host ("✓ Bundle written: {0} ({1:N1} MB)" -f $Output, $SizeMb)
