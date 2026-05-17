"""signals — derive high-level booleans from the enriched profile.

These get fed to the bandit-scorer's lead-quality classifier and to the
personalization LLM (so the prompt can say 'founder=true, recent_press=true,
hiring=true' compactly).
"""

from __future__ import annotations

from datetime import datetime


def compute(profile: dict) -> dict:
    core = profile.get("core") or {}
    web = profile.get("web") or {}
    pages = web.get("pages") or {}
    social = profile.get("social") or {}
    external = profile.get("external") or {}
    infra = profile.get("infra") or {}

    is_founder = _is_founder(core, pages, social)
    is_solo = _is_solo(pages, social)
    team_bucket = _team_size_bucket(pages)
    founded_year = _founded_year(infra, pages)
    growth = _growth_signals(pages, external, infra)
    freshness = _freshness(social, external)

    return {
        "is_founder": is_founder,
        "is_solo_operator": is_solo,
        "approx_team_size_bucket": team_bucket,
        "founded_year_estimate": founded_year,
        "growth_signals": growth,
        "freshness_score": freshness,
        # icp_match_score is filled in by bandit-scorer's /lead/score endpoint, not here
    }


def _is_founder(core: dict, pages: dict, social: dict) -> bool:
    title = (core.get("bio") or "") + " " + (social.get("linkedin", {}).get("bio") or "")
    title = title.lower()
    return any(k in title for k in ["founder", "co-founder", "ceo", "owner", "principal", "managing director"])


def _is_solo(pages: dict, social: dict) -> bool:
    team_page = pages.get("team") or {}
    members = team_page.get("members") or []
    if members and len(members) == 1:
        return True
    careers = pages.get("careers") or {}
    if careers.get("open_roles"):
        return False
    return len(members) <= 1


def _team_size_bucket(pages: dict) -> str:
    team_page = pages.get("team") or {}
    n = len(team_page.get("members") or [])
    if n == 0:
        return "unknown"
    if n <= 2:   return "1-2"
    if n <= 10:  return "3-10"
    if n <= 50:  return "11-50"
    if n <= 200: return "51-200"
    return "200+"


def _founded_year(infra: dict, pages: dict) -> int | None:
    whois = infra.get("whois") or {}
    created = whois.get("created")
    if created:
        try:
            return int(created[:4])
        except Exception:
            pass
    arc = infra.get("archive_org") or {}
    first = arc.get("first_seen")
    if first:
        try:
            return int(str(first)[:4])
        except Exception:
            pass
    return None


def _growth_signals(pages: dict, external: dict, infra: dict) -> list[str]:
    out: list[str] = []
    if (pages.get("careers") or {}).get("open_roles"):
        out.append("hiring")
    if external.get("press") or external.get("news_mentions"):
        out.append("recent_press")
    if (pages.get("pricing") or {}).get("tiers"):
        out.append("has_pricing_page")
    if (pages.get("blog") or {}).get("recent_posts"):
        out.append("active_blog")
    dns = infra.get("dns") or {}
    if dns.get("mx_provider") in {"Google Workspace", "Microsoft 365"}:
        out.append("paid_email_infra")
    return out


def _freshness(social: dict, external: dict) -> float:
    # Crude: more populated platforms + more news = fresher
    score = 0.0
    for p in social.values():
        if p and (p.get("followers") or p.get("posts")):
            score += 0.1
    score += min(0.4, 0.05 * len((external.get("news_mentions") or [])))
    return round(min(score, 1.0), 2)
