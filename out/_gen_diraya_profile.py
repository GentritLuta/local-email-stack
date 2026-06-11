# -*- coding: utf-8 -*-
"""One-shot generator: rebuild profiles/diraya.json as a 5-domain x 12-subdomain
(= 60 sending identities) cold-email profile, mirroring the Aureon engine
structure. Each subdomain gets its own distinct team persona. CTA -> Calendly,
all links land on diraya.ca. Idempotent: overwrites diraya.json from scratch
using the fixed inputs below.

Run: py out/_gen_diraya_profile.py
"""
import json
from pathlib import Path

ROOT = Path(r"C:\Users\bernh\local-email-stack")
PROFILE = ROOT / "profiles" / "diraya.json"

# The 5 sending root domains (from Spaceship). Links/landing stay on diraya.ca.
DOMAINS = [
    "cleardiraya.com",
    "diraya-agency.shop",
    "diraya.biz",
    "dirayaget.com",
    "diraya-marketing.shop",
]

# 2 subdomain labels per root domain -> 10 sending subdomains total.
SUBLABELS = [
    "hello", "team",
]

# 60 distinct team first-names (global team: Algeria / Qatar / Canada + intl).
# One per (domain, sublabel) slot, assigned in order. All sign as Diraya team,
# reply-to info@diraya.ca. Founder Mohammed leads the rotation.
NAMES = [
    "Mohammed", "Amine", "Yacine", "Khalil", "Sami", "Omar",
    "Nadia", "Lina", "Sara", "Hana", "Yasmin", "Rania",
    "Karim", "Bilal", "Tariq", "Rayan", "Adam", "Zaid",
    "Leila", "Maya", "Salma", "Noor", "Dina", "Aya",
    "Hamza", "Ilyas", "Anis", "Walid", "Fares", "Nabil",
    "Imane", "Sofia", "Yara", "Mariam", "Sana", "Amira",
    "Ethan", "Liam", "Noah", "Owen", "Lucas", "Mason",
    "Emma", "Olivia", "Chloe", "Ava", "Zoe", "Mila",
    "Idris", "Reda", "Ayoub", "Mehdi", "Sufyan", "Bashir",
    "Layla", "Ines", "Asma", "Farah", "Hiba", "Nour",
]

CALENDLY = "https://calendly.com/amoura-ma-diraya/30min"

def fresh_domain_entry(subdomain: str) -> dict:
    return {
        "domain": subdomain,
        "resend_domain_id": "",
        "verified_at": None,
        "warmup": {
            "enabled": True,
            "current_day": 0,
            "started_at": None,
            "ramp_curve": "snowball_v1",
            "max_daily_sends": 50,
            "reputation": {"bounce_rate_7d": 0.0, "complaint_rate_7d": 0.0,
                           "delivered_7d": 0, "last_check": None},
        },
    }

def persona(name: str, subdomain: str, label: str) -> dict:
    slug = f"{name.lower()}-{label}"
    return {
        "slug": slug,
        "from_name": f"{name} from Diraya",
        "from_addr": f"{name.lower()}@{subdomain}",
        "reply_to": "info@diraya.ca",
        "title": "Diraya Inc",
        "voice": {
            "register": "founder-direct",
            "quirks": ["short sentences", "concrete numbers", "no buzzwords"],
            "avoid": ["marketing language", "exclamation marks", "emojis", "em-dashes"],
        },
        "signature": f"{name}\nDiraya Inc",
    }

from_domains, personas = [], []
slot = 0
for root in DOMAINS:
    for label in SUBLABELS:
        sub = f"{label}.{root}"
        name = NAMES[slot]
        from_domains.append(fresh_domain_entry(sub))
        personas.append(persona(name, sub, label))
        slot += 1

expected = len(DOMAINS) * len(SUBLABELS)
assert slot == expected, (slot, expected)
assert len({p["from_addr"] for p in personas}) == expected, "duplicate from_addr"
assert len({p["slug"] for p in personas}) == expected, "duplicate persona slug"

