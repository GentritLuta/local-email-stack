"""finalize-atalsolidrocks-profile.py — make the atalsolidrocks profile
structurally complete: 12 personas, brand config, send_ramp, warmup
config (NOT started), and active=true.

Idempotent — re-runnable. Does NOT start the warmup (started_at left null).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from profile_lib import load_profile, save_profile  # noqa: E402

# DACH first+last name pairs, one per subdomain. Gender-balanced (6F/6M).
PERSONA_FULL_NAMES = {
    "lukas":  "Lukas Becker",
    "anna":   "Anna Hofmann",
    "tobias": "Tobias Meyer",
    "lea":    "Lea Schmidt",
    "felix":  "Felix Weber",
    "sara":   "Sara Müller",
    "jonas":  "Jonas Fischer",
    "mira":   "Mira Wagner",
    "niklas": "Niklas Klein",
    "lena":   "Lena Bauer",
    "elias":  "Elias Richter",
    "nora":   "Nora Schulz",
}


def make_persona(slug: str, full_name: str) -> dict:
    first = full_name.split()[0]
    return {
        "slug":     slug,
        "from_name": f"{first} from Atal SolidRocks",
        "from_addr": f"{slug}@{slug}.atalsolidrocks.io",
        "reply_to": "info@atalsolidrocks.io",
        "title":    "Account Executive",
        "voice": {
            "register": "höflich-direkt",
            "quirks":   ["kurze Sätze", "konkrete Zahlen", "Sie-Form"],
            "avoid":    ["Marketing-Floskeln", "Ausrufezeichen", "Emojis"],
        },
        "signature": f"{full_name}\nAtal SolidRocks",
    }


BRAND = {
    "wordmark": "Atal SolidRocks",
    "site":     "atalsolidrocks.io",
    "tagline":  "DACH B2B outreach — Spezialisten für [VALUE_PROP_FIXME]",
    "font_stack": '"Plus Jakarta Sans", sans-serif',
    "font_url":   "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap",
    # Sober DACH B2B navy + amber palette — distinct from F2 (green) and Aureon (gold)
    "colors": {
        "accent":   "#1e3a8a",
        "accent_2": "#0f172a",
        "text":     "#0f172a",
        "text_2":   "#475569",
        "muted":    "#94a3b8",
        "bg_page":  "#f8fafc",
        "bg_card":  "#ffffff",
        "rule":     "#e2e8f0",
    },
    "unsubscribe_url_template": "https://gentritluta.github.io/local-email-stack/unsubscribe/atalsolidrocks.html?t={token}",
    "legal": {
        "company_name":  "Atal SolidRocks",
        "address_lines": ["Atal SolidRocks", "DACH"],
        "contact_email": "info@atalsolidrocks.io",
        "copyright_year": 2026,
        "logo_url":      "",
        "logo_width":    140,
        "privacy_policy_url": "https://atalsolidrocks.io/datenschutz",
        "terms_of_service_url": "https://atalsolidrocks.io/agb",
        "legal_disclaimer": "Diese Nachricht ist ausschliesslich für den Empfänger bestimmt. Wenn Sie nicht der richtige Empfänger sind, löschen Sie die E-Mail bitte und informieren Sie den Absender.",
        "partner_notice":   "Sie erhalten diese Nachricht, weil wir glauben, dass unser Angebot für Sie relevant sein könnte. Mit einem Klick abmelden.",
    },
    "_note_legal": "Mailbox info@atalsolidrocks.io muss noch in Hostinger Email eingerichtet werden, damit DMARC-Reports + Reply-To funktionieren.",
    "template":   "default",
}


def main() -> int:
    p = load_profile("atalsolidrocks")

    # Personas — 12, one per subdomain
    p["personas"] = [make_persona(slug, name) for slug, name in PERSONA_FULL_NAMES.items()]

    # Brand
    p["brand"] = BRAND

    # Activate but DO NOT start warmup yet
    p["active"] = True
    # Warmup: enabled, but started_at=null and current_day=0 so the orchestrator
    # treats it as "configured, not yet ramping". Run start-warmup.py later.
    p.setdefault("warmup", {})
    p["warmup"]["enabled"] = True
    p["warmup"]["current_day"] = 0
    p["warmup"]["started_at"] = None
    p["warmup"]["advance_only_mode"] = True
    p["warmup"].setdefault("auto_pause_thresholds", {"bounce_rate": 0.05, "complaint_rate": 0.003})
    p["warmup"].setdefault("reputation", {"bounce_rate_7d": 0, "complaint_rate_7d": 0, "delivered_7d": 0, "last_check": None})
    p["warmup"]["warmup_targets"] = []
    p["warmup"]["real_send_mix"] = []
    p["warmup"]["ramp_curve"] = "snowball_v1"

    # Send ramp config (mirrors the snowball curve used by warmup logic)
    p.setdefault("send_ramp", {})
    p["send_ramp"]["started_at"] = None

    # Rotation strategy (round-robin across personas, sender stickiness per run)
    p.setdefault("rotation", {})
    p["rotation"]["strategy"] = "round_robin"

    # Each subdomain also gets warmup config bumped to enabled=true and curve=snowball_v1
    for fd in p.get("relay", {}).get("from_domains", []):
        fd.setdefault("warmup", {})
        fd["warmup"]["enabled"] = True
        fd["warmup"]["current_day"] = 0
        fd["warmup"]["started_at"] = None
        fd["warmup"]["ramp_curve"] = "snowball_v1"
        fd["warmup"].setdefault("max_daily_sends", 50)
        fd["warmup"].setdefault("reputation", {"bounce_rate_7d": 0.0, "complaint_rate_7d": 0.0, "delivered_7d": 0, "last_check": None})

    save_profile(p)
    print(f"✓ atalsolidrocks profile finalized")
    print(f"  active                  : {p['active']}")
    print(f"  personas                : {len(p['personas'])}")
    print(f"  subdomains              : {len(p['relay']['from_domains'])}")
    print(f"  warmup.enabled          : {p['warmup']['enabled']}")
    print(f"  warmup.started_at       : {p['warmup']['started_at']}  (orchestrator skips warmup ticks)")
    print(f"  brand.template          : {p['brand']['template']}")
    print(f"  brand.tagline           : {p['brand']['tagline']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
