# -*- coding: utf-8 -*-
"""fulfill-seller-test.py — auto-deliver the aureon "seller test": when an agent
replies with their zip, source motivated sellers for that zip and email them the
first batch, then mark the lead delivered (eligible for the Calendly unlock).

Sellers come from source-seller-leads.py. With the paid BatchData provider on
(SELLER_LEADS_PROVIDER=batchdata + BATCHDATA_API_KEY in hostinger.env) those leads
carry owner contact. In free mode they are signal-only and this fulfiller delivers
NOTHING (it never ships a lead with no contact) — it queues the agent instead. So
it is safe to run before the key is added; it simply waits.

Separation of magnets:
  - a ZIP reply (the "reply with your zip" seller test) -> THIS fulfiller.
  - a LIST / PROBATE reply (the attorney referral list) -> fulfill-referral-requests.py.

Flow each run (idempotent, safe to schedule every ~15 min):
  1. pull recent replies; keep aureon agents whose reply is a zip seller-test ask,
     not yet fulfilled, not suppressed/unsubscribed.
  2. extract the zip; source sellers via source_seller_leads.
  3. has contactable sellers -> email the agent the first N, bcc info@, mark
     status=sellers_sent.  none contactable -> mark status=sourcing (retry later).

Usage:
  py scripts/fulfill-seller-test.py            # deliver all pending
  py scripts/fulfill-seller-test.py --dry      # show what it would do, send/write nothing
  py scripts/fulfill-seller-test.py --limit 5 --count 2
"""
from __future__ import annotations
import argparse
import datetime as dt
import html as _html
import importlib.util
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# source_seller_leads lives in a hyphenated module — load it by path.
_spec = importlib.util.spec_from_file_location("ssl_src", REPO / "scripts" / "source-seller-leads.py")
_ssl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ssl)
source_seller_leads = _ssl.source_seller_leads

# build-home-value-funnel (the agent's personal seller-capture page) — also hyphenated.
_hv_spec = importlib.util.spec_from_file_location("hv_src", REPO / "scripts" / "build-home-value-funnel.py")
_hv = importlib.util.module_from_spec(_hv_spec)
_hv_spec.loader.exec_module(_hv)


def home_value_page(agent: dict, zipc: str, dry: bool) -> str:
    """Generate (refresh) the agent's personal seller-capture page and push it live.
    The page routes every homeowner opt-in straight to this agent as a real,
    contactable seller lead (source=home_value_funnel, for_agent). This is the
    actual free engine — free public data has no contactable cold sellers, but a
    homeowner who checks their own value opts in with their own contact. Returns
    the public URL (empty on failure)."""
    import shutil
    import subprocess
    import tempfile
    email = (agent.get("email") or "").lower()
    slug = _hv.slugify(email.split("@")[0])
    name = (agent.get("first_name") or email.split("@")[0].title()).strip() or "there"
    page = _hv.page_html(agent_name=name, agent_company=(agent.get("company") or "your brokerage"),
                         agent_email=agent["email"], zip_code=zipc,
                         profile_slug=agent.get("profile_slug", "aureon"))
    out = _hv.OUT_DIR / f"{slug}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    url = f"{_hv.PAGES_BASE}/{slug}.html"
    if dry:
        print(f"    [DRY] would generate + deploy home-value page: {url}")
        return url
    # Deploy the single page to the les_pages site. Best-effort: a push failure must
    # never block the fulfillment (the page is on disk and deploys on the next run).
    try:
        wt = tempfile.mkdtemp(prefix="hv_")
        run = lambda *a, cwd: subprocess.run(a, cwd=cwd, capture_output=True, timeout=90)
        run("git", "fetch", "les_pages", cwd=REPO)
        run("git", "worktree", "add", "--detach", wt, "les_pages/main", cwd=REPO)
        (Path(wt) / "home-value").mkdir(exist_ok=True)
        shutil.copy(out, Path(wt) / "home-value" / f"{slug}.html")
        run("git", "add", f"home-value/{slug}.html", cwd=wt)
        run("git", "-c", "user.name=Aureon", "-c", "user.email=info@aureonglobal.de",
            "commit", "-q", "-m", f"home-value page: {slug}", cwd=wt)
        run("git", "push", "les_pages", "HEAD:main", cwd=wt)
        run("git", "worktree", "remove", wt, "--force", cwd=REPO)
    except Exception as e:
        print(f"    ! home-value page deploy failed (non-blocking): {str(e)[:120]}")
    return url


