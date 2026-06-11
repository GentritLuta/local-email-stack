"""import-prospects-csv.py — load a purchased / exported contact list into the
Supabase `prospects` pool for a given profile, so the sequence pipeline can
enroll + send to them (subject to warmup/caps; no send happens here).

Maps flexible column names (DE/EN), sets verified=true + a fresh unsubscribe
token, and dedupes by (profile_slug, email). Idempotent.

CSV needs at least an email column. first_name + company (+ city for DACH
profiles) are required by the sequence merge tags — rows missing them are
imported but flagged (enrollment will skip them until filled).

Usage:
    py scripts/import-prospects-csv.py <profile_slug> <path-to.csv>
    py scripts/import-prospects-csv.py atalsolidrocks "C:/Users/bernh/Downloads/leads.csv" --dry
"""
from __future__ import annotations
import argparse, csv, sys, uuid
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

# Accept many header spellings -> canonical field
ALIASES = {
    "email": "email", "e-mail": "email", "mail": "email", "email address": "email", "e_mail": "email",
    "first_name": "first_name", "firstname": "first_name", "vorname": "first_name", "first name": "first_name",
    "name": "first_name",
    "company": "company", "firma": "company", "unternehmen": "company", "company name": "company",
    "organisation": "company", "organization": "company",
    "city": "city", "stadt": "city", "ort": "city", "standort": "city",
    "title": "title", "position": "title", "rolle": "title", "job title": "title",
    "state": "state", "bundesland": "state", "region": "state",
    "last_name": "last_name", "lastname": "last_name", "last name": "last_name",
    "nachname": "last_name", "surname": "last_name",
    "website": "website", "company website": "website", "domain": "website",
    "url": "website", "company domain": "website", "company url": "website",
}


def canon(header: str) -> str | None:
    return ALIASES.get((header or "").strip().lower())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile_slug")
    ap.add_argument("csv_path")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--unverified", action="store_true",
                    help="import with verified=false (default sets verified=true)")
    ap.add_argument("--niche", default=None,
                    help="set niche_slug on imported rows (e.g. saas_founder)")
    args = ap.parse_args()

    path = Path(args.csv_path)
    if not path.exists():
        sys.exit(f"file not found: {path}")

    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    # sniff delimiter
    try:
        dialect = csv.Sniffer().sniff(raw[:2048], delimiters=",;\t")
    except Exception:
        class dialect:  # noqa
            delimiter = ","
    reader = csv.DictReader(raw.splitlines(), dialect=dialect)
    colmap = {h: canon(h) for h in (reader.fieldnames or [])}
    if "email" not in colmap.values():
        sys.exit(f"no email column found. headers seen: {reader.fieldnames}")
    print(f"columns mapped: { {h:c for h,c in colmap.items() if c} }")

    rows, skipped_noemail, missing_merge = [], 0, 0
    seen = set()
    for r in reader:
        rec = {}
        for h, c in colmap.items():
            if c and r.get(h):
                rec[c] = r[h].strip()
        email = (rec.get("email") or "").lower().strip()
        if not email or "@" not in email:
            skipped_noemail += 1; continue
        if email in seen:
            continue
        seen.add(email)
        if not (rec.get("first_name") and rec.get("company")):
            missing_merge += 1
        rows.append(rec)

    print(f"parsed {len(rows)} unique-email rows  (skipped {skipped_noemail} without email, "
          f"{missing_merge} missing first_name/company)")
    if args.dry:
        for r in rows[:10]:
            print("  ", r)
        print("[dry] no writes."); return 0

    inserted = updated = failed = 0
    with httpx.Client(base_url=BASE, headers=H, timeout=30) as c:
        for rec in rows:
            email = rec["email"].lower()
            body = {
                "profile_slug": args.profile_slug,
                "email": email,
                "first_name": rec.get("first_name"),
                "last_name": rec.get("last_name"),
                "company": rec.get("company"),
                "title": rec.get("title"),
                "website": rec.get("website"),
                "city": rec.get("city"),
                "state": rec.get("state"),
                "verified": not args.unverified,
                "unsubscribed": False,
                "unsubscribe_token": str(uuid.uuid4()),
                "source": "csv_import",
            }
            if args.niche:
                body["niche_slug"] = args.niche
            ex = c.get(f"/prospects?profile_slug=eq.{args.profile_slug}"
                       f"&email=eq.{httpx.URL(email)}&select=id")
            try:
                found = ex.json() if ex.status_code == 200 else []
            except Exception:
                found = []
            if found:
                upd = {k: v for k, v in body.items() if k != "unsubscribe_token"}
                r = c.patch(f"/prospects?id=eq.{found[0]['id']}", json=upd,
                            headers={"Prefer": "return=minimal"})
                if r.status_code in (200, 204): updated += 1
                else: failed += 1; print(f"  ! update {email}: {r.status_code} {r.text[:120]}")
            else:
                r = c.post("/prospects", json=body, headers={"Prefer": "return=minimal"})
                if r.status_code in (200, 201, 204): inserted += 1
                else: failed += 1; print(f"  ! insert {email}: {r.status_code} {r.text[:120]}")

    print(f"\n=== import done ===  inserted={inserted}  updated={updated}  failed={failed}")
    print("Pool is loaded. Nothing sends until you start warmup for atalsolidrocks.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
