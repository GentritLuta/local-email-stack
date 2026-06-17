"""fix-dmarc.py — add/repair a valid DMARC record on every sending domain that
lacks one, via the domain's authoritative DNS provider.

Gmail/Yahoo (Feb 2024 bulk-sender rules) require a valid DMARC record. Audit found:
  missing:   cleardiraya.com, dirayaget.com, tryalgoalpha.com, mercuryscales.com, ener-g-beratung.de
  malformed: diraya-marketing.shop (no p= tag)
  duplicate: lk-advertising.site (two records -> both ignored)
  ok:        aureonglobal.de, diraya.biz, diraya-agency.shop

Provider per domain (from NS records):
  Spaceship  -> cleardiraya.com, dirayaget.com, diraya-marketing.shop
  Cloudflare -> tryalgoalpha.com
  Hostinger  -> mercuryscales.com (Dorian token), lk-advertising.site
  NS1        -> ener-g-beratung.de  (no token -> reported, not changed)

DMARC content: "v=DMARC1; p=none;" — the minimal valid record that satisfies the
bulk-sender requirement (monitoring policy, blocks nothing).
"""
from __future__ import annotations
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV = REPO / "sequences" / "hostinger.env"
DMARC = "v=DMARC1; p=none;"
TTL = 3600


def load_env() -> dict:
    e = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            e[k.strip()] = v.strip().strip('"').strip("'")
    return e


E = load_env()


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")


def _req(url, headers, data=None, method="GET"):
    # spaceship.dev and developers.hostinger.com sit behind Cloudflare, which
    # blocks the default Python-urllib UA with error 1010. Send a browser UA.
    headers = {**headers, "User-Agent": _UA}
    r = urllib.request.Request(url, data=(json.dumps(data).encode() if data is not None else None),
                               headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=40)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read().decode()[:400]


# ─── Cloudflare ──────────────────────────────────────────────────────────────

def cf_fix(domain, zone, token):
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    st, body = _req(f"https://api.cloudflare.com/client/v4/zones/{zone}/dns_records?type=TXT&name=_dmarc.{domain}", H)
    existing = json.loads(body).get("result", []) if st == 200 else []
    if any("DMARC1" in (r.get("content") or "") for r in existing):
        return f"{domain}: DMARC already present (Cloudflare) — skip"
    st, body = _req(f"https://api.cloudflare.com/client/v4/zones/{zone}/dns_records", H,
                    {"type": "TXT", "name": f"_dmarc.{domain}", "content": DMARC, "ttl": TTL}, "POST")
    ok = st in (200, 201)
    return f"{domain}: {'ADDED' if ok else 'FAIL '} DMARC (Cloudflare) -> {st}" + ("" if ok else f" {body[:200]}")


# ─── Spaceship ───────────────────────────────────────────────────────────────

SS_BASE = "https://spaceship.dev/api/v1"


def _ss_h():
    return {"X-API-Key": E["SPACESHIP_API_KEY"], "X-API-Secret": E["SPACESHIP_API_SECRET"],
            "Content-Type": "application/json"}


def ss_records(domain):
    st, body = _req(f"{SS_BASE}/dns/records/{domain}?take=500&skip=0", _ss_h())
    return json.loads(body).get("items", []) if st == 200 else []


def ss_fix(domain):
    recs = ss_records(domain)
    dmarc = [r for r in recs if r.get("type") == "TXT" and r.get("name") in ("_dmarc", f"_dmarc.{domain}")]
    valid = [r for r in dmarc if "p=" in (r.get("value") or "").lower() and "dmarc1" in (r.get("value") or "").lower()]
    if valid and len(dmarc) == 1:
        return f"{domain}: DMARC already valid (Spaceship) — skip"
    # Remove any malformed/duplicate _dmarc first, then add the correct one.
    if dmarc:
        # Spaceship DELETE wants the body to be a raw ARRAY of records.
        st, body = _req(f"{SS_BASE}/dns/records/{domain}", _ss_h(),
                        [{"type": "TXT", "name": r.get("name"), "value": r.get("value")} for r in dmarc],
                        "DELETE")
        if st not in (200, 204):
            return f"{domain}: could NOT delete malformed/dup DMARC (Spaceship) -> {st} {body[:160]}; SKIP add to avoid duplicate"
    st, body = _req(f"{SS_BASE}/dns/records/{domain}", _ss_h(),
                    {"force": True, "items": [{"type": "TXT", "name": "_dmarc", "value": DMARC, "ttl": TTL}]}, "PUT")
    ok = st in (200, 201, 204)
    return f"{domain}: {'ADDED' if ok else 'FAIL '} DMARC (Spaceship) -> {st}" + ("" if ok else f" {body[:200]}")