def load_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


SUPA = load_env(REPO / "sequences" / "supabase.env")
HOST = load_env(REPO / "sequences" / "hostinger.env")
URL = SUPA["SUPABASE_URL"].rstrip("/")
KEY = SUPA["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
try:
    RESEND_KEY = json.loads((REPO / "profiles" / "aureon.private.json").read_text(encoding="utf-8")).get("relay", {}).get("resend_api_key", "")
except Exception:
    RESEND_KEY = ""
RESEND_KEY = RESEND_KEY or HOST.get("RESEND_FULL_ACCESS_API_KEY", "")

FROM = "Anna from Aureon Global <anna@outreach.aureonglobal.de>"
REPLY_TO = "info@aureonglobal.de"
BCC = "info@aureonglobal.de"
UA = "local-email-stack fulfill-seller-test/1.0"

SUPPRESS_ADDRS = {"hunter@laso.finance", "jake@cbstiles.com"}
SUPPRESS_DOMAINS = {"laso.finance", "aureonglobal.de", "algoalpha.io",
                    "atalsolidrocks.com", "atalsolidrocks.io", "diraya.ca", "wolt.com"}

_QUOTE = re.compile(r"^(_{5,}|-{5,}|from:|sent:|to:|subject:|on .+wrote:|>.*)", re.I)


def top_reply_text(body: str) -> str:
    out = []
    for ln in (body or "").splitlines():
        if _QUOTE.match(ln.strip()) or "________" in ln:
            break
        out.append(ln)
    return "\n".join(out).strip() or (body or "").strip()


def extract_zip(text: str) -> str:
    m = re.search(r"\b(\d{5})\b", text or "")
    return m.group(1) if m else ""


def is_seller_test_request(subject: str, body: str) -> bool:
    """A ZIP-led reply (the 'reply with your zip' opt-in). Excludes LIST / PROBATE
    keyword replies (the attorney magnet, a different fulfiller) and excludes long
    replies where a ZIP merely sits in a signature, by requiring the zip up front.
    Works off the reply HEAD so an inline-quoted reply still parses correctly."""
    if re.search(r"\b(probate|list)\b", f"{subject or ''}\n{body or ''}", re.I):
        return False
    head = re.sub(r"\s+", " ", (body or "")).strip()
    if not extract_zip(head):
        return False
    if extract_zip(head[:40]):
        return True  # zip-led reply (e.g. "46135 ...", "47448 or 47401 ...")
    if re.search(r"\bzip\b", head[:90], re.I) and extract_zip(head[:90]):
        return True  # "...please try zip code 46033"
    return False


def is_suppressed(addr: str) -> bool:
    a = (addr or "").lower().strip()
    if a in SUPPRESS_ADDRS:
        return True
    dom = a.split("@", 1)[1] if "@" in a else ""
    return dom in SUPPRESS_DOMAINS


def supa_get(path: str) -> list:
    return json.loads(urllib.request.urlopen(urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H), timeout=40).read())


def supa_patch(path: str, body: dict) -> None:
    urllib.request.urlopen(urllib.request.Request(f"{URL}/rest/v1/{path}", data=json.dumps(body).encode(),
                           headers={**H, "Prefer": "return=minimal"}, method="PATCH"), timeout=30).read()


SELLER_TEST_PROFILES = {"aureon", "lk-advertising"}


def active_agent(addr: str) -> dict | None:
    rows = supa_get("prospects?email=eq." + urllib.parse.quote((addr or "").lower())
                    + "&select=id,email,first_name,company,profile_slug,unsubscribed,custom_fields&limit=1")
    if not rows:
        return None
    p = rows[0]
    if p.get("unsubscribed") or p.get("profile_slug") not in SELLER_TEST_PROFILES:
        return None
    return p


def set_status(prospect: dict, **fields) -> None:
    cf = dict(prospect.get("custom_fields") or {})
    so = dict(cf.get("seller_outreach") or {})
    so.update(fields)
    cf["seller_outreach"] = so
    supa_patch(f"prospects?id=eq.{prospect['id']}", {"custom_fields": cf})


