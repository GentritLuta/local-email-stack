# -*- coding: utf-8 -*-
"""vps_monitor.py - the RTX operator's routine health sweep of the production VPS.

Runs on the RTX. SSHes into the VPS, checks every LES task + sends + DB reachability,
AUTO-FIXES only the safe known failures (pyw path error -> repoint; stale one-off failure
-> re-trigger), ESCALATES everything else, and writes a daily brief. Reasoning/summary is
done by the local model (local_model.py). Stdlib only + the ssh binary on PATH.

Guardrails (see OPERATOR_CHARTER.md): never raise a cap, never send mail, never touch schema.
Env: VPS_HOST, VPS_USER, SSH_KEY, PYW_GOOD (correct pythonw path), REPORT_DIR.
"""
import os, sys, json, base64, subprocess, datetime as dt
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = os.environ.get("VPS_HOST", "188.209.157.127")
USER = os.environ.get("VPS_USER", "Administrator")
KEY  = os.environ.get("SSH_KEY", str(Path.home() / ".ssh" / "id_ed25519_hostinger"))
PYW_GOOD = os.environ.get("PYW_GOOD",
    r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\pythonw.exe")
REPORT_DIR = Path(os.environ.get("REPORT_DIR", str(Path.home() / "aureon-operator-reports")))
PATH_ERR = 2147942402  # 0x80070002


def ssh_ps(ps: str, timeout: int = 180) -> str:
    """Run a PowerShell script on the VPS via base64 EncodedCommand (dodges quoting)."""
    b64 = base64.b64encode(ps.encode("utf-16-le")).decode()
    cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=accept-new",
           f"{USER}@{HOST}", "powershell", "-NoProfile", "-EncodedCommand", b64]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = p.stdout
    # strip the PS-remoting CLIXML/progress noise
    return "\n".join(l for l in out.splitlines()
                     if not l.startswith(("#< CLIXML", "<Objs", "  ")) or "{" in l or "}" in l)


def gather_health() -> dict:
    """One round-trip: task states + send count + DB reachability, returned as JSON."""
    ps = r'''
$today = (Get-Date).Date
$tasks = Get-ScheduledTask | Where-Object { $_.TaskName -like "LES-*" -and $_.State -ne "Disabled" } | ForEach-Object {
  $i = $_ | Get-ScheduledTaskInfo
  [PSCustomObject]@{ name=$_.TaskName; state=[string]$_.State; result=$i.LastTaskResult;
    lastRun=(if($i.LastRunTime){$i.LastRunTime.ToString("s")}else{""});
    ranToday=($i.LastRunTime -ge $today);
    nextRun=(if($i.NextRunTime){$i.NextRunTime.ToString("s")}else{""}) }
}
# DB reachability + today's sends, read on the VPS with its own env
$env2 = "C:\Users\Administrator\local-email-stack\sequences\supabase.env"
$url = ((Get-Content $env2 | Where-Object {$_ -match "^SUPABASE_URL="}) -replace "^SUPABASE_URL=","").Trim()
$key = ((Get-Content $env2 | Where-Object {$_ -match "^SUPABASE_SERVICE_KEY="}) -replace "^SUPABASE_SERVICE_KEY=","").Trim()
$dbok = $false; $sends = -1
try {
  $r = Invoke-WebRequest -Uri "$url/rest/v1/send_log?select=count&sent_at=gte.$($today.ToString('yyyy-MM-dd'))" -Headers @{apikey=$key;Authorization="Bearer $key"} -UseBasicParsing -TimeoutSec 20
  $dbok = $true; $sends = ([regex]::Match($r.Content,'\d+')).Value
} catch { $dbok = $false }
[PSCustomObject]@{ machine=(hostname); dbReachable=$dbok; sendsToday=$sends; tasks=$tasks } | ConvertTo-Json -Depth 5 -Compress
'''
    raw = ssh_ps(ps)
    start = raw.find("{")
    return json.loads(raw[start:]) if start >= 0 else {"error": raw[:400]}


def classify(tasks: list) -> dict:
    buckets = {"path_error": [], "exit1": [], "running": [], "ok": [], "other": []}
    for t in tasks:
        r = t.get("result")
        if r == PATH_ERR:      buckets["path_error"].append(t)
        elif r == 0:           buckets["ok"].append(t)
        elif r == 267009:      buckets["running"].append(t)
        elif r == 1:           buckets["exit1"].append(t)
        elif r == 267011:      pass  # scheduled, not yet run
        else:                  buckets["other"].append(t)
    return buckets


