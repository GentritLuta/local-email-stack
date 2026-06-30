# Self-healing watchdog: re-enable any LES-* scheduled task that got disabled by
# the (still-unknown) external disabler. Skips the tasks we intentionally keep off.
# Runs every 30 min as SYSTEM, and is named OUTSIDE the LES- family so an
# LES-targeting disabler does not take the watchdog down with it.
$ErrorActionPreference = 'SilentlyContinue'
$keepOff = @('LES-employee-review', 'LES-employee-checkin', 'LES-diraya-selftest')
$disabled = Get-ScheduledTask | Where-Object {
    $_.TaskName -like 'LES-*' -and $_.State -eq 'Disabled' -and $_.TaskName -notin $keepOff
}
$n = 0
foreach ($t in $disabled) {
    try { Enable-ScheduledTask -TaskName $t.TaskName -ErrorAction Stop | Out-Null; $n++ } catch {}
}
if ($n -gt 0) {
    $log = 'C:\Users\bernh\local-email-stack\out\reenable-watchdog.log'
    $names = ($disabled | ForEach-Object TaskName) -join ', '
    Add-Content -Path $log -Value ("{0}  re-enabled {1}: {2}" -f (Get-Date -Format s), $n, $names)
}
