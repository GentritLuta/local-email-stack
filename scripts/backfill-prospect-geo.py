"""backfill-prospect-geo.py — derive US state from each Aureon prospect's phone
area code and write it to prospects.state where it is missing.

State is EXACT from area code (each geographic NANP code sits in one state), so
this is safe. City is intentionally NOT written (an area code spans a whole
metro - e.g. 317 = the Indianapolis metro incl. Greenwood - so a per-city guess
would mislabel suburb leads). Metro is shown here (derived) for reporting and
can be derived on the fly anywhere from the area code.

Usage:
  py scripts/backfill-prospect-geo.py --dry     # preview, write nothing
  py scripts/backfill-prospect-geo.py           # apply
"""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from area_codes import state_for, metro_for      # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PROFILE = "aureon"
CHUNK = 40

env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def get(path):
    req = urllib.request.Request(URL + path, headers=HDR)
    return json.loads(urllib.request.urlopen(req, timeout=90).read())


def patch(path, body):
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode(), method="PATCH",
                                 headers={**HDR, "Content-Type": "application/json",
                                          "Prefer": "return=minimal"})
    urllib.request.urlopen(req, timeout=60).read()


def area(phone):
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d[:3] if len(d) >= 10 else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    rows = []
    for off in range(0, 20000, 1000):
        b = get(f"prospects?profile_slug=eq.{PROFILE}&select=id,phone,state&limit=1000&offset={off}")
        rows += b
        if len(b) < 1000:
            break
    print(f"aureon prospects: {len(rows)}")

    targets = []            # (id, state)
    by_state = Counter()
    by_metro = Counter()
    unresolved_ac = Counter()
    have_state = sum(1 for r in rows if (r.get("state") or "").strip())
    for r in rows:
        if (r.get("state") or "").strip():
            continue
        ac = area(r.get("phone"))
        if not ac:
            unresolved_ac["(no phone)"] += 1
            continue
        st = state_for(ac)
        if not st:
            unresolved_ac[ac] += 1          # toll-free / unknown -> skip
            continue
        targets.append((r["id"], st))
        by_state[st] += 1
        by_metro[metro_for(ac) or f"{st} (other)"] += 1

    print(f"state present before : {have_state}/{len(rows)}")
    print(f"resolvable to a state: {len(targets)}")
    print(f"would become state-covered: {have_state + len(targets)}/{len(rows)} "
          f"({100*(have_state+len(targets))//max(len(rows),1)}%)")
    print("\nstate distribution (to write):")
    for s, c in by_state.most_common():
        print(f"   {s}  {c}")
    print("\nmetro distribution (derived, for reporting):")
    for m, c in by_metro.most_common(15):
        print(f"   {c:4}  {m}")
    skipped = sum(unresolved_ac.values())
    if skipped:
        print(f"\nskipped (no phone / toll-free / non-geo): {skipped}")
        for ac, c in unresolved_ac.most_common(8):
            print(f"   {ac}: {c}")

    if args.dry:
        print("\n[dry] nothing written.")
        return 0

    # apply: PATCH grouped by state, chunked by id
    from collections import defaultdict
    ids_by_state = defaultdict(list)
    for pid, st in targets:
        ids_by_state[st].append(pid)
    written = 0
    for st, ids in ids_by_state.items():
        for i in range(0, len(ids), CHUNK):
            chunk = ids[i:i + CHUNK]
            idlist = ",".join(chunk)
            patch(f"prospects?id=in.({idlist})", {"state": st})
            written += len(chunk)
        print(f"   wrote state={st} -> {len(ids)} rows")
    print(f"\nbackfilled state on {written} prospects.")

    # verify
    after = get(f"prospects?profile_slug=eq.{PROFILE}&state=not.is.null&select=id", )
    print(f"verify: state now present on {len(after)} aureon prospects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
