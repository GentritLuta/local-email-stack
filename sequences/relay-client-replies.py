# -*- coding: utf-8 -*-
"""relay-client-replies.py — relay a CLIENT's reply onward to the prospect.

Gap this closes: when we forward a lead, the email is From info@aureonglobal.de
with Reply-To=<prospect>. Clients (especially AI assistants like AlgoAlpha's
"Clara") often reply to the From (info@) instead of the Reply-To, so their
message dead-ends in info@ and the prospect never hears back. This finds those
client replies and sends the client's message to the prospect FROM the persona
that originally emailed them, continuing the real thread.

Deterministic match: forward-replies-to-client.py stamps the forward subject
with [Campaign reply #<token>] (the prospect reply id, dashless first 10). The
client reply quotes that subject, so we extract the token and look up the exact
prospect thread. Older forwards without a token fall back to the quoted subject.

SAFETY: skips messages clearly addressed to US, not the prospect (a client/AI
asking "paste the prospect's message" / "I need the prospect reply"), so
confused AI output is never relayed onward. Idempotent via raw_headers.relayed.

  py relay-client-replies.py            # DRY: print what it would relay
  py relay-client-replies.py --live     # actually send to prospects
"""
from __future__ import annotations
import argparse, json, re, ssl, smtplib, sys, urllib.request
from email.mime.text import MIMEText
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OPERATOR_ADDR = "info@aureonglobal.de"


def load_env(p: Path) -> dict:
    d = {}
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("\r")
    return d


HOST = load_env(REPO / "sequences" / "hostinger.env")
ENVS = load_env(REPO / "sequences" / "supabase.env")
TOK = ENVS["SUPABASE_ACCESS_TOKEN"]


