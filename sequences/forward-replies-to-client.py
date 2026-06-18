# -*- coding: utf-8 -*-
"""forward-replies-to-client.py — forward every genuine campaign reply (and any
reply-to-the-reply in the thread) to the respective CLIENT's email.

Each reply row in `replies` carries a `profile_slug` (resolved authoritatively
from the prospect). Each profile has a `report_to` = the client's email. This
script finds class='reply' rows not yet forwarded, looks up the client email for
their profile, forwards the reply (from, subject, body) to that client via
Hostinger SMTP (from info@aureonglobal.de, reply-to the prospect so the client
can answer directly), and marks the row forwarded so it never double-sends.

Thread continuations ("reply to the reply") are also class='reply' (imap-poll
classifies any In-Reply-To/References message as a reply), so the whole back-and-
forth gets forwarded as it arrives.

    py forward-replies-to-client.py once
    py forward-replies-to-client.py once --dry
"""
from __future__ import annotations
import argparse, json, ssl, smtplib, sys, datetime as dt
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import urllib.request, urllib.parse

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _load_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); out[k.strip()] = v.strip().strip('"').strip("'")
    return out


SENV = _load_env(REPO / "sequences" / "supabase.env")
HENV = _load_env(REPO / "sequences" / "hostinger.env")
URL = SENV["SUPABASE_URL"].rstrip("/")
KEY = SENV["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "User-Agent": "les-fwd/1.0"}
OPERATOR_ADDR = "info@aureonglobal.de"
# Wait up to this long for reply-autodraft (every 15 min) to auto-send + store the
# answer, so the client gets the prospect's reply AND our response in one email.
# After this, forward reply-only so a never-answered reply is never stuck.
FORWARD_GRACE_MIN = 90


def supa_get(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=40).read())


def supa_patch(path: str, body: dict) -> None:
    req = urllib.request.Request(
        f"{URL}/rest/v1/{path}", data=json.dumps(body).encode(), method="PATCH",
        headers={**H, "Content-Type": "application/json", "Prefer": "return=minimal"})
    urllib.request.urlopen(req, timeout=30)


def client_email_for_profile(slug: str) -> str | None:
    """The client's inbox for this profile = relay.report_to (falls back to the
    brand contact email). report_to is where client-facing mail already goes."""
    pf = REPO / "profiles" / f"{slug}.json"
    if not pf.exists():
        return None
    p = json.loads(pf.read_text(encoding="utf-8"))
    rt = (p.get("relay") or {}).get("report_to") or p.get("report_to")
    if rt:
        return rt
    return ((p.get("brand") or {}).get("legal") or {}).get("contact_email")


def forward(reply: dict, client_email: str, dry: bool, answer: str | None = None) -> bool:
    user = HENV.get("SMTP_USER") or OPERATOR_ADDR
    pw = HENV.get("SMTP_PASS")
    if not pw:
        print("  ! no SMTP_PASS — cannot forward"); return False
    prospect = reply.get("from_addr") or "(unknown)"
    subject = reply.get("subject") or "(no subject)"
    body = reply.get("body_snippet") or "(no body captured)"
    answer = (answer or "").strip()
    fwd_subject = subject if subject.lower().startswith(("re:", "fwd:")) else f"Re: {subject}"

    intro = (f"A prospect replied in your AUREON campaign"
             + (", and we already did the groundwork and answered on your behalf (below)." if answer
                else ".") + "\n"
             f"From: {prospect}\nSubject: {subject}\n\n"
             f">> This lead is yours to close. Just hit Reply on this email and your\n"
             f"   message goes straight to {prospect} — not back to us, not to any\n"
             f"   sending address. You are talking to the prospect directly from here.\n"
             f"{'-'*48}\n\n")
    # Show the prospect's reply AND the answer we sent, so the client has the full
    # exchange and can act on the sale. 2026-06-16.
    text = intro + "PROSPECT WROTE:\n\n" + body
    if answer:
        text += ("\n\n" + "-" * 48 + "\n"
                 "OUR REPLY (already sent to the prospect on your behalf):\n\n" + answer + "\n")
    if dry:
        tag = "reply+answer" if answer else "reply only"
        print(f"  [DRY] would forward {tag} from {prospect} -> client {client_email}")
        return True
    m = MIMEMultipart("alternative")
    m["Subject"] = f"[Campaign reply] {fwd_subject}"[:200]
    m["From"] = f"AUREON Campaign <{user}>"
    m["To"] = client_email
    m["Reply-To"] = prospect      # client hits Reply -> goes straight to the prospect
    m.attach(MIMEText(text, "plain", "utf-8"))
    # info@ keeps a silent copy of the handoff for visibility. Delivered via the
    # envelope recipient list, NOT a Bcc header, so it stays blind to the client
    # (m.as_string() would otherwise serialise a Bcc header into their copy).
    envelope = [client_email]
    if OPERATOR_ADDR.lower() != client_email.lower():
        envelope.append(OPERATOR_ADDR)
    try:
        with smtplib.SMTP_SSL("smtp.hostinger.com", 465, context=ssl.create_default_context()) as s:
            s.login(user, pw)
            s.sendmail(user, envelope, m.as_string())
        print(f"  -> forwarded reply from {prospect} to {client_email}")
        return True
    except Exception as e:
        print(f"  ! forward failed ({prospect} -> {client_email}): {e}")
        return False


