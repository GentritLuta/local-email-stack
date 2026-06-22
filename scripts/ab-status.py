# -*- coding: utf-8 -*-
"""ab-status.py — read the aureon step-1 A/B (seller-test vs give-first attorney list).

The runner splits step 1 50/50 by prospect_id hash: A-side = "a seller test for {company}",
B-side = "45 attorneys who hand off listings, {company}". Both carry the company merge, so we
match each step-1 send to its side by a stable subject substring, and tie genuine replies back
through the run. Compares delivered / open rate / reply rate per side since the A/B started.

  py scripts/ab-status.py            # since 2026-06-22 (A/B start)
  py scripts/ab-status.py --since 2026-06-25
"""
from __future__ import annotations
import argparse
import json
import ssl
import sys
import urllib.request
from pathlib import Path

ssl._create_default_https_context = ssl._create_unverified_context
REPO = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def env(p: Path) -> dict:
    d = {}
    for ln in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


S = env(REPO / "sequences" / "supabase.env")
TOK = S.get("SUPABASE_ACCESS_TOKEN")
REF = "ccmqkljsjiuavpydbkva"


def q(sql: str):
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{REF}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 Chrome/123"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=40).read())


def pct(n, d):
    return round(100 * n / d, 2) if d else 0.0


# per-profile step-1 A/B: (label, subject substring) for each side. A = current opener, B = give-first.
AB = {
    "aureon": {"a_lab": "A  seller test", "a_sub": "seller test",
               "b_lab": "B  give-first list", "b_sub": "attorneys who hand off"},
    "energ":  {"a_lab": "A  CHECK assessment", "a_sub": "schriftliche",
               "b_lab": "B  give-first FALLEN list", "b_sub": "vertragsfallen"},
    "lk-advertising": {"a_lab": "A  seller-lead test", "a_sub": "seller-lead test",
                       "b_lab": "B  give-first teardown", "b_sub": "free teardown"},
    "diraya": {"a_lab": "A  REVIEW one-pager", "a_sub": "one-pager",
               "b_lab": "B  give-first GHOSTS list", "b_sub": "ghost-cases"},
    "mark-eting": {"a_lab": "A  teardown subject", "a_sub": "visibility teardown",
                   "b_lab": "B  curiosity subject", "b_sub": "who shows up before"},
}


def rows_for(profile: str, since: str):
    cfg = AB[profile]
    return q(f"""
      with s1 as (
        select s.run_id, s.delivered, s.opened_at,
          case when s.subject ilike '%%{cfg['b_sub']}%%' then '{cfg['b_lab']}'
               when s.subject ilike '%%{cfg['a_sub']}%%' then '{cfg['a_lab']}'
               else 'other' end side
        from send_log s join runs r on r.id=s.run_id join prospects p on p.id=r.prospect_id
        where p.profile_slug='{profile}' and s.step_n=1 and s.sent_at >= '{since}'),
      rep as (select distinct run_id from replies where profile_slug='{profile}' and class='reply')
      select s1.side, count(*) sends, count(*) filter (where s1.delivered) delivered,
        count(*) filter (where s1.opened_at is not null) opened,
        count(*) filter (where rep.run_id is not null) replies
      from s1 left join rep on rep.run_id=s1.run_id
      group by s1.side order by s1.side""")


def fmt(profile: str, since: str) -> str:
    cfg = AB[profile]
    rows = rows_for(profile, since)
    out = [f"{profile} step-1 A/B  (since {since})", "-" * 64,
           f"{'side':26} {'sends':>6} {'deliv':>6} {'open%':>7} {'repl':>5} {'reply%':>7}"]
    for r in rows:
        out.append(f"{r['side']:26} {r['sends']:>6} {r['delivered']:>6} "
                   f"{pct(r['opened'], r['delivered']):>6}% {r['replies']:>5} {pct(r['replies'], r['delivered']):>6}%")
    if not rows:
        out.append("(no step-1 sends since the start date yet)")
    out.append(f"{cfg['a_lab'].strip()} = current opener  |  {cfg['b_lab'].strip()} = give-first challenger")
    return "\n".join(out)


def send_email(subject: str, body: str) -> bool:
    import smtplib
    import ssl as _ssl
    from email.mime.text import MIMEText
    from email.utils import formatdate, make_msgid
    H = env(REPO / "sequences" / "hostinger.env")
    host, port = H.get("SMTP_HOST"), int(H.get("SMTP_PORT", "465"))
    user, pw = H.get("SMTP_USER"), H.get("SMTP_PASS")
    to = "info@aureonglobal.de"
    if not (host and user and pw):
        print("  ! SMTP creds missing — printed only"); return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = f"AB digest <{H.get('FROM_ADDR', user)}>"
    msg["To"] = to; msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="aureonglobal.de")
    try:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=_ssl.create_default_context()) as s:
            s.login(user, pw); s.send_message(msg)
        return True
    except Exception as e:
        print(f"  ! send failed: {str(e)[:120]}"); return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="aureon", choices=list(AB), help="single client A/B")
    ap.add_argument("--all", action="store_true", help="report every client A/B")
    ap.add_argument("--email", action="store_true", help="email the digest to info@aureonglobal.de")
    ap.add_argument("--since", default="2026-06-22", help="A/B start date (YYYY-MM-DD)")
    a = ap.parse_args()
    profiles = list(AB) if (a.all or a.email) else [a.profile]
    body = "\n\n".join(fmt(p, a.since) for p in profiles)
    print(body)
    if a.email:
        ok = send_email("Give-first A/B digest", body + "\n\nRun yourself: py scripts/ab-status.py --all")
        print("\n[emailed to info@aureonglobal.de]" if ok else "\n[email failed — printed above]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
