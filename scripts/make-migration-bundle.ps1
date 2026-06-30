<#  make-migration-bundle.ps1 - rebuild les-migration.zip from the CURRENT stack.

Produces a self-contained move bundle: stack\ (current code + secrets + state),
tasks\ (all LES-* task XMLs), task-manifest.json (intended enabled/disabled state),
bootstrap.ps1 + MIGRATION.md + re-enable-old-pc.ps1 (reused from the prior bundle).

IMPORTANT: all LES tasks are currently DISABLED (migration state), so their live
state is not their INTENDED state. This script takes intended states from the prior
bundle's manifest, and for tasks created since then applies sensible defaults.
#>
param(
  [string]$Repo = 'C:\Users\bernh\local-email-stack',
  [string]$OldZip = 'C:\Users\bernh\les-migration.zip',
  [string]$Out = 'C:\Users\bernh\les-migration.zip'
)
$ErrorActionPreference = 'Stop'
function Say($m){ Write-Host "==> $m" -ForegroundColor Cyan }

$stage = Join-Path $env:TEMP ('lesmig-build-' + (Get-Date -Format 'yyyyMMddHHmmss'))
$ref   = Join-Path $env:TEMP ('lesmig-ref-'   + (Get-Date -Format 'yyyyMMddHHmmss'))
New-Item -ItemType Directory -Force $stage | Out-Null

# --- 0. unpack the prior bundle to reuse its scripts + intended task states ---
$haveOld = Test-Path $OldZip
if($haveOld){
  Expand-Archive -Path $OldZip -DestinationPath $ref -Force
  Say "unpacked prior bundle for reuse"
}

# --- 1. stack/ : current working tree, secrets + state IN, regenerables OUT -----
$stack = Join-Path $stage 'stack'
Say "copying stack (excluding .git, node_modules, caches, out)"
$xd = @('.git','node_modules','__pycache__','.site_cache','.vite','out','target','dist','.pytest_cache')
$xf = @('*.pyc','*.pyo','les-migration.zip')
robocopy $Repo $stack /E /XD $xd /XF $xf /NFL /NDL /NJH /NJS /R:1 /W:1 | Out-Null
if($LASTEXITCODE -ge 8){ throw "robocopy failed ($LASTEXITCODE)" }

# --- 2. tasks/ : export every LES-* task definition --------------------------
$tdir = Join-Path $stage 'tasks'; New-Item -ItemType Directory -Force $tdir | Out-Null
$les = Get-ScheduledTask | Where-Object { $_.TaskName -like 'LES-*' } | Sort-Object TaskName
Say "exporting $($les.Count) LES task definitions"
foreach($t in $les){
  $xml = Export-ScheduledTask -TaskName $t.TaskName
  [IO.File]::WriteAllText((Join-Path $tdir ($t.TaskName + '.xml')), $xml, [Text.UTF8Encoding]::new($false))
}

# --- 3. task-manifest.json : INTENDED states ---------------------------------
# Base = prior bundle's manifest (correct pre-migration states). New tasks get a
# sensible default: the AI-employee pipeline ON, the two popups OFF.
$intended = @{}
$oldManPath = Join-Path $ref 'task-manifest.json'
if(Test-Path $oldManPath){
  (Get-Content $oldManPath -Raw -Encoding UTF8 | ConvertFrom-Json) | ForEach-Object { $intended[$_.Name] = $_.State }
}
$newOn  = @('LES-employee-secretary','LES-employee-editor','LES-employee-bookkeeper','LES-employee-social-writer','LES-bookkeeper-feed','LES-bridge-portal-clients','LES-employee-autodeliver')
$newOff = @('LES-employee-review','LES-employee-checkin')
$manifest = foreach($t in $les){
  $state = if($intended.ContainsKey($t.TaskName)){ $intended[$t.TaskName] }
           elseif($newOff -contains $t.TaskName){ 'Disabled' }
           elseif($newOn  -contains $t.TaskName){ 'Ready' }
           else { 'Ready' }   # unknown new LES task: default ON
  [pscustomobject]@{ Name = $t.TaskName; State = $state }
}
$manifest | ConvertTo-Json | Out-File (Join-Path $stage 'task-manifest.json') -Encoding utf8
Say "manifest: $(@($manifest | Where-Object State -ne 'Disabled').Count) intended-active, $(@($manifest | Where-Object State -eq 'Disabled').Count) off"

# --- 4. reuse the bootstrap + docs from the prior bundle ----------------------
foreach($f in 'bootstrap.ps1','MIGRATION.md','re-enable-old-pc.ps1'){
  $src = Join-Path $ref $f
  if(Test-Path $src){ Copy-Item $src (Join-Path $stage $f) -Force }
  else { Write-Host "!! missing $f in prior bundle - carry it over manually" -ForegroundColor Yellow }
}

# --- 5. zip (fast .NET zip; never clobber the original .bak) ------------------
Add-Type -AssemblyName System.IO.Compression.FileSystem
if((Test-Path $Out) -and -not (Test-Path ($Out + '.bak'))){ Copy-Item $Out ($Out + '.bak') -Force; Say "backed up old zip -> $Out.bak" }
if(Test-Path $Out){ Remove-Item $Out -Force }
[System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $Out, [System.IO.Compression.CompressionLevel]::Optimal, $false)
$z = Get-Item $Out
Say ("wrote {0}  ({1:N1} MB)" -f $Out, ($z.Length/1MB))
Remove-Item $stage,$ref -Recurse -Force -ErrorAction SilentlyContinue