profile = {
    "slug": "diraya",
    "name": "Diraya — Custom AI engineering (seed-Series-B), 5-domain x 2-subdomain cold outbound",
    "created_at": "2026-05-31",
    "rebuilt_at": "2026-06-02",
    "active": False,
    "company": {
        "legal_name": "Diraya Inc",
        "registration_number": "1603166-8",
        "country": "Canada",
        "website": "https://diraya.ca",
        "root_domain": "diraya.ca",
        "office_address": "500 Sedgebrook Way, Canada",
        "signer": "Mohammed El Amine Amoura, Director (and incorporator)",
        "notices_email": "info@diraya.ca",
        "target_market": "Seed to Series B SaaS / health tech / fintech startups and scaleups needing AI engineering",
    },
    "_note": ("Rebuilt 2026-06-02 to 5 sending root domains x 2 subdomains = 10 "
              "sending identities, each a distinct team persona. SENDING domains "
              "are the Spaceship-registered roots; all in-email links + the CTA land "
              "on diraya.ca. CTA button -> Calendly (amoura-ma-diraya/30min). Positive "
              "replies + notifications route to info@diraya.ca. NOT yet sending — needs "
              "Resend domain provisioning (RESEND_FULL_ACCESS_API_KEY present) + DNS "
              "published on the 5 roots (ClouDNS x2 + Spaceship x3; no API token on disk "
              "for either — DNS step needs operator action) + warmup ramp."),
    "relay": {
        "backend": "resend",
        "resend_region": "us-east-1",
        "resend_api_key": "",
        "_note": "Full-access key = RESEND_FULL_ACCESS_API_KEY in sequences/hostinger.env. us-east-1: global English-speaking ICP.",
        "from_domains": from_domains,
    },
    "personas": personas,
    "rotation": {
        "strategy": "round_robin_by_persona",
        "max_sends_per_persona_per_day": 30,
        "min_seconds_between_sends_same_persona": 180,
    },
    "send_ramp": {"started_at": None},
    "warmup": {
        "enabled": True,
        "warmup_targets": [],
        "ramp_curve": "snowball_v1",
        "real_send_mix": [
            {"until_day": 14, "warmup_pct": 80},
            {"until_day": 30, "warmup_pct": 30},
            {"until_day": 45, "warmup_pct": 10},
            {"until_day": 9999, "warmup_pct": 5},
        ],
        "auto_pause_thresholds": {"bounce_rate": 0.05, "complaint_rate": 0.003},
        "reputation": {"bounce_rate_7d": 0, "complaint_rate_7d": 0, "delivered_7d": 0, "last_check": None},
        "started_at": None,
        "current_day": 0,
        "advance_only_mode": True,
    },
    "ramp_curve_snowball_v1": [
        {"from_day": 1, "daily": 15},
        {"from_day": 8, "daily": 25},
        {"from_day": 15, "daily": 35},
        {"from_day": 22, "daily": 50},
    ],
    "send_window": {
        "weekdays_only": True,
        "local_hour_start": 8,
        "local_hour_end": 17,
        "default_timezone": "America/Toronto",
        "target_audience_note": "Global ICP. Default America/Toronto (client HQ) for unresolved; per-prospect city lookup overrides. 08:00-17:00 recipient local.",
    },
    "brand": {
        "wordmark": "DIRAYA",
        "site": "diraya.ca",
        "cta_url": CALENDLY,
        "tagline": "The Future Starts Now. Custom AI engineering for ambitious startups.",
        "font_stack": "'Kanit', sans-serif",
        "font_url": "https://fonts.googleapis.com/css2?family=Kanit:wght@400;500;600;700;800&display=swap",
        "colors": {
            "accent": "#FF6B00", "accent_2": "#0A0A0A", "text": "#0A0A0A",
            "text_2": "#454545", "muted": "#8A8A8A", "bg_page": "#FFFFFF",
            "bg_card": "#FFFFFF", "rule": "#E8E8E8",
        },
        "unsubscribe_url_template": "https://gentritluta.github.io/local-email-stack/unsubscribe/diraya.html?t={token}",
        "legal": {
            "company_name": "Diraya Inc",
            "address_lines": ["Diraya Inc", "500 Sedgebrook Way, Canada"],
            "contact_email": "info@diraya.ca",
            "copyright_year": 2026,
            "logo_url": "https://diraya.ca/logo.png",
            "logo_width": 140,
            "privacy_policy_url": "https://diraya.ca/privacy",
            "terms_of_service_url": "https://diraya.ca/terms",
            "legal_disclaimer": "This message is intended for the named recipient only. If you are not the intended recipient, please delete this email and inform the sender.",
            "partner_notice": "You are receiving this because we believe our work may be relevant to your roadmap. One-click unsubscribe at the bottom.",
        },
        "template": "diraya-custom",
    },
    "_note_template": "Custom template at sequences/email_template_diraya.py (matches live diraya.ca: orange #FF6B00, Kanit, founder-led). CTA button -> brand.cta_url (Calendly).",
}

PROFILE.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"wrote {PROFILE}")
print(f"  from_domains: {len(from_domains)}  personas: {len(personas)}")
print(f"  sample subdomains: {from_domains[0]['domain']}, {from_domains[-1]['domain']}")
print(f"  sample personas: {personas[0]['from_addr']} | {personas[-1]['from_addr']}")
