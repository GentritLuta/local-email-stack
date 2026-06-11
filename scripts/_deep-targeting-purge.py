"""Deep targeting purge over the WHOLE aureon base.
  SAFE auto-actions (no risk of losing a real agent):
    - pause foreign leads (non-US ccTLD email domains) -> verified=false + cancel
    - null mis-parsed first_names (flast like 'Jbasker') -> greeting falls back
    - null ISP/free-mail-derived companies (stragglers) -> pause until re-enriched
  SUSPECTS (no strong real-estate signal ANYWHERE, incl. source page) are NOT
  auto-purged (brandy domains like klausteam.com would false-positive) -> written
  to referral-lists/_targeting_suspects.txt for a deep web-research pass.

  py scripts/_deep-targeting-purge.py --dry
  py scripts/_deep-targeting-purge.py
"""
import json, re, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sequences"))
from name_derive import is_free_or_isp_domain, _is_initial_plus_last  # noqa: E402

DRY = "--dry" in sys.argv
REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
def get(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL+p, headers=H), timeout=90).read())
def patch(p, b):
    r = urllib.request.Request(URL+p, data=json.dumps(b).encode(), method="PATCH",
        headers={**H, "Content-Type": "application/json", "Prefer": "return=minimal"})
    urllib.request.urlopen(r, timeout=60).read()
def page(t, s, e=""):
    out=[]
    for off in range(0,20000,1000):
        b=get(f"{t}?select={s}{e}&limit=1000&offset={off}"); out+=b
        if len(b)<1000: break
    return out

FOREIGN_TLDS = {"dk","de","uk","nl","fr","es","it","ru","br","in","au","mx","pl",
                "se","no","fi","ch","at","be","pt","cz","nz","za","ie","gr","tr",
                "ua","ro","hu","sk"}  # .co/.io kept (US startups use them)
# Domains to hard-pause: excluded competitors / tools that are not ICP brokerages.
PURGE_DOMAINS = {"teamminik.com", "realmadrid.com", "corp.realmadrid.com",
                 "weltmonarch.de", "iglobe.dk"}
STRONG_RE = ["real estate","realestate","realty","realtor","brokerage","broker",
             "remax","re/max","keller","century 21","c21","coldwell","exp realty",
             "exprealty","compass","sotheby","berkshire","bhhs","weichert","redfin",
             "homesmart","mls","homes for sale","properties","property","homes",
             "realtors","listing","sells homes","sellshomes","home sales"]

def tld(d): return d.rsplit(".",1)[-1] if "." in d else ""
def has_re(*vals):
    hay = " ".join(v or "" for v in vals).lower()
    return any(k in hay for k in STRONG_RE)

pros = page("prospects", "id,email,first_name,company,website,source_url,verified",
            "&profile_slug=eq.aureon")
print(f"aureon base: {len(pros)}")

foreign, fix_name, fix_company, suspects = [], [], [], []
for p in pros:
    em = (p.get("email") or "").lower(); dom = em.split("@")[-1]
    fn = (p.get("first_name") or "").strip()
    co = p.get("company"); site = p.get("website"); src = p.get("source_url")
    if dom in PURGE_DOMAINS or tld(dom) in FOREIGN_TLDS:
        foreign.append(p); continue
    if fn and (_is_initial_plus_last(fn.lower()) or any(c.isdigit() for c in fn)
               or len(fn) < 2 or len(fn) > 14):
        fix_name.append(p)
    if is_free_or_isp_domain(dom) and co:
        fix_company.append(p)
    if not has_re(em, co, site, src):
        suspects.append(p)

print(f"\nPAUSE foreign (non-US ccTLD): {len(foreign)}")
for p in foreign[:12]: print(f"   {p['email']}")
print(f"\nFIX mis-parsed first_name -> null: {len(fix_name)}")
for p in fix_name[:12]: print(f"   {p['email']}  name={p.get('first_name')}")
print(f"\nFIX ISP/free-mail company -> null: {len(fix_company)}")
for p in fix_company[:12]: print(f"   {p['email']}  co={p.get('company')}")
print(f"\nSUSPECTS (no strong RE signal anywhere) -> deep-research, NOT auto-purged: {len(suspects)}")
for p in suspects[:25]: print(f"   {p['email']}  co={p.get('company')}  src={(p.get('source_url') or '')[:45]}")

if not DRY:
    for p in foreign:
        patch(f"prospects?id=eq.{p['id']}", {"verified": False})
        for r in get(f"runs?prospect_id=eq.{p['id']}&status=in.(queued,paused_replied)&select=id"):
            patch(f"runs?id=eq.{r['id']}", {"status": "cancelled"})
    for p in fix_name:
        patch(f"prospects?id=eq.{p['id']}", {"first_name": None})
    for p in fix_company:
        patch(f"prospects?id=eq.{p['id']}", {"company": None, "website": None})
        for r in get(f"runs?prospect_id=eq.{p['id']}&status=eq.queued&select=id"):
            patch(f"runs?id=eq.{r['id']}", {"status": "cancelled"})
    (REPO / "referral-lists" / "_targeting_suspects.txt").write_text(
        "\n".join(f"{p['email']}\t{p.get('company')}\t{p.get('website')}\t{p.get('source_url')}" for p in suspects),
        encoding="utf-8")
    print(f"\nAPPLIED: paused {len(foreign)} foreign, nulled {len(fix_name)} names, "
          f"nulled {len(fix_company)} ISP companies. {len(suspects)} suspects -> _targeting_suspects.txt")
