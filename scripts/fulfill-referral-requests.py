"""fulfill-referral-requests.py — auto-fulfil the aureon give-first lead magnet
(agents who reply LIST / PROBATE) from a CURATED, verified attorney-list library.

WHY CURATED (not the CSE scraper): an automated scraper only captures firms that
publish an email on-page (a small minority), so it yields thin, low-trust lists.
The curated library (referral-lists/curated.json) holds hand-verified lists with
a lead attorney, a direct phone for EVERY firm, full address and practice focus
- built the way Jake's Indianapolis list was. The fulfiller matches a reply to
the agent's metro and sends that verified list instantly. Metros not curated yet
are QUEUED and flagged to info@ - we never serve a thin list.

ROBUST reply detection (fixes the old version's false sends + zero matches):
  - reads only the TOP of the reply (text before the quoted history), so our own
    "reply LIST" copy quoted in an auto-reply never self-triggers;
  - ignores replies from our own aureonglobal.de addresses;
  - requires the sender to be a real, non-unsubscribed prospect.

Flow each run (idempotent; safe every ~15 min):
  1. pull recent replies; keep genuine LIST/PROBATE intents not yet fulfilled
  2. resolve each agent's metro (phone area code -> city -> state)
  3. matched   -> email the curated list (xlsx + csv) from Anna, bcc info@, done
  4. unmatched -> queue + alert info@ once (auto-fulfils later once that metro is
     added to curated.json)

Usage:
  py scripts/fulfill-referral-requests.py          # fulfil all pending
  py scripts/fulfill-referral-requests.py --dry    # show what it would do
"""
from __future__ import annotations
import argparse
import base64
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LISTS = REPO / "referral-lists"
CURATED = LISTS / "curated.json"
FULFILLED = LISTS / ".fulfilled.json"     # reply ids already served
QUEUED = LISTS / ".queued.json"           # reply ids already alerted (uncovered metro)
RESEARCH_QUEUE = LISTS / ".research_queue.json"  # uncovered metros to build (with dispatch prompt)
BCC = "info@aureonglobal.de"
FROM = "Anna from Aureon Global <anna@outreach.aureonglobal.de>"
REPLY_TO = "anna@outreach.aureonglobal.de"
SUBJECT = "The attorney referral list I promised"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123 Safari/537.36"
FREEMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com",
            "comcast.net", "me.com", "live.com", "msn.com", "att.net", "verizon.net"}
# Big franchise roots: their corporate site reflects the brand, not the agent, so we
# name the brokerage but DON'T infer a market focus from the email-domain fallback.
FRANCHISE_ROOTS = {"kw.com", "remax.com", "century21.com", "coldwellbanker.com",
                   "compass.com", "exprealty.com", "sothebysrealty.com", "bhhs.com",
                   "era.com", "weichert.com", "homesmart.com", "realtypros.com"}


