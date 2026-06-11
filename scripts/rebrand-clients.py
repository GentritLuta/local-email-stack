"""One-off rebrand pass — applies approved name + persona changes to the
four commercial client profiles, then re-pushes to Supabase.

Idempotent: re-running produces the same result. Safe to re-run after a
push failure.

After running, verify with:
  py sequences/supabase_sync.py status
  py -c "import json; print(json.load(open('profiles/algoalpha.json',encoding='utf-8'))['name'])"
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILES = REPO / "profiles"
PUBLIC = REPO / "desktop" / "frontend" / "public" / "profiles"


# ─── New persona definitions ───────────────────────────────────────────────

AUREON_PERSONAS = [
    {
        "slug": "anna",
        "from_name": "Anna Bauer",
        "from_addr": "anna@mail.aureonglobal.de",
        "reply_to": "info@aureonglobal.de",
        "title": "Senior Partnership Manager",
        "voice": {
            "register": "calm-precise",
            "quirks": ["specific numbers", "one question per email"],
            "avoid": ["hype", "stacked adjectives", "em-dashes"],
        },
        "signature": "Anna Bauer\nSenior Partnership Manager, Aureon Global",
    },
    {
        "slug": "lars",
        "from_name": "Lars Müller",
        "from_addr": "lars@outreach.aureonglobal.de",
        "reply_to": "info@aureonglobal.de",
        "title": "Brokerage Partner Lead — AT / CH",
        "voice": {
            "register": "warm-direct",
            "quirks": ["short paragraphs", "names the city back to them"],
            "avoid": ["corporate-speak", "exclamation marks", "em-dashes"],
        },
        "signature": "Lars Müller\nBrokerage Partner Lead, Aureon Global",
    },
    {
        "slug": "daan",
        "from_name": "Daan de Vries",
        "from_addr": "daan@hi.aureonglobal.de",
        "reply_to": "info@aureonglobal.de",
        "title": "Country Lead Netherlands",
        "voice": {
            "register": "friendly-direct",
            "quirks": ["plain phrasing", "one concrete proof per email"],
            "avoid": ["templated phrases", "marketing language", "em-dashes"],
        },
        "signature": "Daan de Vries\nCountry Lead Netherlands, Aureon Global",
    },
]


ALGOALPHA_PERSONAS = [
    {
        "slug": "tomas",
        "from_name": "Tomás Silva",
        "from_addr": "tomas@team.aureonglobal.de",
        "reply_to": "support@algoalpha.io",
        "title": "Creator Partnerships, AlgoAlpha",
        "voice": {
            "register": "calm-technical",
            "quirks": ["specific numbers"],
            "avoid": ["hype", "em-dashes"],
        },
        "signature": "Tomás Silva\nCreator Partnerships, AlgoAlpha",
    },
    {
        "slug": "marcus",
        "from_name": "Marcus Chen",
        "from_addr": "marcus@desk.aureonglobal.de",
        "reply_to": "support@algoalpha.io",
        "title": "Head of Creator Growth, AlgoAlpha",
        "voice": {
            "register": "direct-warm",
            "quirks": ["specific data points"],
            "avoid": ["em-dashes", "corporate-speak"],
        },
        "signature": "Marcus Chen\nHead of Creator Growth, AlgoAlpha",
    },
    {
        "slug": "iris",
        "from_name": "Iris Walsh",
        "from_addr": "iris@hub.aureonglobal.de",
        "reply_to": "support@algoalpha.io",
        "title": "Creator Onboarding Lead, AlgoAlpha",
        "voice": {
            "register": "precise-friendly",
            "quirks": ["one question per email", "names a real metric"],
            "avoid": ["fluff", "em-dashes"],
        },
        "signature": "Iris Walsh\nCreator Onboarding Lead, AlgoAlpha",
    },
]


F2_NEW_PERSONA = {
    "slug": "reto",
    "from_name": "Reto Stalder",
    "from_addr": "reto@send.aureonglobal.de",
    "reply_to": "info@aureonglobal.de",
    "title": "Projektleiter Liegenschaftsverwaltung",
    "voice": {
        "register": "höflich-direkt",
        "quirks": ["nennt konkrete Quadratmeter / Tage / Franken"],
        "avoid": ["Marketing-Floskeln", "Gedankenstriche", "Ausrufezeichen"],
    },
    "signature": "Reto Stalder\nProjektleiter Liegenschaftsverwaltung, F2 Maler & Gipser",
}


LK_NEW_PERSONA = {
    "slug": "priya",
    "from_name": "Priya Shah",
    "from_addr": "priya@partners.aureonglobal.de",
    "reply_to": "info@aureonglobal.de",
    "title": "Senior Media Buyer",
    "voice": {
        "register": "calm-technical",
        "quirks": ["concrete ROAS / spend numbers", "one ask per email"],
        "avoid": ["hype", "em-dashes", "exclamation marks"],
    },
    "signature": "Priya Shah\nSenior Media Buyer, LK Advertising",
}


# ─── Edits ─────────────────────────────────────────────────────────────────

def rebrand_aureon(p: dict) -> dict:
    p["name"] = "Aureon Global — Real estate growth partner (DACH + NL)"
    p["personas"] = AUREON_PERSONAS
    return p


def rebrand_algoalpha(p: dict) -> dict:
    p["name"] = "AlgoAlpha — Creator partnership program for crypto traders"
    p.pop("_personas_note", None)
    p["personas"] = ALGOALPHA_PERSONAS
    # tighten rotation: with 3 personas × 3 subdomains, raise cap from old defaults
    p.setdefault("rotation", {})
    p["rotation"]["strategy"] = "round_robin_by_persona"
    p["rotation"]["max_sends_per_persona_per_day"] = 30
    p["rotation"]["min_seconds_between_sends_same_persona"] = 180
    return p


def rebrand_f2(p: dict) -> dict:
    p["name"] = "F2 Maler & Gipser — Maler- und Gipserarbeiten Bern / Emmental"
    existing_slugs = {x["slug"] for x in p.get("personas", [])}
    if "reto" not in existing_slugs:
        p["personas"].append(F2_NEW_PERSONA)
    return p


def rebrand_lk(p: dict) -> dict:
    p["name"] = "LK Advertising — Performance media for DTC + B2B brands"
    existing_slugs = {x["slug"] for x in p.get("personas", [])}
    if "priya" not in existing_slugs:
        p["personas"].append(LK_NEW_PERSONA)
    return p


REBRANDERS = {
    "aureon":         rebrand_aureon,
    "algoalpha":      rebrand_algoalpha,
    "f2-malergipser": rebrand_f2,
    "lk-advertising": rebrand_lk,
}


def main() -> int:
    for slug, fn in REBRANDERS.items():
        path = PROFILES / f"{slug}.json"
        if not path.exists():
            print(f"  ! skip {slug}: no profile file")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data = fn(data)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        # Mirror to desktop frontend public dir if it exists there
        pub = PUBLIC / f"{slug}.json"
        if pub.exists():
            safe = json.loads(json.dumps(data))  # deep copy
            # public mirror has no secrets so we can write data directly
            pub.write_text(json.dumps(safe, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
        names = ", ".join(x["slug"] for x in data["personas"])
        print(f"  + {slug:18s} name={data['name'][:60]!r:62s} personas=[{names}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
