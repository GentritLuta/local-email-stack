"""hackernews_hiring — find founders posting in HN 'Who is hiring' + 'Show HN'.

Public HN API, no key. Pulls recent monthly threads and uses Qwen 32B to extract
{company, role, founder_name, contact} from each top-level comment.

Config:
  months_back:   int (default 6)
  keywords:      [list]  (e.g. ["seed", "Series A", "founding engineer"])
  limit:         int
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.hackernews_hiring")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:32b-instruct-q4_K_M")


@register("hackernews_who_is_hiring")
class HackerNewsHiringEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        months_back = int(config.get("months_back", 6))
        kws = [k.lower() for k in config.get("keywords") or []]
        limit = int(config.get("limit", 100))

        # Find the "Who is hiring?" monthly thread IDs via the HN search API (Algolia).
        cutoff = datetime.now(timezone.utc) - timedelta(days=30 * months_back)
        results: dict[str, Lead] = {}

        async with httpx.AsyncClient(timeout=60) as c:
            sr = await c.get(
                "https://hn.algolia.com/api/v1/search",
                params={"query": "Ask HN: Who is hiring?", "tags": "story",
                        "numericFilters": f"created_at_i>{int(cutoff.timestamp())}",
                        "hitsPerPage": 12},
            )
            if sr.status_code != 200:
                logger.warning("HN search returned %s", sr.status_code)
                return []
            thread_ids = [h["objectID"] for h in sr.json().get("hits", [])]

            for tid in thread_ids:
                try:
                    tr = await c.get(f"https://hn.algolia.com/api/v1/items/{tid}")
                    if tr.status_code != 200:
                        continue
                    children = tr.json().get("children", []) or []
                    for ch in children:
                        text = ch.get("text") or ""
                        if not text or len(text) < 80:
                            continue
                        tlow = text.lower()
                        if kws and not any(k in tlow for k in kws):
                            continue
                        # Extract structured data via LLM
                        extracted = await _llm_extract(c, text)
                        if not extracted or not extracted.get("company"):
                            continue
                        key = extracted["company"].lower().strip()
                        if key in results:
                            continue
                        results[key] = Lead(
                            source="hackernews_who_is_hiring",
                            source_id=str(ch.get("id")),
                            handle="",
                            display_name=extracted.get("founder_name", ""),
                            bio=extracted.get("role", ""),
                            url=extracted.get("website") or f"https://news.ycombinator.com/item?id={ch.get('id')}",
                            extra={
                                "company": extracted.get("company"),
                                "stage": extracted.get("stage"),
                                "contact_hint": extracted.get("contact"),
                                "thread_id": tid,
                                "comment_text_excerpt": text[:1000],
                            },
                        )
                        if len(results) >= limit:
                            break
                except Exception as ex:
                    logger.exception("HN thread %s failed: %s", tid, ex)
                if len(results) >= limit:
                    break

        return list(results.values())[:limit]


async def _llm_extract(client: httpx.AsyncClient, text: str) -> dict:
    prompt = (
        "Extract structured data from this 'Who is hiring' comment. "
        "Return JSON with keys: company, role, founder_name, website, contact, stage. "
        "Use empty string if unknown. Do not invent.\n\n"
        f"Comment:\n{text[:3000]}"
    )
    try:
        r = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
            },
            timeout=45,
        )
        import json as _json
        return _json.loads(r.json()["message"]["content"])
    except Exception:
        return {}
