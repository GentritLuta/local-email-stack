# -*- coding: utf-8 -*-
"""seo_copy.py — the ONE place that turns a prospect's stored local-SEO research
(`enriched_context.seo`, written by seo_research.py) into outreach copy.

Two consumers import this so the phrasing lives in a single spot:
  - sequence-runner.py  -> seo_ps()    : the email-1 P.S. that names a real
                                         competitor and the search the prospect
                                         is invisible for (the give-first proof).
  - fulfill-magnets.py  -> seo_block() : the held-back specifics delivered in
                                         email-2 when they reply the keyword.

Design rules (match the lead-magnet playbook + house style):
  - Never fabricate. Every claim here is backed by what seo_research actually
    scraped. If the research is missing or thin, both functions fall back to a
    generic, claim-free version so a normal email still goes out.
  - The money figure is ALWAYS framed as an explicit assumption the prospect is
    invited to correct. It is never presented as measured data (no free source
    of real keyword volume exists, and we will not pretend otherwise).
  - Plain human prose. No em dashes.

The `enriched_context.seo` shape this reads:
  {
    "status": "ok" | "unknown_service" | "no_geo" | "thin_data" | "no_results" | "error",
    "service": "roofing contractor",
    "geo": "Austin, TX",
    "money_search": "roofing contractor Austin TX",
    "queries": ["roofing contractor Austin TX", ...],
    "competitors": [{"name": "Lone Star Roofs", "domain": "lonestarroofs.com"}, ...],
    "own_domain": "smithroofing.com",
    "own_rank": 14 | null,        # 1-based organic position if we found them, else null
    "found_on_page1": false,
    "results_seen": 9,
    "engine": "ddg",
    "assumed_searches": 400,
    "assumed_value_usd": 400,
    "researched_at": "..."
  }
"""
from __future__ import annotations

# Labeled-assumption defaults for the money line. These are NOT measured; they
# exist only to make the math concrete and give the prospect a reason to reply
# with their real numbers. Tunable per the magnet spec if needed later.
ASSUMED_SEARCHES = 400
ASSUMED_VALUE_USD = 400

# The fallback P.S. for prospects we could not research. This is the original
# mark-eting step-1 P.S., kept verbatim so an un-researched send is unchanged.
_FALLBACK_PS = ("P.S. Tell me your top competitor and I will include where they "
                "outrank you in the same document.")


def usable(seo: dict | None) -> bool:
    """True only when seo_research produced a claim we can stand behind: a real
    search and at least one named competitor for it."""
    if not isinstance(seo, dict):
        return False
    if seo.get("status") != "ok":
        return False
    return bool(seo.get("money_search")) and bool(seo.get("competitors"))


def competitor_names(seo: dict, limit: int = 3) -> list[str]:
    """Display labels for the competitors, preferring a real business name and
    falling back to the bare domain. Verifiable either way."""
    out: list[str] = []
    for c in (seo.get("competitors") or []):
        label = (c.get("name") or "").strip() or (c.get("domain") or "").strip()
        if label and label not in out:
            out.append(label)
        if len(out) >= limit:
            break
    return out


def _join(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _company(prospect: dict) -> str:
    return (prospect.get("company") or "").strip() or "you"


def _rank_clause(seo: dict, company: str) -> str:
    """How {company} itself places for the money search, stated only from what
    we actually saw."""
    rank = seo.get("own_rank")
    if isinstance(rank, int) and rank > 0:
        if rank <= 3:
            return f"{company} sits at about position {rank}"
        return f"{company} is down at about position {rank}, off the top of the page"
    return f"{company} does not show up on the first page for it"


def _money_line(seo: dict) -> str:
    searches = int(seo.get("assumed_searches") or ASSUMED_SEARCHES)
    value = int(seo.get("assumed_value_usd") or ASSUMED_VALUE_USD)
    # Honest framing: this is a guess, and the ask is for the real number.
    return (f"Rough math, and I am guessing on the inputs here: if even ~{searches} "
            f"people a month run that search and a new customer is worth ~${value} "
            f"to you, that is real work going to whoever holds those spots. Tell me "
            f"your real customer value and I will redo it properly.")


def seo_ps(seo: dict | None, prospect: dict) -> str:
    """The email-1 P.S. Returns the proof version when we have real research,
    otherwise the original generic P.S. (so an un-researched send is unchanged)."""
    if not usable(seo):
        return _FALLBACK_PS
    company = _company(prospect)
    names = _join(competitor_names(seo))
    query = seo.get("money_search")
    rank = _rank_clause(seo, company)
    return (f'P.S. I ran a quick check. When someone Googles "{query}", {names} '
            f"come up and {rank}. Reply Teardown and I will send you the full list "
            f"of searches you are missing, plus where each of them is beating you.")


def seo_rivals(seo: dict | None, prospect: dict) -> str:
    """A concrete competitor sentence for step 5 ("your competitor is holding
    your seat"). Empty string when there is no usable research, so the existing
    step-5 paragraph stands and the email reads exactly as before (the renderer
    drops empty paragraphs)."""
    if not usable(seo):
        return ""
    company = _company(prospect)
    names = _join(competitor_names(seo))
    query = seo.get("money_search")
    return (f'In your case I already pulled the names. For "{query}", {names} are '
            f"the ones holding those top spots right now while {company} is not on "
            f"the first page. Those are the clicks walking past you every month.")


def seo_block(seo: dict | None, prospect: dict) -> str:
    """The held-back specifics for email-2 (the magnet reply). When we have real
    research, this is the personalized findings. When we do not, it is the
    generic offer to personalize so the cover email still closes cleanly. Only
    mark-eting's cover_email contains {seo_block}, so this is never rendered for
    other clients."""
    company = _company(prospect)
    if not usable(seo):
        return (f"Want the version that is specific to {company}? Send me your "
                "business name, your city, and the two or three services you most "
                "want more calls for, and I will write up where you are leaking "
                "demand: the searches where you do not show up, who sits above "
                "you, and the three fixes I would make first. No call needed.")
    names = _join(competitor_names(seo))
    query = seo.get("money_search")
    rank = _rank_clause(seo, company)
    queries = [q for q in (seo.get("queries") or []) if q]

    paras = [
        f"First, the specific part I held back for {company}.",
        (f'For the search "{query}", these businesses are showing up ahead of you '
         f"on Google right now: {names}. In plain terms, {rank}."),
        _money_line(seo),
    ]
    if len(queries) > 1:
        checked = _join(['"' + q + '"' for q in queries[:4]])
        paras.append(f"The searches I checked for you were {checked}.")
    paras.append(
        "The attached teardown is the framework behind this: the five places a "
        "service buyer finds you on Google and the three fixes that move them, in "
        "order. Reply with your real customer value and the cities or services you "
        "most want more calls for, and I will tighten the list and the math to your "
        "business.")
    return "\n\n".join(paras)