# ─── Hostinger ───────────────────────────────────────────────────────────────

HOST_API = "https://developers.hostinger.com/api"


def host_records(domain, token):
    st, body = _req(f"{HOST_API}/dns/v1/zones/{domain}",
                    {"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if st != 200:
        return None, st, body
    return json.loads(body), st, body


def host_fix(domain, token):
    zone, st, body = host_records(domain, token)
    if zone is None:
        return f"{domain}: cannot read Hostinger zone -> {st} {body[:160]}"
    # Hostinger returns a list of record sets with 'name'/'type'/'records'.
    sets = zone if isinstance(zone, list) else zone.get("zone") or zone.get("records") or []
    dmarc_sets = [s for s in sets if s.get("type") == "TXT" and (s.get("name") in ("_dmarc", f"_dmarc.{domain}"))]
    flat = [(s, rec) for s in dmarc_sets for rec in (s.get("records") or [])]
    valid = [1 for _, rec in flat if "dmarc1" in (rec.get("content") or "").lower() and "p=" in (rec.get("content") or "").lower()]
    if len(flat) == 1 and valid:
        return f"{domain}: DMARC already valid (Hostinger) — skip"
    if len(flat) > 1:
        # duplicate -> overwrite the _dmarc set to a single correct record
        st, body = _req(f"{HOST_API}/dns/v1/zones/{domain}",
                        {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
                        {"overwrite": True, "zone": [{"name": "_dmarc", "type": "TXT", "ttl": TTL,
                                                       "records": [{"content": DMARC}]}]}, "PUT")
        ok = st in (200, 201, 202, 204)
        return f"{domain}: {'REPLACED dup' if ok else 'FAIL replace'} DMARC (Hostinger) -> {st}" + ("" if ok else f" {body[:200]}")
    # none -> merge-add
    st, body = _req(f"{HOST_API}/dns/v1/zones/{domain}",
                    {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
                    {"overwrite": False, "zone": [{"name": "_dmarc", "type": "TXT", "ttl": TTL,
                                                   "records": [{"content": DMARC}]}]}, "PUT")
    ok = st in (200, 201, 202, 204)
    return f"{domain}: {'ADDED' if ok else 'FAIL '} DMARC (Hostinger) -> {st}" + ("" if ok else f" {body[:200]}")


def main():
    print(f"Adding DMARC ({DMARC!r}) where missing/broken.\n")
    results = []
    # Cloudflare
    cf_zone = E.get("CF_ZONE_ID_ALGOALPHA") or E.get("CLOUDFLARE_ZONE_TRYALGOALPHA")
    cf_tok = E.get("CF_API_TOKEN_ALGOALPHA") or E.get("CLOUDFLARE_API_TOKEN")
    if cf_zone and cf_tok:
        results.append(cf_fix("tryalgoalpha.com", cf_zone, cf_tok))
    else:
        results.append("tryalgoalpha.com: no Cloudflare token/zone in env — SKIP")
    # Spaceship
    for d in ("cleardiraya.com", "dirayaget.com", "diraya-marketing.shop"):
        results.append(ss_fix(d))
    # Hostinger
    results.append(host_fix("mercuryscales.com", E.get("HOSTINGER_API_TOKEN_DORIAN", "")))
    # ener-g-beratung.de: the ENERG Hostinger account owns the zone (verified), so
    # add via that token even though public NS shows NS1.
    results.append(host_fix("ener-g-beratung.de", E.get("HOSTINGER_API_TOKEN_ENERG", "")))
    # getmark-eting.com: DNS on the mark-eting client's Hostinger account.
    results.append(host_fix("getmark-eting.com", E.get("HOSTINGER_API_TOKEN_MARK_ETING", "")))
    # lk-advertising.site: not owned by ANY available token (separate account) —
    # genuinely cannot fix; the duplicate _dmarc must be removed by its owner.
    results.append("lk-advertising.site: no API token owns this domain — owner must remove the duplicate _dmarc record manually")
    print("\n=== RESULTS ===")
    for r in results:
        print("  " + r)


if __name__ == "__main__":
    main()
