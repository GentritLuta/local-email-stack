# -*- coding: utf-8 -*-
"""bridge-portal-clients.py — feed portal-onboarded clients into the invoice generator.

billing-sync.py drops each portal client as C:\\Aureon Invoices\\clients\\<uuid>.json
(schema: company / legal_name / address_line / city / postal_code / country / vat_id /
funding...). The generator (C:\\Aureon Invoice App) reads a DIFFERENT store,
data\\clients.json, keyed by display name with buyer_* fields, and never read the
portal files — so portal clients were not generable. This bridges the two: it maps the
portal schema to the generator schema and upserts into data\\clients.json.

Idempotent. Adds new clients, updates portal-sourced ones, and never deletes or
overwrites a client that did not come from the portal (matched by display name).

    py scripts/bridge-portal-clients.py            # apply
    py scripts/bridge-portal-clients.py --dry      # show what would change
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORTAL_CLIENTS = Path(r"C:\Aureon Invoices\clients")
GEN_CLIENTS = Path(r"C:\Aureon Invoice App\data\clients.json")

# Portal stores country as a name; the generator/EN16931 wants an alpha-2 code.
_COUNTRY = {
    "germany": "DE", "deutschland": "DE", "austria": "AT", "österreich": "AT",
    "switzerland": "CH", "schweiz": "CH", "netherlands": "NL", "belgium": "BE",
    "france": "FR", "italy": "IT", "spain": "ES", "portugal": "PT", "ireland": "IE",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "united states": "US", "usa": "US", "united states of america": "US",
    "canada": "CA", "kosovo": "XK", "republic of kosovo": "XK", "albania": "AL",
    "poland": "PL", "czechia": "CZ", "czech republic": "CZ", "sweden": "SE",
    "denmark": "DK", "norway": "NO", "finland": "FI", "luxembourg": "LU",
}


def _alpha2(country: str | None) -> tuple[str, bool]:
    """Return (alpha2, ok). ok=False means we could not map it confidently."""
    if not country:
        return "", False
    c = country.strip()
    if len(c) == 2 and c.isalpha():
        return c.upper(), True
    code = _COUNTRY.get(c.lower())
    if code:
        return code, True
    return c, False  # leave raw, flag for manual fix


def _cust_code(company: str, taken: set) -> str:
    """Derive the AG-<CUST>-... numbering token: first alnum word, uppercased, unique."""
    token = re.sub(r"[^A-Za-z0-9]", "", (company or "client").split(" ")[0]).upper() or "CLIENT"
    base, code, n = token, token, 2
    while code in taken:
        code = f"{base}{n}"
        n += 1
    taken.add(code)
    return code


def map_client(p: dict, taken: set) -> tuple[str, dict]:
    company = (p.get("company") or p.get("legal_name") or p.get("billing_name")
               or "Client").strip()
    display = p.get("billing_name") or company
    country, ok = _alpha2(p.get("country"))
    rec = {
        "buyer_name": (p.get("legal_name") or company).strip(),
        "buyer_trading_name": company,
        "buyer_street": (p.get("address_line") or "").strip(),
        "buyer_postcode": (p.get("postal_code") or "").strip(),
        "buyer_city": (p.get("city") or "").strip(),
        "buyer_country": country,
        "buyer_steuernummer": "",
        "buyer_vat_id": (p.get("vat_id") or "").strip(),
        "buyer_email": (p.get("billing_email") or "").strip(),
        "buyer_phone": "",
        "buyer_customer_id": _cust_code(company, taken),
        "project_id": (p.get("slug") or "").strip(),
        "_country_unmapped": not ok,  # advisory flag; generator ignores unknown keys
    }
    return display, rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not PORTAL_CLIENTS.exists():
        print(f"no portal clients dir: {PORTAL_CLIENTS}")
        return 0
    if not GEN_CLIENTS.parent.exists():
        print(f"generator data dir missing: {GEN_CLIENTS.parent}")
        return 1

    existing = {}
    if GEN_CLIENTS.exists():
        try:
            existing = json.loads(GEN_CLIENTS.read_text(encoding="utf-8-sig"))
        except Exception as e:
            print(f"could not read existing clients.json: {e}")
            return 1

    taken = {v.get("buyer_customer_id", "") for v in existing.values() if isinstance(v, dict)}
    taken.discard("")

    added, updated, warned = 0, 0, []
    for f in sorted(PORTAL_CLIENTS.glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ! skip {f.name}: {e}")
            continue
        display, rec = map_client(p, taken)
        if rec.pop("_country_unmapped", False):
            warned.append(f"{display}: country '{p.get('country')}' not mapped to a code")
        prior = existing.get(display)
        if prior is None:
            existing[display] = rec
            added += 1
            print(f"  + add: {display}  (cust {rec['buyer_customer_id']}, {rec['buyer_country'] or '??'})")
        else:
            # keep a manually-set customer_id if one already exists
            if prior.get("buyer_customer_id"):
                rec["buyer_customer_id"] = prior["buyer_customer_id"]
            if prior != rec:
                existing[display] = rec
                updated += 1
                print(f"  ~ update: {display}")

    if warned:
        print("  ! review (country not auto-mapped, fix in the generator GUI):")
        for w in warned:
            print(f"      - {w}")

    if args.dry:
        print(f"[DRY] would add {added}, update {updated}. No file written.")
        return 0

    GEN_CLIENTS.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {GEN_CLIENTS}: +{added} added, {updated} updated, "
          f"{len(existing)} total clients now generable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
