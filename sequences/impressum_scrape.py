"""impressum_scrape.py — harvest DACH B2B prospects from company Impressum pages.

German law (§5 DDG/TMG) requires every business website to publish an Impressum
with the legal company name, the Geschäftsführer / Inhaber name, a postal address,
and a contact email. That makes the Impressum a reliable, structured lead source
where team-page scraping fails (decision-makers rarely list personal emails).

For each domain: find the Impressum (homepage link or common paths), then extract
  - email            (the contact email)
  - first_name       (from "Geschäftsführer: <Name>" / "Vertreten durch:" / "Inhaber:")
  - company          (legal name, else domain)
  - city             (from "PLZ Ort")
and upsert into Supabase prospects for the given profile (verified=true).

Usage:
    py sequences/impressum_scrape.py <profile_slug> <domains_file> [--dry] [--limit N]
      domains_file: one domain or URL per line (blank lines / # comments ignored)
"""
from __future__ import annotations
import argparse, re, sys, uuid, urllib.parse
from pathlib import Path
import httpx

REPO = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
BASE = env["SUPABASE_URL"].rstrip("/") + "/rest/v1"
KEY = env["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"}

EMAIL_RX = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
# Geschäftsführer / Vertreten durch / Inhaber: capture the following name
GF_RX = re.compile(
    r"(?:Gesch[äa]ftsf[üu]hr(?:er|erin|ung)|Vertreten durch|Inhaber(?:in)?|"
    r"Vorstand|Gesellschafter)\s*[:\-]?\s*(?:Herr|Frau|Dr\.?|Dipl\.[-\w.]*\s*)?"
    r"([A-ZÄÖÜ][a-zäöüß]+)\s+([A-ZÄÖÜ][a-zäöüß\-]+)", re.I)
PLZ_RX = re.compile(r"\b(\d{5})\s+([A-ZÄÖÜ][a-zäöüß.\- ]{2,30})")
# Legal company name: a phrase ending in a German legal form.
COMPANY_RX = re.compile(
    r"([A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9&.,'\- ]{1,55}?\s"
    r"(?:gGmbH|GmbH\s*&\s*Co\.?\s*KG|GmbH|mbH|AG|GbR|UG\s*\(haftungsbeschränkt\)|UG|e\.\s?K\.|e\.\s?V\.|KG|OHG))")
GENERIC_FIRST = {"info", "kontakt", "office", "mail", "post", "service", "team", "zentrale"}
BAD_EMAIL_DOMAINS = ("sentry", "wixpress", "example", "domain.", "sentry.io")


def fetch(url: str, client: httpx.Client) -> str | None:
    try:
        r = client.get(url, follow_redirects=True)
        if r.status_code < 400 and "text/html" in r.headers.get("content-type", "") + "html":
            return r.text
    except Exception:
        return None
    return None


def find_impressum_url(domain: str, client: httpx.Client) -> tuple[str | None, str | None]:
    """Return (impressum_html, impressum_url). Try homepage link first, then
    common paths."""
    base = domain if domain.startswith("http") else f"https://{domain}"
    base = base.rstrip("/")
    home = fetch(base, client)
    if home:
        m = re.search(r'href=["\']([^"\']*impr[^"\']*)["\']', home, re.I)
        if m:
            href = m.group(1)
            url = href if href.startswith("http") else base + "/" + href.lstrip("/")
            html = fetch(url, client)
            if html:
                return html, url
    for p in ("impressum", "de/impressum", "impressum.html", "impressum/",
              "imprint", "kontakt/impressum", "ueber-uns/impressum", "legal-notice"):
        url = f"{base}/{p}"
        html = fetch(url, client)
        if html and ("impressum" in html.lower() or "geschäftsführ" in html.lower()
                     or "vertreten durch" in html.lower()):
            return html, url
    # last resort: parse homepage itself
    return (home, base) if home else (None, None)


def visible_text(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    # decode common entities + mailto
    html = html.replace("&auml;", "ä").replace("&ouml;", "ö").replace("&uuml;", "ü") \
               .replace("&Auml;", "Ä").replace("&Ouml;", "Ö").replace("&Uuml;", "Ü") \
               .replace("&szlig;", "ß").replace("&nbsp;", " ").replace("(at)", "@").replace("[at]", "@")
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text)


