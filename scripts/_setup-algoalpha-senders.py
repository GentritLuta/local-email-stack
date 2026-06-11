# -*- coding: utf-8 -*-
"""_setup-algoalpha-senders.py — populate algoalpha profile with 12 sending
subdomains + 12 paired personas, then leave provisioning to domain_autoprovision.

Layout: 3 localparts x 4 TLDs = 12 subdomains, spread across owned algoalpha
TLDs to diversify sending reputation. Keeps .com/.net/.org as clean brand
domains. Reply-to converges to partners@algoalpha.io.

Idempotent: rewrites from_domains + personas wholesale from the spec below.
Does NOT activate the profile and does NOT push DNS — that's the next step.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sequences"))
from profile_lib import load_profile, save_profile  # noqa

REPO = Path(__file__).resolve().parent.parent

# 12 distinct subdomains of tryalgoalpha.com (the real Cloudflare zone), mirroring
# aureon's 12-subdomain-of-one-root pattern. DNS pushable via CF_API_TOKEN_ALGOALPHA.
ROOT = "tryalgoalpha.com"
SUBDOMAINS = ["hello", "team", "mail", "hi", "reach", "connect",
              "partners", "growth", "desk", "hub", "news", "send"]
# Replies must converge to the ONE mailbox imap-poll.py monitors, else they vanish.
# imap-poll only watches info@aureonglobal.de (and reply-autodraft drafts from there).
REPLY_TO = "info@aureonglobal.de"

# 12 partnership-team personas (realistic names, crypto/fintech-plausible)
PERSONA_NAMES = [
    ("tomas", "Tomás Silva"), ("mara", "Mara Costa"), ("liam", "Liam Walsh"),
    ("nina", "Nina Berg"), ("diego", "Diego Reyes"), ("sara", "Sara Klein"),
    ("kai", "Kai Andersen"), ("ana", "Ana Ferreira"), ("noah", "Noah Bennett"),
    ("lena", "Lena Vogel"), ("marco", "Marco Bianchi"), ("ivy", "Ivy Chen"),
]

VOICE = {
    "register": "creator-partnerships-direct",
    "quirks": ["short sentences", "concrete numbers", "no fluff"],
    "avoid": ["apostrophes", "em-dashes", "typographic quotes", "exclamation marks", "emojis"],
}


def build_from_domains():
    doms = []
    for sub in SUBDOMAINS:
        doms.append({
            "domain": f"{sub}.{ROOT}",
            "resend_domain_id": "",
            "verified_at": None,
            "warmup": {
                "enabled": True, "current_day": 1, "started_at": None,
                "ramp_curve": "snowball_v1", "max_daily_sends": 50,
                "reputation": {"bounce_rate_7d": 0.0, "complaint_rate_7d": 0.0,
                               "delivered_7d": 0, "last_check": None},
            },
        })
    return doms


def build_personas():
    personas = []
    domains = [f"{sub}.{ROOT}" for sub in SUBDOMAINS]
    for (slug, full), domain in zip(PERSONA_NAMES, domains):
        local = slug  # persona first-name as localpart, e.g. tomas@hello.tryalgoalpha.com
        personas.append({
            "slug": slug,
            "from_name": f"{full.split()[0]} at AlgoAlpha",
            "from_addr": f"{local}@{domain}",
            "reply_to": REPLY_TO,
            "title": "Creator Partnerships, AlgoAlpha",
            "voice": VOICE,
            "signature": f"{full}\nCreator Partnerships, AlgoAlpha\nalgoalpha.io",
            "full_name": full,
        })
    return personas


def main():
    p = load_profile("algoalpha")
    p["relay"]["from_domains"] = build_from_domains()
    p["personas"] = build_personas()
    # keep active False until DNS verified + warmup task created
    p["active"] = False
    save_profile(p)
    print(f"algoalpha: {len(p['relay']['from_domains'])} from_domains, "
          f"{len(p['personas'])} personas written. active={p['active']}")
    for d in p["relay"]["from_domains"]:
        print("  ", d["domain"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
