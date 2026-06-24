"""export-supabase.py — full backup of the live Supabase via the anon key
(works while RLS is off). Writes one JSON file per table + a schema summary, so
the DB can be rebuilt in a fresh project even if the old account is lost.

Run: py scripts/export-supabase.py
Output: out/supabase-export/<table>.json  + _schema.json + _manifest.txt
"""
from __future__ import annotations
import json, urllib.request, urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for l in (REPO / "sequences" / "supabase.env").read_text().splitlines():
    if "=" in l and not l.strip().startswith("#"):
        k, v = l.split("=", 1); env[k.strip()] = v.strip()
U = env["SUPABASE_URL"].rstrip("/"); K = env["SUPABASE_ANON_KEY"]
H = {"apikey": K, "Authorization": f"Bearer {K}"}

OUT = REPO / "out" / "supabase-export"
OUT.mkdir(parents=True, exist_ok=True)

# All tables the stack uses (from the codebase).
TABLES = ["profiles", "prospects", "sequences", "sequence_steps", "runs",
          "variants", "send_log", "replies"]


def fetch_all(table: str) -> list:
    """Page through a table 1000 rows at a time via Range headers."""
    rows = []
    step = 1000
    offset = 0
    while True:
        req = urllib.request.Request(
            f"{U}/rest/v1/{table}?select=*&order=id.asc&limit={step}&offset={offset}",
            headers=H)
        try:
            batch = json.loads(urllib.request.urlopen(req, timeout=60).read())
        except urllib.error.HTTPError as e:
            # some tables may not have an 'id' to order by; retry without order
            req2 = urllib.request.Request(
                f"{U}/rest/v1/{table}?select=*&limit={step}&offset={offset}", headers=H)
            try:
                batch = json.loads(urllib.request.urlopen(req2, timeout=60).read())
            except Exception as e2:
                print(f"  ! {table} offset {offset}: {e2}"); break
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < step:
            break
        offset += step
    return rows


def main() -> None:
    schema = {}
    manifest = []
    for t in TABLES:
        rows = fetch_all(t)
        (OUT / f"{t}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
        cols = sorted({k for r in rows for k in r.keys()}) if rows else []
        schema[t] = {"row_count": len(rows), "columns": cols}
        manifest.append(f"{t:16} rows={len(rows):6}  cols={len(cols)}")
        print(f"  + {t:16} {len(rows):6} rows -> {t}.json")
    (OUT / "_schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
    (OUT / "_manifest.txt").write_text("\n".join(manifest), encoding="utf-8")
    print("\nschema summary:")
    print("\n".join(manifest))
    print(f"\nexport written to {OUT}")


if __name__ == "__main__":
    main()