# ----- env / supabase -----
def load_env() -> dict:
    env = {}
    for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    try:
        priv = json.loads((REPO / "profiles" / "aureon.private.json").read_text(encoding="utf-8"))
        env["RESEND_KEY"] = priv.get("relay", {}).get("resend_api_key", "")
    except Exception:
        env["RESEND_KEY"] = ""
    if not env["RESEND_KEY"]:
        for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
            if line.startswith("RESEND_FULL_ACCESS_API_KEY"):
                env["RESEND_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
    return env


def supa_get(env: dict, path: str) -> list:
    URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
    KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
    req = urllib.request.Request(URL + path, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


# ----- reply intent parsing -----
_QUOTE_RE = re.compile(
    r"^(_{5,}|-{5,}|from:|sent:|to:|subject:|on .+wrote:|>.*|le .+a écrit\s*:)",
    re.IGNORECASE)


def top_reply(body: str) -> str:
    """The agent's actual words: everything before the quoted original."""
    out = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if _QUOTE_RE.match(s) or "________" in s:
            break
        out.append(ln)
    return "\n".join(out).strip()


ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def zip_in_reply(body: str) -> str | None:
    """A 5-digit ZIP the agent typed in their reply = their area. The most reliable
    metro signal; overrides the prospect's stored city/state when present."""
    top = top_reply(body)
    if not top or len(top) > 400:
        return None
    m = ZIP_RE.search(top)
    return m.group(1) if m else None


def intent_of(body: str) -> str | None:
    top = top_reply(body)
    if not top or len(top) > 400:          # a long top = not a clean keyword reply
        return None
    low = top.lower()
    if re.search(r"\bprobate\b", low):
        return "probate"
    if re.search(r"\blist\b", low):
        return "list"
    if ZIP_RE.search(top):                 # a ZIP alone = responding to "reply with your ZIP"
        return "list"
    return None


def is_ours(addr: str) -> bool:
    dom = addr.split("@")[-1].lower()
    return dom == "aureonglobal.de" or dom.endswith(".aureonglobal.de")


def area_code(phone: str) -> str:
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d[:3] if len(d) >= 10 else ""


# ----- personalization (from REAL data only; never invents a claim) -----
# A market keyword counts only if the agent's OWN site emphasizes it (in the
# <title> or repeated >= 3x), so the note reflects their stated focus, not a guess.
_FOCUS = [("luxury", "luxury homes"), ("waterfront", "waterfront properties"),
          ("first-time", "first-time buyers"), ("first time", "first-time buyers"),
          ("relocation", "relocations"), ("new construction", "new-construction homes"),
          ("downsiz", "helping clients downsize"), ("55+", "the 55+ market"),
          ("investment propert", "investment properties"), ("commercial real estate", "commercial real estate"),
          ("farm", "farm and land"), ("ranch", "ranch and land"), ("condo", "condos")]


def site_url_for(p: dict, addr: str) -> str:
    """The agent's website: their stored site, else their email domain if it's a
    real company domain (not free webmail)."""
    w = (p.get("website") or "").strip()
    if w:
        return w if w.startswith("http") else "https://" + w
    dom = addr.split("@")[-1].lower()
    if dom and dom not in FREEMAIL and dom not in FRANCHISE_ROOTS:
        return "https://" + dom              # their own company site
    return ""                                 # franchise root / freemail -> name brokerage only


def fetch_site(url: str) -> str | None:
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "replace").lower()
    except Exception:
        return None


def site_focus(html: str | None) -> str:
    if not html:
        return ""
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
    if m:
        title = m.group(1)
    for key, phrase in _FOCUS:
        if key in title or html.count(key) >= 3:
            return phrase
    return ""


def _clean_company(c: str | None) -> str:
    """Only name the brokerage when it reads like a real, multi-word brand. Many
    stored company values are mashed domain tokens ('Mynexthomeelite', 'Cbstiles')
    - naming those looks fake, so we skip them and say 'your site' instead."""
    c = (c or "").strip()
    return c if (" " in c and 2 <= len(c) <= 60) else ""


def personal_note(p: dict, html: str | None) -> str:
    """One tasteful opening line built only from verified facts: their brokerage
    name, their city, and a market focus their own website emphasizes. Returns ''
    when we have nothing real to say (then the email opens with the generic line)."""
    company = _clean_company(p.get("company"))
    city = (p.get("city") or "").strip()
    focus = site_focus(html)
    if not (company or city or focus):
        return ""
    s = "Before anything else, I took a quick look at "
    if company:
        s += company + (f" over in {city}" if city else "")
    else:
        s += "your site" + (f" and your {city} market" if city else "")
    if focus:
        s += f" — looks like {focus} are a big part of what you do"
    s += ". So this list is built for exactly that kind of agent."
    return s


# ----- metro resolution -----
def resolve(index: dict, city: str, state: str, ac: str, zipc: str | None = None) -> dict | None:
    lists = index.get("lists", [])
    if zipc:                                # ZIP the agent gave = most precise; try first
        z3 = zipc[:3]
        for e in lists:
            if z3 in e["match"].get("zip_prefixes", []):
                return e
    if ac:
        for e in lists:
            if ac in e["match"].get("area_codes", []):
                return e
    cl = (city or "").strip().lower()
    if cl:
        for e in lists:
            if cl in [c.lower() for c in e["match"].get("cities", [])]:
                return e
    su = (state or "").strip().upper()
    if su:
        for e in lists:
            if su in [s.upper() for s in e["match"].get("states", [])]:
                return e
    return None


# ----- send -----
def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def n_firms(csv_path: Path) -> int:
    return max(0, len(csv_path.read_text(encoding="utf-8-sig").splitlines()) - 1)


def send_list(env: dict, to_agent: str, p: dict, entry: dict,
              zipc: str | None, html_site: str | None, dry: bool) -> bool:
    csv_path = LISTS / entry["csv"]
    xlsx_path = LISTS / entry["xlsx"]
    n = n_firms(csv_path)
    label = entry["label"]
    first_name = (p.get("first_name") or "").strip()
    greet = f"Hey {first_name}," if first_name else "Hey,"
    note = personal_note(p, html_site)              # tailored to their brokerage/market (real data only)
    area = f" for your area ({zipc})" if zipc else f" for {label}"
    paras = [greet]
    if note:
        paras.append(note)
    paras += [
        f"Here is the attorney referral list I promised{area}, attached two ways: "
        f"an Excel file and a CSV you can import straight into your CRM. It is {n} "
        f"firms across {label}, covering divorce and family law plus estate and "
        f"probate, the two groups whose clients most often need to sell a home "
        f"fast. For each firm you get the lead attorney to ask for, their practice "
        f"focus, a direct phone, an email where the firm publishes one, the "
        f"website, and the office address.",
        "The fastest way to use it: pick the firms closest to you, call or email "
        "the lead attorney, and offer to be the agent they send any client who "
        "needs to sell quickly. Probate and divorce sellers are usually motivated, "
        "so even one or two firms saying yes can mean steady listings.",
        "No call needed and no strings. If you ever want us to run the seller "
        "outbound that keeps a pipeline like this full for you, just reply and I "
        "will send the details.",
    ]
    sig = ("Anna Bauer", "Senior Partnership Manager, Aureon Global")
    text = "\n\n".join(paras) + "\n\n" + sig[0] + "\n" + sig[1]
    import html as _html
    # Branded + email-client-safe (inline styles): gold header, body, attachments card.
    hdr = ('<div style="background:#0a0a0a;border-top:4px solid #d4af37;padding:20px 26px">'
           '<div style="color:#d4af37;font-weight:700;font-size:19px;letter-spacing:.5px">'
           'AUREON GLOBAL</div><div style="color:#94a3b8;font-size:12px;margin-top:3px">'
           'Performance Partner for Real Estate Agents &amp; Brokerages</div></div>')
    body = "".join(f'<p style="margin:0 0 14px">{_html.escape(p)}</p>' for p in paras)
    att = ('<div style="margin:18px 0;padding:14px 16px;background:#fafafa;'
           'border:1px solid #e5e7eb;border-radius:10px">'
           '<div style="font-weight:600;font-size:13px;color:#475569;margin-bottom:6px">'
           '2 attachments</div>'
           f'<div style="padding:4px 0;font-size:14px"><b>{_html.escape(entry["xlsx"])}</b>'
           f'<span style="color:#94a3b8"> &middot; {n} firms, styled</span></div>'
           f'<div style="padding:4px 0;font-size:14px"><b>{_html.escape(entry["csv"])}</b>'
           f'<span style="color:#94a3b8"> &middot; {n} firms, CRM-ready</span></div></div>')
    sig_html = (f'<p style="margin-top:18px"><b>{sig[0]}</b><br>'
                f'<span style="color:#64748b;font-size:13px">{sig[1]}</span></p>')
    html_body = (
        '<div style="font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;'
        'color:#0a0a0a;max-width:600px;margin:0 auto;border:1px solid #e5e7eb;'
        'border-radius:12px;overflow:hidden">'
        + hdr + '<div style="padding:24px 26px;line-height:1.6;font-size:15px">'
        + body + att + sig_html + '</div></div>'
    )
    if dry:
        print(f"     [dry] would send {n}-firm '{label}' list to {to_agent} "
              f"(greet={first_name or '-'}, zip={zipc or '-'})")
        return True
    payload = {
        "from": FROM, "to": [to_agent], "bcc": [BCC], "reply_to": REPLY_TO,
        "subject": SUBJECT, "html": html_body, "text": text,
        "attachments": [
            {"filename": entry["xlsx"], "content": b64(xlsx_path)},
            {"filename": entry["csv"], "content": b64(csv_path)},
        ],
        "tags": [{"name": "kind", "value": "referral_fulfilment"}],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {env['RESEND_KEY']}", "Content-Type": "application/json",
                 "User-Agent": "local-email-stack fulfil/2.0"})
    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception as e:
        body = getattr(e, "read", lambda: b"")()
        print(f"     ! send failed: {e} {body[:160]}")
        return False