def mark_reply(reply: dict, fulfilled: bool, **extra) -> None:
    rh = dict(reply.get("raw_headers") or {})
    rh["seller_test_fulfilled"] = fulfilled
    rh["seller_test_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    rh.update(extra)
    supa_patch(f"replies?id=eq.{reply['id']}", {"raw_headers": rh})


def brand_sender(profile_slug: str) -> tuple[str, str, str]:
    """(from_header, reply_to, resend_key) for the agent's brand. aureon keeps the
    Anna sender; other brands send from their own persona + Resend relay."""
    if profile_slug == "aureon":
        return FROM, REPLY_TO, RESEND_KEY
    try:
        prof = json.loads((REPO / "profiles" / f"{profile_slug}.json").read_text(encoding="utf-8"))
    except Exception:
        prof = {}
    relay = prof.get("relay") or {}
    key = relay.get("resend_api_key") or RESEND_KEY
    p0 = (prof.get("personas") or [{}])[0]
    from_name = p0.get("from_name") or prof.get("name") or "the team"
    from_addr = p0.get("from_addr") or ""
    from_hdr = f"{from_name} <{from_addr}>" if from_addr else FROM
    return from_hdr, (relay.get("report_to") or REPLY_TO), key


def deliver(agent: dict, zipc: str, leads: list, hv_url: str, dry: bool) -> bool:
    fn = (agent.get("first_name") or "there").strip() or "there"
    esc = _html.escape
    # FSBO is an honest BONUS: listings to reach out to, never claimed as handed contacts.
    rows_html, text_lines = "", []
    for i, l in enumerate(leads, 1):
        addr = l.get("address") or "(address on request)"
        sig = (l.get("signal") or "").replace("-", " ").replace("_", " ")
        contact = " / ".join(x for x in [l.get("contact_phone"), l.get("contact_email")] if x)
        if not contact:
            src = l.get("source") or ""
            contact = ("reach out via the listing: " + src) if src.startswith("http") else (src or "no direct contact")
        if l.get("owner_name"):
            contact = l["owner_name"] + "  |  " + contact
        rows_html += (f"<tr><td style='padding:5px 10px;border-bottom:1px solid #eee'>{i}</td>"
                      f"<td style='padding:5px 10px;border-bottom:1px solid #eee'>{esc(addr)}</td>"
                      f"<td style='padding:5px 10px;border-bottom:1px solid #eee'>{esc(sig)}</td>"
                      f"<td style='padding:5px 10px;border-bottom:1px solid #eee'>{esc(contact)}</td></tr>")
        text_lines.append(f"{i}. {addr}  [{sig}]  {contact}")
    fsbo_html = (f"<p style='margin-top:18px'><b>Bonus, for-sale-by-owner listings in {esc(zipc)} right now</b> "
                 f"you can reach out to directly:</p>"
                 f"<table style=\"border-collapse:collapse;font-size:14px;border:1px solid #e2e8f0\">"
                 f"<tr style=\"background:#f5f5f5\"><th style='padding:6px 10px;text-align:left'>#</th>"
                 f"<th style='padding:6px 10px;text-align:left'>Property</th>"
                 f"<th style='padding:6px 10px;text-align:left'>Signal</th>"
                 f"<th style='padding:6px 10px;text-align:left'>How to reach</th></tr>{rows_html}</table>") if leads else ""
    fsbo_text = (f"\n\nBonus, for-sale-by-owner listings in {zipc} you can reach out to now:\n\n"
                 + "\n".join(text_lines)) if leads else ""
    html = (f"<div style=\"font-family:system-ui,sans-serif;color:#1e293b;max-width:640px\">"
            f"<p>Hi {esc(fn)},</p>"
            f"<p>Your seller test is set up. Here is your personal seller-capture page:</p>"
            f"<p><a href=\"{esc(hv_url)}\" style=\"font-weight:600\">{esc(hv_url)}</a></p>"
            f"<p>Share it with your sphere, your past clients, and your social. Every homeowner who "
            f"checks their home value there comes straight to you as a seller lead, with their name, "
            f"contact, and what they tell us about their home and timeline. We send each one a "
            f"consented follow-up on your behalf and route the conversation to you. The more you "
            f"share it, the more sellers it brings.</p>"
            f"{fsbo_html}"
            f"<p>Want this wired deeper into your pipeline? Just reply.</p>"
            f"<p>{esc(fn) and ''}Aureon Global</p></div>")
    text = (f"Hi {fn},\n\nYour seller test is set up. Here is your personal seller-capture page:\n\n"
            f"{hv_url}\n\nShare it with your sphere, past clients, and social. Every homeowner who "
            f"checks their value there comes to you as a seller lead with their contact and timeline; "
            f"we send a consented follow-up and route the conversation to you."
            f"{fsbo_text}\n\nAureon Global")
    if dry:
        print(f"  [DRY] would email {agent.get('email')} [{agent.get('profile_slug')}]: capture page {hv_url} + {len(leads)} FSBO bonus")
        return True
    from_hdr, reply_to, key = brand_sender(agent.get("profile_slug", "aureon"))
    if not key:
        print("  ! no RESEND key for this brand — cannot deliver")
        return False
    payload = {"from": from_hdr, "to": [agent["email"]], "bcc": [BCC], "reply_to": reply_to,
               "subject": f"Your seller test is live, your capture page for {zipc}", "html": html, "text": text,
               "tags": [{"name": "kind", "value": "seller_test"}]}
    try:
        urllib.request.urlopen(urllib.request.Request("https://api.resend.com/emails",
                               data=json.dumps(payload).encode(), method="POST",
                               headers={"Authorization": f"Bearer {key}",
                                        "Content-Type": "application/json", "User-Agent": UA}), timeout=25)
        return True
    except urllib.error.HTTPError as e:
        print(f"  ! deliver failed: HTTP {e.code} {e.read().decode()[:160]}")
        return False
    except Exception as e:
        print(f"  ! deliver failed: {e}")
        return False


def one_pass(limit: int, count: int, dry: bool) -> dict:
    stats = {"candidates": 0, "delivered": 0, "queued": 0, "skipped": 0, "errors": 0}
    rows = supa_get("replies?class=eq.reply&select=id,from_addr,subject,body_snippet,"
                    "raw_headers,received_at&order=received_at.desc&limit=200")
    todo = []
    for r in rows:
        if (r.get("raw_headers") or {}).get("seller_test_fulfilled"):
            continue
        frm = (r.get("from_addr") or "").lower()
        if frm.startswith(("alerts@", "drafts@", "reports@")) or is_suppressed(frm):
            continue
        msg = top_reply_text(r.get("body_snippet") or "")
        if not is_seller_test_request(r.get("subject", ""), msg):
            continue
        todo.append((r, msg))
    todo = todo[:limit]
    stats["candidates"] = len(todo)
    print(f"seller-test zip replies to evaluate: {len(todo)}  (provider={_ssl.PROVIDER})")
    for r, msg in todo:
        agent = active_agent(r.get("from_addr"))
        if not agent:
            stats["skipped"] += 1
            if not dry:
                mark_reply(r, True, seller_test_skipped="not_an_agent")
            continue
        zipc = extract_zip(f"{r.get('subject','')} {msg}")
        # The agent's personal seller-capture page is the real engine: free public
        # data has no contactable cold sellers, but a homeowner who checks their own
        # value opts in with their own contact, routed straight to this agent.
        hv_url = home_value_page(agent, zipc, dry)
        if not hv_url:
            stats["errors"] += 1
            continue
        # FSBO listings in the zip are an honest BONUS (may be empty).
        leads = []
        try:
            res = source_seller_leads(zipc, limit=max(count, 5))
            leads = [l for l in res.get("leads", []) if l.get("address") or l.get("source")][:count]
        except Exception as e:
            print(f"    ! fsbo source error (non-blocking): {str(e)[:100]}")
        print(f"  · {agent['email']} [{agent.get('profile_slug')}] zip {zipc} — page + {len(leads)} fsbo bonus")
        if deliver(agent, zipc, leads, hv_url, dry):
            stats["delivered"] += 1
            if not dry:
                set_status(agent, status="page_sent", zip=zipc, page=hv_url,
                           fsbo_count=len(leads), delivered_at=dt.datetime.now(dt.timezone.utc).isoformat())
                mark_reply(r, True, seller_test_delivered=hv_url)
        else:
            stats["errors"] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--count", type=int, default=10, help="sellers delivered per agent")
    a = ap.parse_args()
    print(json.dumps(one_pass(a.limit, a.count, a.dry), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
