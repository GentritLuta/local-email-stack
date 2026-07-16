# -*- coding: utf-8 -*-
"""creator-signup-notify.py, route new creator-program signups to the client.

A creator fills the AlgoAlpha signup capture page (docs/algoalpha-signup.html ->
gentritluta.github.io/local-email-stack/signup/algoalpha.html). The page writes a
row straight into Supabase `creator_signups` (anon insert, same pattern as the
home-value funnel). This poller picks up un-notified rows and emails the signup to
the client's inbox (profile relay.report_to), with Reply-To set to the creator so
the client can reply and onboard them directly. info@ is blind-copied for
visibility, exactly like the forwarded-lead handoff. Then it marks the row
notified so it never double-sends.

    py creator-signup-notify.py once
    py creator-signup-notify.py once --dry
    py creator-signup-notify.py once --to info@aureonglobal.de   # test override
"""
from __future__ import annotations
import argparse, json, ssl, smtplib, sys, urllib.request
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from mailer import send as send_mail   # Resend primary (VPS blocks SMTP), SMTP fallback
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT = "zmzolkijhiaedzcmdfji"
OPERATOR_ADDR = "info@aureonglobal.de"


def _env(path: Path) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); out[k.strip()] = v.strip().strip('"').strip("'")
    return out


SENV = _env(REPO / "sequences" / "supabase.env")
HENV = _env(REPO / "sequences" / "hostinger.env")
_TOK = SENV["SUPABASE_ACCESS_TOKEN"]


def mq(sql: str):
    rq = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{PROJECT}/database/query",
        data=json.dumps({"query": sql}).encode(), method="POST",
        headers={"Authorization": f"Bearer {_TOK}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 Chrome/123"})
    return json.loads(urllib.request.urlopen(rq, timeout=60).read().decode())


def _q(s: str) -> str:
    return (s or "").replace("'", "''")


def client_email_for(slug: str) -> str | None:
    """The client's inbox for this profile = relay.report_to (same source the
    forward-replies handoff uses). Falls back to the brand contact email."""
    pf = REPO / "profiles" / f"{slug}.json"
    if not pf.exists():
        return None
    try:
        p = json.loads(pf.read_text(encoding="utf-8"))
    except Exception:
        return None
    return ((p.get("relay") or {}).get("report_to") or p.get("report_to")
            or ((p.get("brand") or {}).get("legal") or {}).get("contact_email"))


def build_email(sig: dict) -> tuple[str, str, str]:
    """Return (subject, text_body, reply_to=creator) for a signup notification."""
    creator = (sig.get("email") or "").strip()
    name = sig.get("channel_name") or "(no name)"
    lines = [
        "A creator just signed up through the AlgoAlpha Creator Program page.",
        "",
        f"Channel:   {name}",
        f"Link:      {sig.get('channel_url') or '-'}",
        f"Platform:  {sig.get('platform') or '-'}",
        f"Niche:     {sig.get('niche') or '-'}",
        f"Audience:  {sig.get('audience') or '-'}",
        f"Email:     {creator or '-'}",
        f"Telegram:  {sig.get('telegram') or '-'}",
        f"Payout:    {sig.get('payout_method') or '-'}",
    ]
    if (sig.get("notes") or "").strip():
        lines += ["", "Notes:", sig["notes"].strip()]
    lines += [
        "", "-" * 48,
        f">> Just hit Reply to reach {name} directly (Reply-To is the creator). "
        "Confirm their per-video number and walk them into signup.",
    ]
    return f"[AlgoAlpha signup] {name}"[:200], "\n".join(lines), creator


def once(limit: int, dry: bool, to_override: str | None) -> dict:
    rows = mq(f"""select id, profile_slug, channel_name, channel_url, platform, email,
                    audience, niche, payout_method, telegram, notes
                  from creator_signups
                  where notified = false
                  order by created_at asc limit {int(limit)}""")
    stats = {"pending": len(rows), "sent": 0, "skipped_no_client": 0, "errors": 0}
    if not rows:
        print("=== creator-signup-notify === no un-notified signups"); return stats

    for s in rows:
        slug = s.get("profile_slug") or "algoalpha"
        client_email = to_override or client_email_for(slug)
        if not client_email:
            print(f"  ! no client inbox for profile {slug}, skipping {s.get('channel_name')}")
            stats["skipped_no_client"] += 1
            continue
        if dry:
            print(f"  [DRY] would notify {client_email} of signup: "
                  f"{s.get('channel_name')} ({s.get('email')})  Reply-To={s.get('email')}")
            stats["sent"] += 1
            continue
        subject, text, creator = build_email(s)
        # info@ blind-copied for visibility (Resend bcc is blind to the client).
        bcc = [OPERATOR_ADDR] if OPERATOR_ADDR.lower() != client_email.lower() else None
        if send_mail(to=client_email, subject=subject, text=text, reply_to=(creator or None),
                     from_addr="AUREON Campaign <info@send.aureonglobal.de>", bcc=bcc):
            mq(f"update creator_signups set notified = true where id = '{_q(s['id'])}'")
            print(f"  -> notified {client_email} of signup {s.get('channel_name')}")
            stats["sent"] += 1
        else:
            print(f"  ! send failed ({s.get('channel_name')})")
            stats["errors"] += 1

    print(f"=== creator-signup-notify === {json.dumps(stats)}")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="once")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--to", default=None, help="override client recipient (testing)")
    a = ap.parse_args()
    once(a.limit, a.dry, a.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