def auto_fix_path_errors(tasks: list) -> list:
    """SAFE fix: repoint any pyw/wrong-exec task to the good pythonw, then re-trigger."""
    fixed = []
    for t in tasks:
        n = t["name"]
        ps = f'''
$t = Get-ScheduledTask -TaskName "{n}"; $a = $t.Actions[0]
if ($a.Execute -ne "{PYW_GOOD}") {{
  if ([string]::IsNullOrEmpty($a.WorkingDirectory)) {{ $na = New-ScheduledTaskAction -Execute "{PYW_GOOD}" -Argument $a.Arguments }}
  else {{ $na = New-ScheduledTaskAction -Execute "{PYW_GOOD}" -Argument $a.Arguments -WorkingDirectory $a.WorkingDirectory }}
  Set-ScheduledTask -TaskName "{n}" -Action $na | Out-Null
}}
Start-ScheduledTask -TaskName "{n}"
Write-Output "repointed+triggered {n}"
'''
        ssh_ps(ps, timeout=60)
        fixed.append(n)
    return fixed


def build_escalations(health: dict, b: dict) -> list:
    esc = []
    if not health.get("dbReachable"):
        esc.append("DB not reachable over REST (possible 402/egress cap or outage). CHECK Supabase.")
    try:
        if int(health.get("sendsToday", -1)) == 0:
            esc.append("Zero sends today. If inside the send window, a sender is stuck - investigate or escalate to cloud Claude.")
    except (TypeError, ValueError):
        pass
    for t in b["other"]:
        esc.append(f"UNKNOWN failure on {t['name']} (result={t.get('result')}). New error - do NOT auto-fix; escalate.")
    if b["exit1"]:
        esc.append("Tasks with exit-1 (script-level, usually benign but verify): " + ", ".join(t["name"] for t in b["exit1"]))
    return esc


def main() -> int:
    stamp = os.environ.get("RUN_STAMP") or "unstamped"  # pass a real timestamp from the scheduler
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("== RTX operator sweep ==")
    health = gather_health()
    if "error" in health:
        print("SWEEP FAILED:", health["error"]); return 2
    b = classify(health.get("tasks", []))
    print(f"machine={health.get('machine')} dbReachable={health.get('dbReachable')} sendsToday={health.get('sendsToday')}")
    print(f"tasks: ok={len(b['ok'])} running={len(b['running'])} exit1={len(b['exit1'])} "
          f"path_error={len(b['path_error'])} other={len(b['other'])}")

    fixed = auto_fix_path_errors(b["path_error"]) if b["path_error"] else []
    if fixed:
        print("AUTO-FIXED (repointed+retriggered):", ", ".join(fixed))

    escalations = build_escalations(health, b)

    # local-model summary for the human brief (optional; degrades gracefully if model down)
    summary = ""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from local_model import ask_local, health as lm_health
        up, _ = lm_health()
        if up:
            summary = ask_local(
                system=open(Path(__file__).parent / "OPERATOR_CHARTER.md", encoding="utf-8").read(),
                prompt=("Write a 4-6 line operator brief from this sweep JSON. Lead with the state, "
                        "be concrete, flag what needs a human. No filler.\n\n" + json.dumps({
                            "health": {k: health[k] for k in ("machine", "dbReachable", "sendsToday") if k in health},
                            "counts": {k: len(v) for k, v in b.items()},
                            "auto_fixed": fixed, "escalations": escalations})))
    except Exception as e:
        summary = f"(local-model summary unavailable: {e})"

    report = REPORT_DIR / f"brief-{stamp}.md"
    with open(report, "w", encoding="utf-8") as f:
        f.write(f"# Aureon VPS operator brief {stamp}\n\n")
        f.write(f"- machine: {health.get('machine')} | DB reachable: {health.get('dbReachable')} | sends today: {health.get('sendsToday')}\n")
        f.write(f"- tasks: ok={len(b['ok'])} running={len(b['running'])} exit1={len(b['exit1'])} path_error={len(b['path_error'])} other={len(b['other'])}\n")
        f.write(f"- auto-fixed: {', '.join(fixed) if fixed else 'none'}\n\n")
        f.write("## Needs a human\n" + ("\n".join(f"- {e}" for e in escalations) if escalations else "- nothing\n") + "\n\n")
        f.write("## Summary\n" + (summary or "(none)") + "\n")
    print("brief ->", report)
    print("ESCALATIONS:", len(escalations))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
