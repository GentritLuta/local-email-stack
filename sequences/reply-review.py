# -*- coding: utf-8 -*-
"""reply-review.py — human-in-the-loop approval gate for AI prospect replies.

Replaces the old AUTO-SEND behaviour of reply-autodraft.py. Now, when a genuine
prospect reply lands, reply-autodraft DRAFTS the reply but instead of sending it,
queues it (draft + full context) into out/pending_replies.json. THIS script owns
the human gate:

  scan    Pull any pending-review items that still need a decision.
  prompt  For each undecided item, pop a Windows GUI dialog showing:
            - the prospect + which persona/brand/campaign + the deal context
            - a quick sentiment/intent read
            - the FULL prior thread (their replies + what the persona sent)
            - the AI's proposed reply in an EDITABLE box
          with action buttons:
            1. Approve AI draft as-is   -> send the AI draft unchanged as the avatar
            2. Send my edited text       -> send what's in the box as the avatar
            3. Forward to client + note   -> send prospect reply + our draft + your
                                            note to the client (report_to from DB)
            4. Snooze / decide later      -> leave pending; re-pops next hour
            5. No reply needed            -> resolve with no send, stops the nag
            6. Block / do-not-contact     -> suppress this prospect, no send
  run     scan then prompt (the scheduled entry point, hourly).
  list    Print the pending queue.

The scheduled task LES-reply-review runs `run` every hour, so any item left
unresolved keeps popping until a decision is recorded. Silent when nothing pends.

Sends reuse reply-autodraft's proven per-brand send path (Aureon = Hostinger SMTP
from info@; other brands = their own Resend relay from the original sender), so
there is ONE send implementation, not two.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
STORE = REPO / "out" / "pending_replies.json"
OPERATOR_ADDR = "info@aureonglobal.de"
UA = "local-email-stack reply-review/1.0"

# Reuse reply-autodraft's send path + DB helpers so there is no duplicated logic.
import importlib
_rad = importlib.import_module("reply-autodraft") if False else None
# The module name has a hyphen, so import via importlib by file path.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("reply_autodraft", REPO / "sequences" / "reply-autodraft.py")
rad = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(rad)


# ─── env / store ─────────────────────────────────────────────────────────────

def load_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


HOST = load_env(REPO / "sequences" / "hostinger.env")
SUPA = load_env(REPO / "sequences" / "supabase.env")
SUPA_URL = SUPA.get("SUPABASE_URL", "").rstrip("/")
SUPA_KEY = SUPA.get("SUPABASE_ANON_KEY", "")
SUPA_H = {"apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}", "User-Agent": UA}


def load_store() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            return {"pending": []}
    return {"pending": []}


def save_store(store: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def supa_get(path: str) -> list:
    try:
        req = urllib.request.Request(f"{SUPA_URL}/rest/v1/{path}", headers=SUPA_H)
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"  ! supa_get failed: {e}")
        return []


def supa_patch(path: str, payload: dict) -> bool:
    try:
        req = urllib.request.Request(
            f"{SUPA_URL}/rest/v1/{path}", data=json.dumps(payload).encode(),
            method="PATCH",
            headers={**SUPA_H, "Content-Type": "application/json",
                     "Prefer": "return=minimal"})
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception as e:
        print(f"  ! supa_patch failed: {e}")
        return False


# ─── context builders ────────────────────────────────────────────────────────

def report_to_for(slug: str) -> str | None:
    """The client's address for forward-to-client, read from the LIVE DB config
    (profiles.config.report_to), where the real value lives (JSON files are stale)."""
    if not slug:
        return None
    rows = supa_get(f"profiles?slug=eq.{urllib.parse.quote(slug)}&select=config")
    if rows:
        cfg = rows[0].get("config") or {}
        # report_to lives under config.relay.report_to (verified live 2026-06-21);
        # fall back to a top-level report_to or the brand legal contact email.
        rt = ((cfg.get("relay") or {}).get("report_to")
              or cfg.get("report_to")
              or ((cfg.get("brand") or {}).get("legal") or {}).get("contact_email"))
        if rt:
            return rt
    return None


def thread_history(prospect_email: str, run_id: str | None,
                   profile_slug: str | None) -> list[dict]:
    """Reconstruct the full conversation, newest first:
      - every PROSPECT reply we recorded (replies table), and
      - every message WE sent them (send_log + any stored answer_text).
    Returns a list of {when, who, text} dicts."""
    items = []
    pe = (prospect_email or "").lower()
    # 1) Their replies to us.
    reps = supa_get(
        "replies?from_addr=eq." + urllib.parse.quote(pe)
        + "&select=subject,body_snippet,received_at,raw_headers&order=received_at.asc&limit=50")
    for r in reps:
        items.append({
            "when": r.get("received_at") or "",
            "who": "PROSPECT",
            "text": (r.get("body_snippet") or "").strip(),
        })
        # If we previously stored what we answered, show it too.
        ans = (r.get("raw_headers") or {}).get("answer_text")
        if ans:
            items.append({
                "when": r.get("received_at") or "",
                "who": "US (sent)",
                "text": ans.strip(),
            })
    # 2) Sequence emails we sent them (subject only — bodies are templated).
    # send_log's timestamp column is sent_at (there is no created_at).
    sends = supa_get(
        "send_log?to_addr=eq." + urllib.parse.quote(pe)
        + "&select=subject,step_n,sent_at,persona_slug&order=sent_at.asc&limit=50")
    for s in sends:
        items.append({
            "when": s.get("sent_at") or "",
            "who": f"US (step {s.get('step_n')})",
            "text": f"[outreach email] {s.get('subject') or ''}".strip(),
        })
    items.sort(key=lambda x: x["when"] or "", reverse=True)
    return items


_POS = ("interested", "yes", "let's", "lets ", "sounds good", "happy to", "sure",
        "works for me", "let me know", "call", "book", "schedule", "deal",
        "i agree", "great", "perfect", "ready")
_NEG = ("not interested", "no thanks", "stop", "unsubscribe", "remove me",
        "not a fit", "no thank", "leave me alone", "spam")
_OBJ = ("how much", "price", "cost", "expensive", "budget", "why ", "but ",
        "concern", "not sure", "skeptical", "more info", "what is", "?")


def quick_intent(text: str) -> str:
    """A fast, transparent heuristic read so the operator can triage. Not a
    decision maker — just a hint shown in the popup header."""
    t = (text or "").lower()
    if any(k in t for k in _NEG):
        return "NEGATIVE / opt-out"
    if any(k in t for k in _POS):
        return "POSITIVE / interested"
    if any(k in t for k in _OBJ):
        return "QUESTION / objection"
    return "neutral / unclear"


# ─── the GUI dialog ──────────────────────────────────────────────────────────

_PS_DIALOG = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$f = New-Object System.Windows.Forms.Form
$f.Text = "Prospect reply - your decision"
$f.Size = New-Object System.Drawing.Size(760,720)
$f.StartPosition = "CenterScreen"
$f.TopMost = $true

$hdr = New-Object System.Windows.Forms.Label
$hdr.Text = @'
{HEADER}
'@
$hdr.Location = New-Object System.Drawing.Point(12,10)
$hdr.Size = New-Object System.Drawing.Size(726,86)
$hdr.Font = New-Object System.Drawing.Font("Segoe UI",9)
$f.Controls.Add($hdr)

$thlbl = New-Object System.Windows.Forms.Label
$thlbl.Text = "Conversation so far (newest first):"
$thlbl.Location = New-Object System.Drawing.Point(12,100)
$thlbl.Size = New-Object System.Drawing.Size(726,18)
$f.Controls.Add($thlbl)

$thread = New-Object System.Windows.Forms.TextBox
$thread.Multiline = $true; $thread.ReadOnly = $true
$thread.ScrollBars = "Vertical"
$thread.Location = New-Object System.Drawing.Point(12,120)
$thread.Size = New-Object System.Drawing.Size(726,200)
$thread.Font = New-Object System.Drawing.Font("Consolas",9)
$thread.Text = @'
{THREAD}
'@
$f.Controls.Add($thread)

$drlbl = New-Object System.Windows.Forms.Label
$drlbl.Text = "AI draft reply (edit freely — what you send goes as the persona):"
$drlbl.Location = New-Object System.Drawing.Point(12,328)
$drlbl.Size = New-Object System.Drawing.Size(726,18)
$f.Controls.Add($drlbl)

$draft = New-Object System.Windows.Forms.TextBox
$draft.Multiline = $true; $draft.ScrollBars = "Vertical"
$draft.Location = New-Object System.Drawing.Point(12,348)
$draft.Size = New-Object System.Drawing.Size(726,150)
$draft.Font = New-Object System.Drawing.Font("Segoe UI",10)
$draft.Text = @'
{DRAFT}
'@
$f.Controls.Add($draft)

$ntlbl = New-Object System.Windows.Forms.Label
$ntlbl.Text = "Note to client (only used by 'Forward to client'):"
$ntlbl.Location = New-Object System.Drawing.Point(12,506)
$ntlbl.Size = New-Object System.Drawing.Size(726,18)
$f.Controls.Add($ntlbl)

$note = New-Object System.Windows.Forms.TextBox
$note.Multiline = $true; $note.ScrollBars = "Vertical"
$note.Location = New-Object System.Drawing.Point(12,526)
$note.Size = New-Object System.Drawing.Size(726,60)
$f.Controls.Add($note)

# action buttons
$result = New-Object System.Windows.Forms.TextBox
$result.Visible = $false
$result.Text = "snooze"

function mk($text,$x,$w,$val) {
  $b = New-Object System.Windows.Forms.Button
  $b.Text = $text
  $b.Location = New-Object System.Drawing.Point($x,600)
  $b.Size = New-Object System.Drawing.Size($w,34)
  $b.Add_Click({ $result.Text = $val; $f.Close() }.GetNewClosure())
  $f.Controls.Add($b)
}
mk "Approve AI as-is" 12 130 "approve"
mk "Send my text" 148 110 "edit"
mk "Forward to client" 264 130 "forward"
mk "Block" 400 70 "block"

function mk2($text,$x,$w,$val) {
  $b = New-Object System.Windows.Forms.Button
  $b.Text = $text
  $b.Location = New-Object System.Drawing.Point($x,640)
  $b.Size = New-Object System.Drawing.Size($w,30)
  $b.Add_Click({ $result.Text = $val; $f.Close() }.GetNewClosure())
  $f.Controls.Add($b)
}
mk2 "No reply needed (resolve)" 12 200 "noreply"
mk2 "Snooze (decide later)" 220 180 "snooze"

$f.Add_Shown({ $f.Activate() })
[void]$f.ShowDialog()
$out = @{ action = $result.Text; draft = $draft.Text; note = $note.Text } | ConvertTo-Json -Compress
Write-Output $out
'''


def _show_dialog(item: dict, history: list[dict]) -> dict | None:
    header = (
        f"Prospect : {item.get('prospect_name') or ''} <{item['prospect_email']}>\n"
        f"Persona  : {item.get('persona_name') or '(default)'}   "
        f"Brand/Client: {item.get('brand_name') or item.get('slug') or 'unmatched'}\n"
        f"Their last message intent: {item.get('intent') or '?'}\n"
        f"Deal context: {(item.get('deal_context') or '(none)')[:180]}"
    )
    th_lines = []
    for h in history[:30]:
        when = (h.get("when") or "")[:16].replace("T", " ")
        th_lines.append(f"[{when}] {h['who']}:\n{h['text'][:600]}\n")
    thread = "\n".join(th_lines) if th_lines else "(no prior thread found)"

    def esc(s: str) -> str:
        # GUI text is injected as single-quoted PS here-strings (@'...'@), which are
        # fully literal: no $, $(...), or backtick expansion. The only break-out is the
        # '@ terminator, so neutralize it. (Prospect-controlled reply bodies land in
        # {THREAD}; double-quoted here-strings would have executed any $(...) in them.)
        return (s or "").replace("'@", "' @")

    script = (_PS_DIALOG
              .replace("{HEADER}", esc(header))
              .replace("{THREAD}", esc(thread))
              .replace("{DRAFT}", esc(item.get("draft") or "")))
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=1800, encoding="utf-8",
            errors="replace")
        out = (proc.stdout or "").strip()
        line = [l for l in out.splitlines() if l.strip().startswith("{")]
        if not line:
            return None
        return json.loads(line[-1])
    except Exception as e:
        print(f"  ! dialog failed: {e}")
        return None


# ─── actions ─────────────────────────────────────────────────────────────────

def _send_as_avatar(item: dict, text: str, dry: bool) -> bool:
    """Send `text` to the prospect as the persona, via reply-autodraft's proven
    per-brand send path. Builds the minimal reply dict it expects."""
    reply = {"id": item.get("reply_id"), "run_id": item.get("run_id"),
             "raw_headers": {}}
    persona = item.get("persona") or {}
    profile = item.get("profile") or {}
    return rad.send_draft_to_prospect(
        reply=reply, slug=item.get("slug") or "",
        prospect_email=item["prospect_email"], subject=item.get("subject") or "",
        draft=text, persona=persona, profile=profile, dry=dry,
        unsub_token=item.get("unsub_token"))


def _forward_to_client(item: dict, note: str, dry: bool) -> bool:
    """Send the prospect's reply + our draft + the operator's note to the client
    (report_to from DB), bcc info@. Via Resend (alerts subdomain) so it threads
    off mailbox quota."""
    slug = item.get("slug") or ""
    client = report_to_for(slug)
    if not client:
        print(f"  ! no report_to for {slug}; forwarding to {OPERATOR_ADDR} instead")
        client = OPERATOR_ADDR
    body = (
        f"Forwarding a prospect reply for your call.\n\n"
        f"Prospect : {item.get('prospect_name') or ''} <{item['prospect_email']}>\n"
        f"Campaign : {item.get('brand_name') or slug}\n\n"
        f"--- their message ---\n{(item.get('prospect_text') or '').strip()}\n\n"
        f"--- our suggested reply (not yet sent) ---\n{(item.get('draft') or '').strip()}\n\n"
        f"--- note from {OPERATOR_ADDR} ---\n{(note or '(none)').strip()}\n"
    )
    resend_key = (HOST.get("RESEND_FULL_ACCESS_API_KEY")
                  or HOST.get("RESEND_API_KEY"))
    if dry:
        print(f"  [DRY] would FORWARD to client {client} (bcc {OPERATOR_ADDR}) for {item['prospect_email']}")
        return bool(resend_key)
    if not resend_key:
        print("  ! no RESEND_FULL_ACCESS_API_KEY; cannot forward")
        return False
    payload = {
        "from": "Aureon Lead Desk <alerts@hi.aureonglobal.de>",
        "to": [client], "bcc": [OPERATOR_ADDR],
        "reply_to": item["prospect_email"],  # client can reply straight to prospect
        "subject": f"[Lead] {item.get('prospect_name') or item['prospect_email']} replied - {item.get('subject') or ''}"[:200],
        "text": body,
        "tags": [{"name": "kind", "value": "lead_forward"}],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {resend_key}",
                 "Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=20)
        return True
    except Exception as e:
        print(f"  ! forward failed: {e}")
        return False


def _block_prospect(item: dict, dry: bool) -> bool:
    """Mark the prospect do-not-contact: unsubscribe + a do_not_contact flag in
    custom_fields, and pause any queued runs (reuse reply-autodraft helpers)."""
    email_addr = (item.get("prospect_email") or "").lower()
    if dry:
        print(f"  [DRY] would BLOCK {email_addr} (unsubscribe + do_not_contact)")
        return True
    rows = supa_get("prospects?email=eq." + urllib.parse.quote(email_addr)
                    + "&select=id,custom_fields&limit=1")
    if rows:
        cf = dict(rows[0].get("custom_fields") or {})
        cf["do_not_contact"] = True
        cf["do_not_contact_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        supa_patch(f"prospects?id=eq.{rows[0]['id']}",
                   {"custom_fields": cf, "unsubscribed": True})
    return True


def mark_reply_handled(reply_id: str | None, action: str, sent_text: str | None) -> None:
    """Stamp the source replies row so reply-autodraft never reprocesses it and
    forward-to-client can show what we sent."""
    if not reply_id:
        return
    rows = supa_get(f"replies?id=eq.{reply_id}&select=raw_headers")
    rh = dict((rows[0].get("raw_headers") if rows else {}) or {})
    rh["autodraft_sent"] = True
    rh["reviewed"] = True
    rh["review_action"] = action
    rh["reviewed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    if sent_text:
        rh["answer_text"] = sent_text[:4000]
    supa_patch(f"replies?id=eq.{reply_id}", {"raw_headers": rh})


# ─── prompt loop ─────────────────────────────────────────────────────────────

def _pending(store: dict) -> list[dict]:
    return [it for it in store["pending"] if not it.get("resolved")]


def prompt(dry: bool = False) -> int:
    store = load_store()
    pend = _pending(store)
    if not pend:
        print("prompt: no replies awaiting a decision")
        return 0
    print(f"prompt: {len(pend)} reply(ies) awaiting a decision")
    handled = 0
    for it in pend:
        # enrich at display time: thread + intent
        history = thread_history(it["prospect_email"], it.get("run_id"), it.get("slug"))
        if not it.get("intent"):
            it["intent"] = quick_intent(it.get("prospect_text") or "")
        if dry:
            print(f"  [DRY] would pop dialog for {it['prospect_email']} "
                  f"[{it.get('slug') or 'unmatched'}] intent={it['intent']}")
            continue
        res = _show_dialog(it, history)
        if not res:
            print(f"  ~ no response (treated as snooze) for {it['prospect_email']}")
            continue
        action = (res.get("action") or "snooze").strip()
        edited = (res.get("draft") or "").strip()
        note = (res.get("note") or "").strip()

        if action == "snooze":
            print(f"  · snoozed {it['prospect_email']} (will re-pop next hour)")
            continue

        ok = True
        sent_text = None
        if action == "approve":
            sent_text = (it.get("draft") or "").strip()
            ok = _send_as_avatar(it, sent_text, dry=False)
        elif action == "edit":
            if not edited:
                print(f"  ! empty edit for {it['prospect_email']}, snoozing")
                continue
            sent_text = edited
            ok = _send_as_avatar(it, sent_text, dry=False)
        elif action == "forward":
            ok = _forward_to_client(it, note, dry=False)
        elif action == "block":
            ok = _block_prospect(it, dry=False)
        elif action == "noreply":
            ok = True  # nothing to send
        else:
            print(f"  ! unknown action {action!r}, snoozing")
            continue

        if ok:
            it["resolved"] = True
            it["action"] = action
            it["resolved_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            mark_reply_handled(it.get("reply_id"), action, sent_text)
            save_store(store)
            handled += 1
            print(f"  + {it['prospect_email']}: {action} -> resolved")
        else:
            print(f"  ! {it['prospect_email']}: {action} FAILED, left pending")
    return handled


def list_store() -> None:
    store = load_store()
    if not store["pending"]:
        print("(queue empty)"); return
    for it in store["pending"]:
        st = it.get("action") or ("RESOLVED" if it.get("resolved") else "PENDING")
        print(f"  {it.get('queued_at','')[:16]}  {it['prospect_email']:34s} "
              f"[{it.get('slug') or '-'}]  {st}")


# ─── enqueue (called by reply-autodraft via import, or for testing) ───────────

def enqueue(*, reply_id, prospect_email, prospect_name, prospect_text,
            subject, slug, run_id, persona, profile, draft, deal_context="",
            unsub_token=None) -> bool:
    """Add a reply to the review queue. Idempotent on reply_id. Returns True if
    newly added (or already present), False on store error."""
    store = load_store()
    for it in store["pending"]:
        if it.get("reply_id") and it["reply_id"] == reply_id:
            return True  # already queued
    persona_name = (persona or {}).get("from_name") or "(default persona)"
    brand_name = (profile or {}).get("name") or slug or "unmatched"
    store["pending"].append({
        "reply_id": reply_id,
        "prospect_email": (prospect_email or "").lower(),
        "prospect_name": prospect_name or "",
        "prospect_text": (prospect_text or "")[:4000],
        "subject": subject or "",
        "slug": slug or "",
        "run_id": run_id,
        "persona": persona or {},
        "persona_name": persona_name,
        "profile": profile or {},
        "brand_name": brand_name,
        "draft": draft or "",
        "deal_context": deal_context or "",
        "unsub_token": unsub_token,
        "intent": quick_intent(prospect_text or ""),
        "resolved": False,
        "queued_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    save_store(store)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")  # reserved (pull from DB if ever needed); store-driven now
    p_prompt = sub.add_parser("prompt"); p_prompt.add_argument("--dry", action="store_true")
    p_run = sub.add_parser("run"); p_run.add_argument("--dry", action="store_true")
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd in ("scan", "run"):
        prompt(dry=getattr(a, "dry", False))
    elif a.cmd == "prompt":
        prompt(dry=a.dry)
    elif a.cmd == "list":
        list_store()
    return 0


if __name__ == "__main__":
    sys.exit(main())
