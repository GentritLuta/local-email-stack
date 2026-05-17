# import-state.ps1 — restore a LocalEmailStack bundle on a new machine.
#
# Usage:
#   .\import-state.ps1 -Source C:\backups\les-2026-05-17.zip -Repo C:\Users\me\local-email-stack
#   .\import-state.ps1 -Source \\nas\share\les.zip -Repo C:\les -RestoreModels

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)] [string]$Source,
  [Parameter(Mandatory=$true)] [string]$Repo,
  [switch]$RestoreModels
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Source)) { throw "Bundle not found: $Source" }
$WorkDir = Join-Path $env:TEMP "les-import-$([guid]::NewGuid().ToString('n'))"
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null

Write-Host "▶ Extracting bundle"
Expand-Archive -Path $Source -DestinationPath $WorkDir -Force

$Meta = Get-Content (Join-Path $WorkDir "META.json") -Raw | ConvertFrom-Json
Write-Host "  Bundle id: $($Meta.bundle_id) (source: $($Meta.source_machine), created: $($Meta.created_at))"

Write-Host "▶ Restoring repo to $Repo"
New-Item -ItemType Directory -Path $Repo -Force | Out-Null
robocopy (Join-Path $WorkDir "repo") $Repo /MIR | Out-Null

$EnvSrc = Join-Path $WorkDir "env\bootstrap.env"
if (Test-Path $EnvSrc) {
  Copy-Item $EnvSrc (Join-Path $Repo "bootstrap.env") -Force
  Write-Host "  ✓ bootstrap.env restored"
}

foreach ($v in $Meta.volumes) {
  if (-not $RestoreModels -and $v -eq "local-email-stack_ollama_models") {
    Write-Host "  ⏭ Skipping LLM models (pass -RestoreModels to include)"
    continue
  }
  $Tarball = Join-Path $WorkDir "volumes\$v.tar.gz"
  if (-not (Test-Path $Tarball)) {
    Write-Host "  ⚠ Volume archive missing: $v"
    continue
  }
  Write-Host "▶ Restoring volume $v"
  docker volume create $v | Out-Null
  $TarballDir = Split-Path $Tarball -Parent
  $TarballName = Split-Path $Tarball -Leaf
  $Bind = "${TarballDir}:/backup:ro"
  docker run --rm -v "${v}:/data" -v $Bind busybox sh -c "rm -rf /data/* && tar xzf /backup/$TarballName -C /data" | Out-Null
}

Remove-Item -Recurse -Force $WorkDir
Write-Host ""
Write-Host "✓ Import complete."
Write-Host "  Next: cd '$Repo\docker' ; docker compose up -d"
Write-Host "  Then open LocalEmailStack.exe — point Settings → Stack repo path at '$Repo'."
