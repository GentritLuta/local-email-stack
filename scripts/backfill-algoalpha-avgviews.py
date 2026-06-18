#!/usr/bin/env python
"""One-off (re-runnable) backfill: populate enriched_context.avg_views_10 for
existing AlgoAlpha prospects that were scraped BEFORE the offer formula started
capturing last-10-video average views at scrape time.

Why: the AlgoAlpha offer (10 USD per 1,000 of the last-10-video average, +30%
commission) personalises the per-video number off enriched_context.avg_views_10.
Prospects scraped before 2026-06-18 have no avg_views_10, so their replies fall
back to a generic offer. This walks their YouTube channels once and fills it in,
instead of waiting for the next full re-scrape.

Reuses the proven youtube_worker functions (KeyPool, resolve_channel_async,
avg_views_last_10) so the resolution / quota-rotation logic is identical to the
live scraper. Resolves off enriched_context.channel_handle (the full 24-char UC
id), NOT source_url/website (those are truncated by a column limit).

  py scripts/backfill-algoalpha-avgviews.py            # run for real
  py scripts/backfill-algoalpha-avgviews.py --dry      # resolve only, no DB write
"""
import asyncio, json, sys, urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))

import httpx  # noqa: E402
from youtube_worker import KeyPool, resolve_channel_async, avg_views_last_10  # noqa: E402
from youtube_scraper import load_api_keys  # noqa: E402

DRY = "--dry" in sys.argv
PROJECT = "ccmqkljsjiuavpydbkva"


def _env(path: Path) -> dict:
    out = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("\r")
    return out


_TOK = _env(REPO / "sequences" / "supabase.env")["SUPABASE_ACCESS_TOKEN"]


def mq(sql: str):
    rq = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{PROJECT}/database/query",
        data=json.dumps({"query": sql}).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {_TOK}",
                 "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 Chrome/123"})
    return json.loads(urllib.request.urlopen(rq, timeout=90).read().decode())


def fetch_targets() -> list[dict]:
    """AlgoAlpha prospects with a YouTube channel handle but no avg_views_10 yet."""
    rows = mq("""select id, enriched_context->>'channel_handle' handle
      from prospects
      where profile_slug='algoalpha'
        and (enriched_context->>'channel_handle') is not null
        and (enriched_context->>'avg_views_10') is null""")
    return [r for r in rows if (r.get("handle") or "").strip()]


async def worker(name, queue, pool, client, results, stats):
    while True:
        try:
            row = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        pid, handle = row["id"], row["handle"].strip()
        try:
            ch = await resolve_channel_async(client, pool, handle)
        except Exception as e:
            if "quota" in str(e).lower():
                stats["quota_blocked"] += 1
            else:
                stats["resolve_err"] += 1
            queue.task_done(); continue
        if not ch:
            stats["no_channel"] += 1
            queue.task_done(); continue
        try:
            avg = await avg_views_last_10(client, pool, ch)
        except Exception:
            avg = None
        if avg is None:
            stats["no_avg"] += 1
        else:
            results[pid] = avg
            stats["got_avg"] += 1
        queue.task_done()


def write_batch(pairs: list[tuple[str, int]]):
    """UPDATE enriched_context.avg_views_10 for a batch via VALUES join."""
    if not pairs:
        return
    vals = ",".join(f"('{pid}', {avg})" for pid, avg in pairs)
    mq(f"""update prospects p
        set enriched_context = jsonb_set(
              coalesce(p.enriched_context,'{{}}'::jsonb),
              '{{avg_views_10}}', to_jsonb(v.avg::int))
        from (values {vals}) as v(id, avg)
        where p.id = v.id::uuid""")


async def main():
    targets = fetch_targets()
    keys = load_api_keys()
    print(f"targets={len(targets)}  api_keys={len(keys)}  dry={DRY}")
    if not targets:
        print("nothing to backfill — all AlgoAlpha YT prospects already have avg_views_10")
        return
    pool = KeyPool(keys)
    queue = asyncio.Queue()
    for t in targets:
        queue.put_nowait(t)
    results: dict[str, int] = {}
    stats = {"got_avg": 0, "no_avg": 0, "no_channel": 0,
             "resolve_err": 0, "quota_blocked": 0}
    async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
        await asyncio.gather(*[worker(f"w{i}", queue, pool, client, results, stats)
                               for i in range(8)])
    print("resolve stats:", stats)
    print(f"resolved avg_views_10 for {len(results)} prospects")
    if results:
        sample = sorted(results.values())
        print(f"  avg range: min={sample[0]:,}  median={sample[len(sample)//2]:,}  max={sample[-1]:,}")
    if DRY:
        print("DRY run — no DB writes")
        return
    pairs = list(results.items())
    for i in range(0, len(pairs), 50):
        write_batch(pairs[i:i + 50])
        print(f"  wrote {min(i + 50, len(pairs))}/{len(pairs)}")
    # verify
    have = mq("""select count(*) c from prospects
      where profile_slug='algoalpha' and (enriched_context->>'avg_views_10') is not null""")[0]["c"]
    print(f"DONE — AlgoAlpha prospects now carrying avg_views_10: {have}")


if __name__ == "__main__":
    asyncio.run(main())