def alert(env: dict, agent: str, city: str, state: str, ac: str, ltype: str, dry: bool) -> None:
    msg = (f"Agent {agent} replied {ltype.upper()} but their metro is not in the "
           f"curated library yet (city={city or '?'} state={state or '?'} "
           f"area_code={ac or '?'}). Build a verified list for that metro and add "
           f"it to referral-lists/curated.json; it will auto-fulfil on the next run.")
    if dry:
        print(f"     [dry] would ALERT info@: {msg}")
        return
    payload = {"from": FROM, "to": [BCC], "reply_to": REPLY_TO,
               "subject": f"[Aureon] uncovered referral metro: {city or state or ac or agent}",
               "text": msg}
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {env['RESEND_KEY']}", "Content-Type": "application/json",
                 "User-Agent": "local-email-stack fulfil/2.0"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        print(f"     ! alert failed: {e}")


def build_research_prompt(city: str, state: str, ac: str, zc: str | None) -> str:
    """A ready-to-run, anti-fabrication research brief for an uncovered metro — the
    same standard the curated library was built to. A dispatcher (or a session) runs
    this verbatim; its verified JSON drops straight into a metro file."""
    locus = ", ".join(x for x in [city, state] if x) or (f"ZIP code {zc}" if zc else f"area code {ac}")
    return (
        f"Build a VERIFIED attorney referral list for the US metro that contains {locus}. "
        "Step 1: identify the metro/county, its main towns, and its telephone area codes. "
        "Step 2: find at least 12 Estate/Probate firms and 12 Divorce/Family firms there. "
        "For EVERY firm, open the firm's OWN website and confirm: exact firm name, one named "
        "lead attorney, practice focus, city, a direct phone in the metro's area codes, the "
        "email ONLY if the firm publishes one (else \"\"), the website URL, and the full street "
        "address. ABSOLUTE RULE: no fabrication — every field must be read off the firm's real, "
        "live site; if you cannot verify a firm, skip it; never pad the list. Return ONLY a JSON "
        'object: {"firms":[{"firm","type","lead_attorney","practice","city","phone","email",'
        '"website","address"}]} where "type" is exactly "Estate / Probate" or "Divorce / Family". '
        "Then it is built with scripts/build-curated-list.py and gated by scripts/verify-curated-lists.py.")


