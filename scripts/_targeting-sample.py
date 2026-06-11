"""Pull a representative Stichprobe of the prospects we ACTUALLY email (aureon,
verified, not unsubscribed, with a website), spread across lead sources, for a
deep ICP / targeting audit."""
import json, urllib.request
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
def get(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL+p, headers=H), timeout=90).read())

rows = []
for off in range(0, 20000, 1000):
    b = get(f"prospects?profile_slug=eq.aureon&verified=eq.true&unsubscribed=eq.false"
            f"&select=email,first_name,company,title,website,source_url,city,state&limit=1000&offset={off}")
    rows += b
    if len(b) < 1000: break
rows = [r for r in rows if (r.get("website") or r.get("source_url"))]
print(f"verified, sendable, with-website aureon prospects: {len(rows)}")

# group by source, take a spread (representative across sources)
by_src = defaultdict(list)
for r in rows:
    by_src[r.get("source_url") or "(none)"] += [r]
print(f"distinct sources: {len(by_src)}\n")

sample = []
for src, items in sorted(by_src.items(), key=lambda kv: -len(kv[1])):
    take = 3 if len(items) >= 40 else (2 if len(items) >= 8 else 1)
    sample += items[:take]
sample = sample[:16]

print("=== STICHPROBE (16) ===")
for i, r in enumerate(sample, 1):
    print(f'{i}. {r.get("email")} | name={r.get("first_name") or "-"} | co={r.get("company") or "-"} '
          f'| title={r.get("title") or "-"} | site={r.get("website") or "-"} '
          f'| {r.get("city") or "-"},{r.get("state") or "-"} | src={r.get("source_url") or "-"}')
