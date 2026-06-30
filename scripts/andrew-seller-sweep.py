#!/usr/bin/env python
"""Zero-spend seller sweep for Andrew Barr (@properties Indianapolis).

Runs the free source-seller-leads engine across Andrew's 15 territory zips,
dedupes, and writes out/andrew_fsbo_leads.csv. FSBO rows are reachable through
the listing's own reply channel (invited solicitation). absentee-owner rows are
mailing-address-only (direct-mail lane, not the zero-spend cold lane).

    python scripts/andrew-seller-sweep.py
"""
import subprocess, json, csv, sys, os

ZIPS = ["46011", "46012", "46013", "46016", "46017", "46055", "46060", "46062",
        "46064", "46202", "46220", "46226", "46236", "46250", "46256"]
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    seen, rows = set(), []
    for z in ZIPS:
        try:
            out = subprocess.run(
                [sys.executable, os.path.join("scripts", "source-seller-leads.py"),
                 z, "--limit", "25", "--json"],
                capture_output=True, text=True, timeout=140, cwd=REPO)
            data = json.loads(out.stdout or "{}")
        except Exception as e:
            print(f"{z}: ERROR {e}", flush=True)
            continue
        new = 0
        for L in data.get("leads", []):
            key = L.get("source") or (str(L.get("address", "")) + str(L.get("signal", "")))
            if key in seen:
                continue
            seen.add(key)
            L["zip_searched"] = z
            rows.append(L)
            new += 1
        print(f"{z}: {data.get('count', 0)} leads ({new} new), coverage={data.get('coverage')}",
              flush=True)

    os.makedirs(os.path.join(REPO, "out"), exist_ok=True)
    out_csv = os.path.join(REPO, "out", "andrew_fsbo_leads.csv")
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["zip", "signal", "address", "owner_name", "contact_phone",
                    "contact_email", "source", "confidence"])
        for L in rows:
            w.writerow([L.get("zip_searched"), L.get("signal"), L.get("address"),
                        L.get("owner_name"), L.get("contact_phone"),
                        L.get("contact_email"), L.get("source"), L.get("confidence")])

    fsbo = sum(1 for L in rows if L.get("signal") == "fsbo")
    print(f"\nTOTAL unique: {len(rows)} | FSBO (reply-via-listing): {fsbo} "
          f"| absentee (mail-ready): {len(rows) - fsbo}")
    print(f"CSV -> {out_csv}")


if __name__ == "__main__":
    main()