def mq(sql: str):
    rq = urllib.request.Request(
        "https://api.supabase.com/v1/projects/ccmqkljsjiuavpydbkva/database/query",
        data=json.dumps({"query": sql}).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 Chrome/123"})
    body = urllib.request.urlopen(rq, timeout=60).read().decode()
    return json.loads(body) if body.strip() else []


# Clearly-not-for-the-prospect content (a client/AI talking to US). Never relay these.
_TO_US_RX = re.compile(
    r"(paste (their|the prospect)|forward the email|i (still )?need the prospect|"
    r"need the prospect'?s (actual )?(message|reply)|send (it|the prospect'?s)|"
    r"what('?s| is) the prospect)", re.I)


def client_addresses() -> dict:
    """report_to per profile from the DB profiles (or fall back to disk)."""
    out = {}
    for slug in [p["slug"] for p in mq("select slug from profiles")]:
        f = REPO / "profiles" / f"{slug}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        rt = (d.get("relay") or {}).get("report_to") or d.get("report_to")
        if rt and rt.lower() != OPERATOR_ADDR:
            out[rt.lower()] = slug
    return out


def top_message(snippet: str) -> str:
    """The client's new text, before any quoted history."""
    s = (snippet or "").replace("\r", "")
    for marker in [r"\nOn .*wrote:", r"\nEl .*escrib", r"\n_{5,}", r"\nFrom: ", r"\n>{1,}"]:
        m = re.search(marker, s)
        if m:
            s = s[:m.start()]
    return s.strip()


def find_prospect(subject: str, client_slug: str):
    """The forwarded prospect reply this client message is about. Token first, then subject."""
    m = re.search(r"#([0-9a-f]{6,12})", subject or "")
    if m:
        tok = m.group(1)
        rows = mq(f"""select id, from_addr, run_id, profile_slug, subject from replies
                      where profile_slug='{client_slug}' and class='reply'
                      and replace(id::text,'-','') like '{tok}%' limit 1""")
        if rows:
            return rows[0]
    # fallback: strip our prefix and match the original "Re: <subject>"
    orig = re.sub(r"^\s*(re:\s*)?\[campaign reply[^\]]*\]\s*", "", subject or "", flags=re.I).strip()
    if orig:
        safe = orig.replace("'", "''")[:80]
        rows = mq(f"""select id, from_addr, run_id, profile_slug, subject from replies
                      where profile_slug='{client_slug}' and class='reply'
                      and subject ilike '%{safe}%' order by received_at desc limit 1""")
        if rows:
            return rows[0]
    return None


def persona_from(run_id: str | None) -> str | None:
    if not run_id:
        return None
    rows = mq(f"select from_addr from send_log where run_id='{run_id}' order by step_n asc limit 1")
    return rows[0]["from_addr"] if rows else None


def brand_resend_key(slug: str) -> str:
    f = REPO / "profiles" / f"{slug}.json"
    if f.exists():
        return (json.loads(f.read_text(encoding="utf-8")).get("relay") or {}).get("resend_api_key") or ""
    return ""


def relay_send(slug: str, persona_addr: str, prospect: str, subject: str, text: str) -> bool:
    """Send the client's message to the prospect FROM the persona. aureon -> Hostinger
    info@, every other brand -> its own Resend relay from the persona address."""
    subj = subject if (subject or "").lower().startswith("re:") else f"Re: {subject}"
    if slug == "aureon":
        user, pw = HOST.get("SMTP_USER") or OPERATOR_ADDR, HOST.get("SMTP_PASS")
        if not pw:
            print("  ! no SMTP_PASS — cannot relay"); return False
        m = MIMEText(text, "plain", "utf-8")
        m["Subject"], m["From"], m["To"], m["Reply-To"] = subj[:200], f"Aureon <{user}>", prospect, user
        try:
            with smtplib.SMTP_SSL("smtp.hostinger.com", 465, context=ssl.create_default_context()) as s:
                s.login(user, pw); s.sendmail(user, [prospect], m.as_string())
            return True
        except Exception as e:
            print(f"  ! relay send failed: {e}"); return False
    key = brand_resend_key(slug)
    if not (persona_addr and key):
        print(f"  ! {slug}: missing persona sender or resend key — cannot relay"); return False
    payload = {"from": persona_addr, "to": [prospect], "subject": subj[:200], "text": text}
    rq = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(),
                                method="POST", headers={"Authorization": f"Bearer {key}",
                                                        "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(rq, timeout=30).read()
        return True
    except Exception as e:
        print(f"  ! {slug} resend relay failed: {e}"); return False


def mark_relayed(reply_id: str):
    mq(f"""update replies set raw_headers = coalesce(raw_headers,'{{}}'::jsonb)
           || '{{"relayed_to_prospect":"yes"}}'::jsonb where id='{reply_id}'""")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="actually send (default is dry)")
    ap.add_argument("--days", type=int, default=21)
    a = ap.parse_args()
    dry = not a.live

    clients = client_addresses()
    inlist = "','".join(clients.keys())
    rows = mq(f"""select id, from_addr, subject, body_snippet, received_at, raw_headers
                  from replies
                  where lower(from_addr) in ('{inlist}')
                  and subject ilike '%[Campaign reply%'
                  and received_at >= now() - interval '{a.days} days'
                  and coalesce(raw_headers->>'relayed_to_prospect','') = ''
                  order by received_at desc""")
    stats = {"relayed": 0, "skipped_to_us": 0, "no_match": 0, "no_text": 0}
    print(f"client replies to evaluate: {len(rows)}  ({'DRY' if dry else 'LIVE'})\n")
    for r in rows:
        client_slug = clients.get((r["from_addr"] or "").lower(), "?")
        msg = top_message(r.get("body_snippet") or "")
        if not msg:
            stats["no_text"] += 1; continue
        # A genuine reply to the creator never calls them "the prospect" — any such
        # mention means the message is meta (the client/AI talking to US), so skip.
        if "prospect" in msg.lower() or _TO_US_RX.search(msg):
            print(f"  SKIP (addressed to us, not prospect) [{client_slug}]: {msg[:70]!r}")
            stats["skipped_to_us"] += 1; continue
        pros = find_prospect(r.get("subject") or "", client_slug)
        if not pros:
            print(f"  NO MATCH [{client_slug}] subj={r.get('subject')!r}")
            stats["no_match"] += 1; continue
        prospect = pros["from_addr"]
        persona = persona_from(pros.get("run_id"))
        print(f"  RELAY [{client_slug}] -> {prospect}  (from persona {persona or '?'})")
        print(f"        client wrote: {msg[:90]!r}")
        if not dry:
            if relay_send(client_slug, persona, prospect, pros.get("subject") or "", msg):
                mark_relayed(r["id"]); stats["relayed"] += 1
        else:
            stats["relayed"] += 1
    print(f"\n=== relay-client-replies === {json.dumps(stats)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