def extract(html: str, domain: str) -> dict | None:
    text = visible_text(html)
    # email — prefer one on the company's own domain
    emails = [e for e in EMAIL_RX.findall(text)
              if not any(b in e.lower() for b in BAD_EMAIL_DOMAINS)]
    root = domain.replace("https://", "").replace("http://", "").split("/")[0].lstrip("www.")
    on_domain = [e for e in emails if root.split(".")[0] in e.lower()]
    email = (on_domain or emails or [None])[0]
    if not email:
        return None
    gf = GF_RX.search(text)
    first_name = gf.group(1) if gf else None
    if first_name and first_name.lower() in GENERIC_FIRST:
        first_name = None
    plz = PLZ_RX.search(text)
    city = plz.group(2).strip().split("  ")[0].strip() if plz else None
    if city:
        city = re.split(r"\b(Telefon|Tel|Fax|E-?Mail|Deutschland|Germany)\b", city)[0].strip(" .,-")
    # company: first legal-name phrase in the Impressum; else domain root
    cm = COMPANY_RX.search(text)
    company = None
    if cm:
        company = re.sub(r"\s+", " ", cm.group(1)).strip(" .,-")
        # drop leading boilerplate words the regex may have swept in
        company = re.sub(r"^(?:Impressum|Angaben gemäß.*?DDG|Anbieter|Diensteanbieter|"
                         r"Verantwortlich.*?:|Herausgeber)\s*[:\-]?\s*", "", company, flags=re.I).strip()
    return {"email": email.lower(), "first_name": first_name,
            "company": company or root.split(".")[0].capitalize(), "city": city}


def upsert(rec: dict, profile: str, client: httpx.Client) -> str:
    """client must be a Supabase client (base_url=BASE, headers=H)."""
    email = rec["email"]
    q = urllib.parse.quote(email, safe="")
    ex = client.get(f"/prospects?profile_slug=eq.{profile}&email=eq.{q}&select=id")
    found = ex.json() if ex.status_code == 200 else []
    body = {"profile_slug": profile, "email": email, "first_name": rec.get("first_name"),
            "company": rec.get("company"), "city": rec.get("city"), "verified": True,
            "unsubscribed": False, "source": "impressum_scrape"}
    if found:
        client.patch(f"/prospects?id=eq.{found[0]['id']}",
                     json={k: v for k, v in body.items()},
                     headers={"Prefer": "return=minimal"})
        return "updated"
    body["unsubscribe_token"] = str(uuid.uuid4())
    client.post("/prospects", json=body, headers={"Prefer": "return=minimal"})
    return "inserted"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile_slug")
    ap.add_argument("domains_file")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    domains = []
    for ln in Path(args.domains_file).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            domains.append(ln)
    if args.limit:
        domains = domains[:args.limit]
    print(f"=== impressum_scrape: {len(domains)} domains -> profile {args.profile_slug} ===")

    found = withname = ins = upd = 0
    web = httpx.Client(timeout=15, headers=HEADERS)
    sb = httpx.Client(base_url=BASE, headers=H, timeout=30)
    try:
        for d in domains:
            html, url = find_impressum_url(d, web)
            if not html:
                print(f"  -- {d:38} (no impressum reachable)"); continue
            rec = extract(html, d)
            if not rec:
                print(f"  -- {d:38} (no email found)"); continue
            found += 1
            if rec.get("first_name"):
                withname += 1
            tag = f"{rec['email']}  first={rec.get('first_name')}  company={rec.get('company')!r}  city={rec.get('city')}"
            if args.dry:
                print(f"  OK {d:28} {tag}")
                continue
            verb = upsert(rec, args.profile_slug, sb)
            ins += verb == "inserted"; upd += verb == "updated"
            print(f"  {verb:8} {d:28} {tag}")
    finally:
        web.close(); sb.close()

    print(f"\n=== summary ===  domains={len(domains)}  with_email={found}  with_first_name={withname}  "
          f"inserted={ins}  updated={upd}")
    if not args.dry:
        print("Pool loaded. Nothing sends until warmup is started for the profile.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
