"""Daily check-in: 'here is what your team does each day - anything to add?'

    python checkin.py            # popup across all roles (email-free; just edits files)
    python checkin.py --print    # print each role's routine + orders, no popup

Shows every employee's routine and standing orders, and lets you add to them in one
box. One instruction per line, routed by prefix:

    secretary: also scan the spam folder for missed replies      -> routine item
    order editor: never use the word 'leverage'                  -> permanent rule

Additions are permanent. The next shift picks them up. If you are not at the PC, the
popup times out after a few minutes and changes nothing, so scheduled runs are safe.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import _lib as L

_PS_DIALOG = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$display = [IO.File]::ReadAllText('{DISPLAYFILE}')
$f = New-Object System.Windows.Forms.Form
$f.Text = 'Daily check-in - your AI team'
$f.Size = New-Object System.Drawing.Size(720,700)
$f.StartPosition = 'CenterScreen'
$f.TopMost = $true
$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = 'Here is what your team does each day. Add anything? One per line - "role: task" for routine, "order role: rule" for a permanent rule.'
$lbl.Location = New-Object System.Drawing.Point(12,8)
$lbl.Size = New-Object System.Drawing.Size(680,34)
$f.Controls.Add($lbl)
$bt = New-Object System.Windows.Forms.TextBox
$bt.Multiline = $true; $bt.ReadOnly = $true; $bt.ScrollBars = 'Vertical'
$bt.Location = New-Object System.Drawing.Point(12,46)
$bt.Size = New-Object System.Drawing.Size(680,400)
$bt.Text = $display
$f.Controls.Add($bt)
$nl = New-Object System.Windows.Forms.Label
$nl.Text = 'Additions:'
$nl.Location = New-Object System.Drawing.Point(12,452)
$nl.Size = New-Object System.Drawing.Size(680,18)
$f.Controls.Add($nl)
$tb = New-Object System.Windows.Forms.TextBox
$tb.Multiline = $true; $tb.ScrollBars = 'Vertical'
$tb.Location = New-Object System.Drawing.Point(12,472)
$tb.Size = New-Object System.Drawing.Size(680,120)
$f.Controls.Add($tb)
$script:action = 'skip'
$bsave = New-Object System.Windows.Forms.Button
$bsave.Text = 'Save additions'; $bsave.Location = New-Object System.Drawing.Point(12,602); $bsave.Size = New-Object System.Drawing.Size(150,32)
$bsave.Add_Click({ $script:action = 'save'; $f.Close() })
$f.Controls.Add($bsave); $f.AcceptButton = $bsave
$bskip = New-Object System.Windows.Forms.Button
$bskip.Text = 'Nothing to add'; $bskip.Location = New-Object System.Drawing.Point(170,602); $bskip.Size = New-Object System.Drawing.Size(150,32)
$bskip.Add_Click({ $script:action = 'skip'; $f.Close() })
$f.Controls.Add($bskip); $f.CancelButton = $bskip
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 240000
$timer.Add_Tick({ $script:action = 'skip'; $timer.Stop(); $f.Close() })
$timer.Start()
[void]$f.ShowDialog()
$timer.Stop()
$out = @{ action = $script:action; text = $tb.Text } | ConvertTo-Json -Compress
Write-Output $out
'''


def _build_display() -> str:
    lines = []
    for role in L.list_roles():
        lines.append("=" * 60)
        lines.append(role.upper())
        routine = L.load_routine(role).strip()
        lines.append("Routine:")
        lines.append(routine if routine else "  (no routine set)")
        orders = L.load_standing_orders(role).strip()
        if orders:
            lines.append("Standing orders:")
            lines.append(orders)
        lines.append("")
    return "\n".join(lines)


def _apply(text: str):
    roles = set(L.list_roles())
    added = 0
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        is_order = False
        body = line
        if line.lower().startswith("order "):
            is_order = True
            body = line[6:].strip()
        if ":" not in body:
            print(f"  (skipped, no 'role:' prefix) {line}")
            continue
        role, instr = body.split(":", 1)
        role, instr = role.strip().lower(), instr.strip()
        if role not in roles:
            print(f"  (skipped, unknown role '{role}') {line}")
            continue
        if not instr:
            continue
        if is_order:
            L.append_standing_order(role, instr)
            print(f"  + standing order [{role}]: {instr}")
        else:
            L.append_routine(role, instr)
            print(f"  + routine [{role}]: {instr}")
        added += 1
    print(f"check-in: {added} addition(s) saved." if added else "check-in: nothing added.")


def _popup() -> str | None:
    tmp = Path(tempfile.mkdtemp(prefix="emp_checkin_"))
    df = tmp / "display.txt"
    df.write_text(_build_display(), encoding="utf-8")
    script = _PS_DIALOG.replace("{DISPLAYFILE}", str(df).replace("\\", "\\\\"))
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=1800,
            encoding="utf-8", errors="replace")
        out = (proc.stdout or "").strip()
        jline = [l for l in out.splitlines() if l.strip().startswith("{")]
        if not jline:
            return None
        data = json.loads(jline[-1])
        return data.get("text", "") if data.get("action") == "save" else ""
    except Exception as e:
        print(f"  ! check-in popup failed: {e}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="show", action="store_true",
                    help="print routines + orders instead of the popup")
    args = ap.parse_args()
    if args.show:
        print(_build_display())
        return 0
    text = _popup()
    if text is None:
        print("check-in: popup unavailable; no changes.")
        return 0
    if not text.strip():
        print("check-in: nothing to add.")
        return 0
    _apply(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