def queue_research(city: str, state: str, ac: str, zc: str | None, ltype: str, dry: bool) -> None:
    """Record an uncovered metro (deduped) with a ready dispatch prompt, so it gets
    researched + built autonomously instead of only pinging info@."""
    key = (zc[:3] if zc else "") or ac or f"{(city or '').strip().lower()}|{(state or '').strip().upper()}"
    if not key.strip("|"):
        return
    try:
        q = json.loads(RESEARCH_QUEUE.read_text()) if RESEARCH_QUEUE.exists() else []
    except Exception:
        q = []
    if any(r.get("key") == key for r in q):
        return                                       # already requested — don't duplicate
    rec = {"key": key, "city": city or "", "state": state or "", "area_code": ac or "",
           "zip": zc or "", "intent": ltype, "status": "pending",
           "dispatch_prompt": build_research_prompt(city, state, ac, zc)}
    if dry:
        print(f"     [dry] would queue research for metro key={key!r}")
        return
    q.append(rec)
    RESEARCH_QUEUE.write_text(json.dumps(q, indent=2))
    print(f"     -> queued research for uncovered metro key={key!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    env = load_env()
    if not env.get("RESEND_KEY"):
        print("! no aureon resend key"); return 1
    index = json.loads(CURATED.read_text(encoding="utf-8"))

    fulfilled = set(json.loads(FULFILLED.read_text())) if FULFILLED.exists() else set()
    queued = set(json.loads(QUEUED.read_text())) if QUEUED.exists() else set()

    replies = supa_get(env, "replies?select=id,from_addr,body_snippet,received_at"
                            "&order=received_at.desc&limit=500")
    # genuine, not-ours, not-yet-fulfilled LIST/PROBATE intents
    cand = []
    for r in replies:
        addr = (r.get("from_addr") or "").lower()
        if not addr or is_ours(addr) or r["id"] in fulfilled:
            continue
        it = intent_of(r.get("body_snippet"))
        if it:
            cand.append((r, addr, it))
    print(f"replies: {len(replies)} | genuine external LIST/PROBATE pending: {len(cand)}")

    n_sent = n_queued = 0
    newly_fulfilled, newly_queued = [], []
    for r, addr, ltype in cand:
        ps = supa_get(env, f"prospects?email=eq.{urllib.parse.quote(addr)}"
                           f"&select=first_name,company,website,city,state,phone,unsubscribed&limit=1")
        if not ps:
            print(f"  - {addr}: not a prospect (skip)")
            continue
        p = ps[0]
        if p.get("unsubscribed"):
            print(f"  - {addr}: unsubscribed (skip)")
            continue
        ac = area_code(p.get("phone"))
        zc = zip_in_reply(r.get("body_snippet"))          # ZIP the agent typed (best signal)
        entry = resolve(index, p.get("city"), p.get("state"), ac, zc)
        q = (entry or {}).get("quality") or {}
        if entry and q.get("passed"):                       # QC GATE: only send verified lists
            print(f"  + {addr} [{ltype.upper()}] -> {entry['metro']} "
                  f"(zip={zc or '-'} ac={ac or '-'} city={p.get('city') or '-'}) "
                  f"[QC ok {q.get('checked_at')}]")
            html_site = None if args.dry else fetch_site(site_url_for(p, addr))  # tailor to their site
            if send_list(env, addr, p, entry, zc, html_site, args.dry):
                newly_fulfilled.append(r["id"]); n_sent += 1
        else:
            already = r["id"] in queued
            if entry:                                       # matched but failed/unverified QC -> never serve it
                why = (f"{entry['metro']} list BLOCKED by QC (passed={q.get('passed')}, "
                       f"flags={(q.get('flagged') or [])[:3]})")
            else:
                why = (f"NO curated metro (zip={zc or '-'} ac={ac or '-'} "
                       f"city={p.get('city') or '-'} state={p.get('state') or '-'})")
            print(f"  ~ {addr} [{ltype.upper()}] -> {why}"
                  f"{' [already queued]' if already else ' [QUEUE+ALERT]'}")
            if not already:
                alert(env, addr, p.get("city"), p.get("state"), ac, ltype, args.dry)
                if not entry:                               # uncovered -> autonomously research+build it
                    queue_research(p.get("city"), p.get("state"), ac, zc, ltype, args.dry)
                newly_queued.append(r["id"]); n_queued += 1

    if not args.dry:
        if newly_fulfilled:
            FULFILLED.write_text(json.dumps(sorted(fulfilled | set(newly_fulfilled))))
        # a reply we just served must leave the queued/alerted set; add any new misses
        final_queued = (queued - set(newly_fulfilled)) | set(newly_queued)
        if final_queued != queued:
            QUEUED.write_text(json.dumps(sorted(final_queued)))
    print(f"\nsent {n_sent} | newly queued {n_queued}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