def once(limit: int, dry: bool) -> dict:
    # genuine prospect replies from the last 30 days not yet forwarded
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
    rows = supa_get(
        f"replies?class=eq.reply&received_at=gte.{urllib.parse.quote(since)}"
        f"&select=id,profile_slug,from_addr,to_addr,subject,body_snippet,raw_headers,received_at"
        f"&order=received_at.desc&limit={limit}")
    stats = {"candidates": 0, "forwarded": 0, "skipped_no_client": 0,
             "already": 0, "errors": 0, "waiting_answer": 0}
    client_cache: dict[str, str | None] = {}
    for r in rows:
        rh = r.get("raw_headers") or {}
        if isinstance(rh, str):
            try: rh = json.loads(rh)
            except Exception: rh = {}
        if rh.get("client_forwarded"):
            stats["already"] += 1
            continue
        stats["candidates"] += 1
        slug = r.get("profile_slug")
        if not slug:
            # cannot route without a profile; skip (and mark so we don't re-eval forever)
            stats["skipped_no_client"] += 1
            if not dry:
                supa_patch(f"replies?id=eq.{r['id']}",
                           {"raw_headers": {**rh, "client_forwarded": "skip_no_profile"}})
            continue
        if slug not in client_cache:
            client_cache[slug] = client_email_for_profile(slug)
        client_email = client_cache[slug]
        # don't forward to our own operator inbox (aureon's report_to IS info@) —
        # those replies are handled by reply-autodraft/seller-outreach already.
        if not client_email or client_email.lower() == OPERATOR_ADDR.lower():
            stats["skipped_no_client"] += 1
            if not dry:
                supa_patch(f"replies?id=eq.{r['id']}",
                           {"raw_headers": {**rh, "client_forwarded": "skip_operator_or_none"}})
            continue
        # Wait briefly for the auto-reply so the client gets reply+answer together.
        # reply-autodraft stores raw_headers.answer_text when it auto-sends. If the
        # reply isn't answered yet and is still recent, defer to the next run; once
        # it's older than the grace window, forward reply-only so nothing is stuck.
        answer = rh.get("answer_text")
        answered = bool(answer) or bool(rh.get("autosent")) or bool(rh.get("autoreply_sent"))
        if not answered:
            try:
                recv = dt.datetime.fromisoformat((r.get("received_at") or "").replace("Z", "+00:00"))
                age_min = (dt.datetime.now(dt.timezone.utc) - recv).total_seconds() / 60
            except Exception:
                age_min = 1e9
            if age_min < FORWARD_GRACE_MIN:
                stats["waiting_answer"] += 1
                continue  # leave unmarked; next run forwards it (ideally with the answer)
        ok = forward(r, client_email, dry, answer=answer)
        if ok:
            stats["forwarded"] += 1
            if not dry:
                supa_patch(f"replies?id=eq.{r['id']}", {"raw_headers": {
                    **rh, "client_forwarded": True,
                    "client_forwarded_to": client_email,
                    "client_forwarded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "client_forwarded_with_answer": bool(answer)}})
        else:
            stats["errors"] += 1
    print(f"=== forward-replies-to-client === {json.dumps(stats)}")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    p = sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("once"); o.add_argument("--limit", type=int, default=200); o.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if args.cmd == "once":
        once(args.limit, args.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
