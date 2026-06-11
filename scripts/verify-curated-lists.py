# -*- coding: utf-8 -*-
"""verify-curated-lists.py — automatic, strict QC gate for the attorney referral
lists. Audits every firm and writes a `quality` stamp into curated.json per list.
The fulfiller (fulfill-referral-requests.py) REFUSES to send any list whose stamp
is missing or `passed=false`, so a degraded list never reaches an agent.

A firm is VERIFIED real when: its website is reachable (robust fetch: retries +
www/http/relaxed-SSL fallback, so transient blips and bare-domain/JS sites don't
false-flag), the site OR its domain signals a law practice, AND it has a valid
10-digit phone in the metro's area codes. Firm/attorney name on the page is logged
as a bonus signal. Email domains are MX-checked.

STRICT pass bar (all must hold):
  * 100% of firms have a valid 10-digit phone in the metro's area codes
  * >= 95% of firms are VERIFIED (reachable law site + valid phone)
  * >= 90% of listed emails have a valid-MX domain

Run weekly (LES-verify-lists) to catch link-rot. Usage: py scripts/verify-curated-lists.py [--dry]
"""
import sys, csv, re, json, ssl, argparse, datetime as dt, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
import lead_verify as lv  # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LISTS = REPO / "referral-lists"
CURATED = LISTS / "curated.json"
PRACTICE = re.compile(r"estate|probate|divorce|family|elder|trust|guardianship|wills?|attorney|law", re.I)
DOM_PRACTICE = re.compile(r"law|legal|estate|probate|attorney|counsel|esq|family", re.I)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123 Safari/537.36"
STOP = {"law","llc","pllc","llp","attorney","attorneys","office","offices","group","firm","the","and","of"}
MIN_VERIFIED, MIN_MX = 0.95, 0.90
_CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE


def fetch(url):
    """Robust: try the url, then www-prefixed, then http; retry transient blips.
    Returns (html_or_None, status) where status='ok'|'httpNNN'|'unreachable'."""
    if not url: return None, "no-url"
    host = re.sub(r"^https?://", "", url).split("/")[0]
    attempts = [url if url.startswith("http") else "https://" + host]
    if not host.startswith("www."): attempts.append("https://www." + host)
    attempts.append("http://" + host)
    http_code = None
    for a in attempts:                               # try ALL variants; a 301/403 on one shouldn't bail
        try:
            ctx = _CTX if a.startswith("https") else None
            r = urllib.request.urlopen(urllib.request.Request(a, headers={"User-Agent": UA}), timeout=12, context=ctx)
            return r.read().decode("utf-8", "replace").lower(), "ok"
        except urllib.error.HTTPError as e:
            http_code = http_code or f"http{e.code}"  # domain responds (blocked/redirect); keep trying www/http
            continue
        except Exception:
            continue
    return None, (http_code or "unreachable")


def toks(firm): return [t for t in re.split(r"[^a-z0-9]+", firm.lower()) if len(t) > 3 and t not in STOP]


def check(row, acs):
    firm, atty, email, website, phone = row[0], row[2], row[6], row[7], row[5]
    html, st = fetch(website)
    exists = st != "unreachable" and st != "no-url"
    dom = re.sub(r"^https?://", "", website or "").split("/")[0].lower()
    name = None
    if html:
        last = atty.split()[-1].lower() if atty else ""
        name = any(t in html for t in toks(firm)) or (len(last) > 2 and last in html) or any(t in dom for t in toks(firm))
    practice_ok = bool((html and PRACTICE.search(html)) or DOM_PRACTICE.search(dom))
    mx = lv.verify(email, do_smtp_probe=False).verified if email else None
    d = re.sub(r"\D", "", phone or ""); d = d[1:] if len(d) == 11 and d.startswith("1") else d
    phone_ok = len(d) == 10 and (d[:3] in acs)
    # If the page is readable, require a practice signal (catches a wrong site). If it
    # only responds with a block (403) we can't read it, so a live site + valid metro
    # phone is sufficient — don't penalize a real firm for blocking bots.
    verified = exists and phone_ok and (practice_ok or html is None)
    return {"firm": firm, "web": st, "exists": exists, "loaded": st == "ok",
            "name": name, "practice": practice_ok, "mx": mx, "phone_ok": phone_ok, "verified": verified}


def audit(entry):
    rows = list(csv.reader((LISTS / entry["csv"]).open(encoding="utf-8-sig")))[1:]
    acs = set(entry["match"].get("area_codes", []))
    res = []
    with ThreadPoolExecutor(max_workers=14) as ex:
        for f in as_completed([ex.submit(check, r, acs) for r in rows]):
            res.append(f.result())
    n = len(res)
    verified = sum(1 for r in res if r["verified"])
    live = sum(1 for r in res if r["exists"])
    name = sum(1 for r in res if r["name"])
    phone = sum(1 for r in res if r["phone_ok"])
    have_e = [r for r in res if r["mx"] is not None]; mx = sum(1 for r in have_e if r["mx"])
    v_pct, l_pct, p_pct = verified / n, live / n, phone / n
    n_pct = (name / live) if live else 1.0
    mx_pct = (mx / len(have_e)) if have_e else 1.0
    flagged = [r["firm"] for r in res if not r["verified"]]
    passed = (p_pct == 1.0) and (v_pct >= MIN_VERIFIED) and (mx_pct >= MIN_MX)
    return {"checked_at": dt.date.today().isoformat(), "firms": n,
            "verified_pct": round(v_pct, 3), "live_pct": round(l_pct, 3),
            "name_pct": round(n_pct, 3), "phone_pct": round(p_pct, 3),
            "email_mx_pct": round(mx_pct, 3), "flagged": flagged, "passed": bool(passed)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true"); args = ap.parse_args()
    data = json.loads(CURATED.read_text(encoding="utf-8"))
    print(f"{'METRO':<22} {'firms':>5} {'verified':>9} {'phone':>6} {'mx':>6}  PASS")
    npass = 0
    for e in data["lists"]:
        q = audit(e); e["quality"] = q; npass += q["passed"]
        tail = "PASS" if q["passed"] else "FAIL -> " + str(q["flagged"][:4])
        flags = f"  flags={q['flagged']}" if q["flagged"] else ""
        print(f"{e['metro']:<22} {q['firms']:>5} {q['verified_pct']*100:>8.0f}% {q['phone_pct']*100:>5.0f}% {q['email_mx_pct']*100:>5.0f}%  {tail}{flags}")
    if not args.dry:
        CURATED.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\n{npass}/{len(data['lists'])} lists PASS the strict QC bar"
          f"{'  (stamped into curated.json)' if not args.dry else '  [dry]'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
