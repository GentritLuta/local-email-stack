"""The boss seat. Review what your employees produced.

    python review.py [role]      # review pending items (all roles, or one)

For each pending work product you can:
  a  approve -> it ships (emailed to info@) and is archived
  r  revise  -> type what needs fixing; the employee redoes it and re-presents
  s  skip    -> leave it in the queue for later
  v  view    -> print the full work product
  x  discard -> delete it unsent

Approve/revise is the loop you asked for: revise as many times as you want,
the employee keeps fixing and re-presenting until you approve.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import _lib as L
from employee import _parse_meta

_REVISE_SYSTEM = (
    "You are an autonomous employee revising your own earlier work product after "
    "your boss reviewed it and told you what to fix. Apply the feedback fully and "
    "return the COMPLETE corrected work product (not a diff). Use your tools to "
    "redo research if the feedback requires it. Plain human prose, no em dashes, "
    "no filler. Same hard rule: you never contact third parties or ship anything; "
    "you only produce and propose. End with the metadata block exactly:\n"
    "<<<EMPLOYEE_META\n"
    '{"title": "...", "summary": "...", "push_actions": [{"type": "...", "desc": "..."}], '
    '"memory_update": "..."}\n'
    "EMPLOYEE_META>>>"
)


def _pending_items(role_filter):
    items = []
    roles = [role_filter] if role_filter else L.list_roles()
    for role in roles:
        pdir = L.role_paths(role)["pending"]
        for f in sorted(pdir.glob("*.json")):
            items.append((role, f))
    return items


def _show(role, item):
    print("\n" + "=" * 72)
    print(f"ROLE:    {role}")
    print(f"TITLE:   {item['title']}   (v{item['version']}, {item['date']})")
    print(f"TASK:    {item['task']}")
    print(f"SUMMARY: {item['summary']}")
    if item.get("push_actions"):
        print("PROPOSED ACTIONS:")
        for a in item["push_actions"]:
            print(f"   - [{a.get('type', '?')}] {a.get('desc', '')}")
    print("-" * 72)
    body = item["body"]
    preview = body if len(body) <= 1600 else body[:1600] + "\n... [v to view full]"
    print(preview)
    print("=" * 72)


def _execute_actions(role, item, dry, allow_send=True):
    """On approval, send fully-specified email actions IF this role is cleared to
    send AND sends are allowed. allow_send=False (auto-deliver) HOLDS every
    third-party send as a proposal, so nothing reaches a third party unattended."""
    cfg = L.load_role_config(role)
    results = []
    for a in item.get("push_actions", []):
        if a.get("type") != "email" or not a.get("to") or not a.get("body"):
            continue
        if not allow_send or not cfg.get("can_send"):
            why = ("auto-deliver holds third-party sends" if not allow_send
                   else "role not cleared to send")
            results.append(f"  - [email->{a['to']}] HELD, not sent ({why}). "
                           f"{a.get('desc', '')}")
            continue
        ok = L.send_email(a["to"], a.get("subject", "(no subject)"), a["body"],
                          from_addr=cfg.get("send_from", L.OPERATOR_ADDR),
                          from_name=cfg.get("send_name", "Gentrit"), dry=dry)
        results.append(f"  - [email->{a['to']}] {'SENT' if ok else 'FAILED'}. "
                       f"{a.get('desc', '')}")
        print(f"    {'(dry) ' if dry else ''}{'sent' if ok else 'FAILED'} -> {a['to']}")
    return results


def _approve(role, fpath, item, dry, allow_send=True):
    sent_results = _execute_actions(role, item, dry, allow_send=allow_send)
    lines = [item["summary"], ""]
    if sent_results:
        lines.append("Actions executed on approval:")
        lines.extend(sent_results)
        lines.append("")
    other = [a for a in item.get("push_actions", [])
             if not (a.get("type") == "email" and a.get("to") and a.get("body"))]
    if other:
        lines.append("Recommended actions (do these yourself or tell me to):")
        for a in other:
            lines.append(f"  - [{a.get('type', '?')}] {a.get('desc', '')}")
        lines.append("")
    lines.append("=" * 60)
    lines.append(item["body"])
    body = "\n".join(lines)
    subject = f"[{role}] {item['title']}"
    ok = L.send_to_operator(subject, body, dry=dry)

    # archive
    item["status"] = "approved"
    apath = L.role_paths(role)["approved"] / fpath.name
    apath.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
    # also drop a readable copy in reports/
    rpath = L.role_paths(role)["reports"] / f"{item['date']}_{fpath.stem}.md"
    rpath.write_text(f"# {item['title']}\n\n{item['body']}\n", encoding="utf-8")
    try:  # also render the official-looking HTML version of the report
        import render_report
        hpath = L.role_paths(role)["reports"] / f"{item['date']}_{fpath.stem}.html"
        render_report.write_official_html(role, item, hpath)
        print(f"  rendered official HTML -> {hpath}")
    except Exception as e:
        print(f"  (html render skipped: {e})")
    fpath.unlink(missing_ok=True)

    # memory
    mem = L.load_memory(role)
    mem["runs"].append({"date": item["date"], "title": item["title"],
                        "summary": item["summary"], "status": "shipped"})
    if item.get("memory_update"):
        mem["standing_context"] = item["memory_update"]
    L.save_memory(role, mem)
    print(f"  approved. {'(dry) ' if dry else ''}shipped to info@ and archived.")


def _revise(role, fpath, item, notes=None, remember=False):
    if notes is None:  # terminal path
        notes = input("  What needs fixing? > ").strip()
        if notes and input("  Remember this as a permanent rule? [y/N] ").strip().lower() == "y":
            remember = True
    notes = (notes or "").strip()
    if not notes:
        print("  (no notes; left as-is)")
        return item
    if remember:
        L.append_standing_order(role, notes)
        print(f"  remembered as a permanent standing order for {role}.")
    charter = L.load_charter(role)
    prompt = (f"# YOUR ROLE CHARTER\n{charter}\n\n"
              f"# YOUR EARLIER WORK PRODUCT (v{item['version']})\n{item['body']}\n\n"
              f"# YOUR BOSS'S FEEDBACK\n{notes}\n\n"
              "Redo the work, fix everything in the feedback, and return the full "
              "corrected work product plus the metadata block.")
    print("  employee is revising...")
    out = L.ask_claude(_REVISE_SYSTEM, prompt, cwd=L.role_paths(role)["base"] / "workspace")
    body, meta = _parse_meta(out)
    item["version"] += 1
    item["revision_log"].append({"v": item["version"], "feedback": notes})
    item["body"] = body
    item["title"] = meta.get("title", item["title"])
    item["summary"] = meta.get("summary", item["summary"])
    item["push_actions"] = meta.get("push_actions", item["push_actions"])
    item["memory_update"] = meta.get("memory_update", item.get("memory_update", ""))
    fpath.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  revised to v{item['version']}. Re-presenting.")
    return item


# ─── desktop popup review (with email fallback) ─────────────────────────────

_PS_DIALOG = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$header = [IO.File]::ReadAllText('{HEADERFILE}')
$body   = [IO.File]::ReadAllText('{BODYFILE}')
$f = New-Object System.Windows.Forms.Form
$f.Text = 'AI employee review'
$f.Size = New-Object System.Drawing.Size(700,675)
$f.StartPosition = 'CenterScreen'
$f.TopMost = $true
$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = $header
$lbl.Location = New-Object System.Drawing.Point(12,10)
$lbl.Size = New-Object System.Drawing.Size(660,95)
$f.Controls.Add($lbl)
$bt = New-Object System.Windows.Forms.TextBox
$bt.Multiline = $true; $bt.ReadOnly = $true; $bt.ScrollBars = 'Vertical'
$bt.Location = New-Object System.Drawing.Point(12,110)
$bt.Size = New-Object System.Drawing.Size(660,335)
$bt.Text = $body
$f.Controls.Add($bt)
$nl = New-Object System.Windows.Forms.Label
$nl.Text = 'What needs fixing (used by Send back to fix):'
$nl.Location = New-Object System.Drawing.Point(12,452)
$nl.Size = New-Object System.Drawing.Size(660,18)
$f.Controls.Add($nl)
$tb = New-Object System.Windows.Forms.TextBox
$tb.Multiline = $true; $tb.ScrollBars = 'Vertical'
$tb.Location = New-Object System.Drawing.Point(12,472)
$tb.Size = New-Object System.Drawing.Size(660,72)
$f.Controls.Add($tb)
$rem = New-Object System.Windows.Forms.CheckBox
$rem.Text = 'Remember this fix as a permanent rule (never make this mistake again)'
$rem.Location = New-Object System.Drawing.Point(12,550)
$rem.Size = New-Object System.Drawing.Size(660,22)
$f.Controls.Add($rem)
$script:outcome = 'skip'
$ba = New-Object System.Windows.Forms.Button
$ba.Text = 'Approve and ship'; $ba.Location = New-Object System.Drawing.Point(12,580); $ba.Size = New-Object System.Drawing.Size(150,32)
$ba.Add_Click({ $script:outcome = 'approve'; $f.Close() })
$f.Controls.Add($ba)
$br = New-Object System.Windows.Forms.Button
$br.Text = 'Send back to fix'; $br.Location = New-Object System.Drawing.Point(170,580); $br.Size = New-Object System.Drawing.Size(150,32)
$br.Add_Click({ $script:outcome = 'revise'; $f.Close() })
$f.Controls.Add($br)
$bs = New-Object System.Windows.Forms.Button
$bs.Text = 'Skip'; $bs.Location = New-Object System.Drawing.Point(328,580); $bs.Size = New-Object System.Drawing.Size(100,32)
$bs.Add_Click({ $script:outcome = 'skip'; $f.Close() })
$f.Controls.Add($bs)
$bx = New-Object System.Windows.Forms.Button
$bx.Text = 'Discard'; $bx.Location = New-Object System.Drawing.Point(436,580); $bx.Size = New-Object System.Drawing.Size(100,32)
$bx.Add_Click({ $script:outcome = 'discard'; $f.Close() })
$f.Controls.Add($bx)
[void]$f.ShowDialog()
$out = @{ outcome = $script:outcome; notes = $tb.Text; remember = $rem.Checked } | ConvertTo-Json -Compress
Write-Output $out
'''


def _popup(role, item):
    """Show the review popup. Returns (status, outcome, notes, remember).
    status is 'ok' if the dialog displayed, 'unavailable' if it could not."""
    header = (f"ROLE: {role}    (v{item['version']}, {item['date']})\n"
              f"TITLE: {item['title']}\n"
              f"TASK: {item['task']}\n"
              f"SUMMARY: {item['summary']}")
    if item.get("push_actions"):
        header += "\nPROPOSED: " + "; ".join(
            f"[{a.get('type', '?')}] {a.get('desc', '')}" for a in item["push_actions"])
    tmp = Path(tempfile.mkdtemp(prefix="emp_review_"))
    hf, bf = tmp / "header.txt", tmp / "body.txt"
    hf.write_text(header, encoding="utf-8")
    bf.write_text(item["body"], encoding="utf-8")
    script = (_PS_DIALOG.replace("{HEADERFILE}", str(hf).replace("\\", "\\\\"))
                        .replace("{BODYFILE}", str(bf).replace("\\", "\\\\")))
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=1800,
            encoding="utf-8", errors="replace")
        out = (proc.stdout or "").strip()
        jline = [l for l in out.splitlines() if l.strip().startswith("{")]
        if not jline:
            return ("unavailable", None, None, False)
        data = json.loads(jline[-1])
        return ("ok", data.get("outcome", "skip"), data.get("notes", "") or "",
                bool(data.get("remember", False)))
    except Exception as e:
        print(f"  ! popup failed: {e}")
        return ("unavailable", None, None, False)


def _email_fallback(role, fpath, item):
    """Popup could not show. Email the draft to the operator once."""
    if item.get("review_notified"):
        print(f"  [{role}] popup unavailable; already emailed earlier. Left pending.")
        return
    lines = [f"Desktop popup could not be shown, so here is the draft for review.",
             "To approve or send it back, run:  python review.py", "",
             f"SUMMARY: {item['summary']}", ""]
    if item.get("push_actions"):
        lines.append("Proposed actions:")
        for a in item["push_actions"]:
            lines.append(f"  - [{a.get('type', '?')}] {a.get('desc', '')}")
        lines.append("")
    lines.append("=" * 60)
    lines.append(item["body"])
    L.send_to_operator(f"[Review needed] [{role}] {item['title']}", "\n".join(lines))
    item["review_notified"] = True
    fpath.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [{role}] popup unavailable; emailed draft to info@. Left pending.")


def _review_popup(items, dry):
    for role, fpath in items:
        if not fpath.exists():
            continue
        item = json.loads(fpath.read_text(encoding="utf-8"))
        while True:
            status, outcome, notes, remember = _popup(role, item)
            if status == "unavailable":
                _email_fallback(role, fpath, item)
                break
            if outcome == "approve":
                _approve(role, fpath, item, dry)
                break
            elif outcome == "revise":
                item = _revise(role, fpath, item, notes=notes, remember=remember)
                continue
            elif outcome == "discard":
                fpath.unlink(missing_ok=True)
                print(f"  [{role}] discarded.")
                break
            else:
                print(f"  [{role}] skipped (still pending).")
                break


def _review_terminal(items, dry):
    for role, fpath in items:
        if not fpath.exists():
            continue
        item = json.loads(fpath.read_text(encoding="utf-8"))
        while True:
            _show(role, item)
            choice = input("  [a]pprove  [r]evise  [s]kip  [v]iew  [x]discard > ").strip().lower()
            if choice == "a":
                _approve(role, fpath, item, dry)
                break
            elif choice == "r":
                item = _revise(role, fpath, item)
                continue
            elif choice == "v":
                print("\n" + item["body"] + "\n")
                continue
            elif choice == "x":
                fpath.unlink(missing_ok=True)
                print("  discarded.")
                break
            else:
                print("  skipped (still pending).")
                break


def _auto_deliver(items, dry):
    """Hands-off mode: for every role flagged auto_approve, ship its pending work
    to info@ (archive + official HTML) with NO popup and NO human. Third-party
    sends are HELD as proposals, never fired unattended."""
    shipped, skipped = 0, 0
    for role, fpath in items:
        if not fpath.exists():
            continue
        if not L.load_role_config(role).get("auto_approve"):
            skipped += 1
            continue
        item = json.loads(fpath.read_text(encoding="utf-8"))
        print(f"[{role}] auto-delivering: {item['title']}")
        _approve(role, fpath, item, dry, allow_send=False)
        shipped += 1
    print(f"auto-deliver: shipped {shipped} item(s) to info@"
          + (f", {skipped} left for manual review (not auto-approve)." if skipped else "."))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("role", nargs="?", default=None)
    ap.add_argument("--popup", action="store_true",
                    help="review via desktop popup (email fallback if it can't show)")
    ap.add_argument("--auto", action="store_true",
                    help="hands-off: auto-deliver auto_approve roles to info@, no popup")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    items = _pending_items(args.role)
    if not items:
        print("Nothing pending. All clear, boss.")
        return 0

    if args.auto:
        _auto_deliver(items, args.dry)
        return 0

    print(f"{len(items)} item(s) awaiting your review.")
    if args.popup:
        _review_popup(items, args.dry)
    else:
        _review_terminal(items, args.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
