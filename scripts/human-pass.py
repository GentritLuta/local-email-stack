"""Human-voice pass — applies the user's latest direction:
  - Tighter Hormozi (em-dashes welcome, personal voice, no marketing fluff)
  - Sound like a human wrote it, not a template
  - Use actual website language where available
  - Update persona voice notes to ALLOW em-dashes

Idempotent. Writes profile JSONs + variants.json files.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILES = REPO / "profiles"
PUBLIC = REPO / "desktop" / "frontend" / "public" / "profiles"
SEQ = REPO / "sequences"


# ─── Variants ──────────────────────────────────────────────────────────────

VARIANT_AUREON = {
    "n": 1,
    "delay_days": 0,
    "angle": "aureon_human_v1",
    "subject": "More listings. More closings. Without the lead-chasing.",
    "body": (
        "{first_name} — quick one.\n\n"
        "We've been running ads for a 3-agent team in Munich that took "
        "them from 9 closings/month to 17 in 90 days. Done-for-you "
        "Google/Meta/LinkedIn — they paid only on revenue we sourced.\n\n"
        "Same model for {company}: we eat the ad spend, you keep 100% "
        "of your existing book. 30% only on what we source. No retainer.\n\n"
        "Two slots left before next intake closes.\n\n"
        "What's your average monthly closings in {city}? I'll send an "
        "8-minute audit for {company}.\n\n"
        "— Anna"
    ),
}

VARIANT_ALGOALPHA = {
    "n": 1,
    "delay_days": 0,
    "angle": "algoalpha_human_v1",
    "subject": "Free AlgoAlpha VIP + 50% lifetime — for {company}",
    "body": (
        "{first_name} — quick note.\n\n"
        "AlgoAlpha is the leading brand of TradingView indicators — "
        "14.1 million chart adds, 75,000+ paying traders, Editor's "
        "Choice twice. Smart Signals Assistant, ILPAC, Momentum "
        "Concepts, Echo automation.\n\n"
        "For {company}: free lifetime VIP for you, one custom indicator "
        "built and branded for your audience, 50% lifetime commission "
        "on every paid signup through your link.\n\n"
        "Eight creator slots this month — then we freeze through Q3.\n\n"
        "What's your channel link? I'll send a partner brief inside "
        "24 hours.\n\n"
        "— Tomas"
    ),
}

VARIANT_F2 = {
    "n": 1,
    "delay_days": 0,
    "angle": "f2_human_v1_de",
    "subject": "Wohnungsabnahme in 5 Werktagen — für {company}",
    "body": (
        "Guten Tag {first_name},\n\n"
        "Kurz und direkt. Wir machen Wohnungsabnahmen für eine "
        "Bewirtschaftung in Bern — 5 Werktage, Festpreis, keine "
        "Nachträge.\n\n"
        "Für {company} in {city} würde das so aussehen:\n\n"
        "— Festpreis schriftlich nach der Vor-Ort-Begehung\n"
        "— Termin innert 5 Werktagen oder die nächste Wohnung gratis\n"
        "— eine Telefonnummer, eine Ansprechperson für alle Liegenschaften\n"
        "— Foto-Dokumentation vor und nach jeder Wohnung\n\n"
        "10 Prozent unter Ihrem aktuellen Anbieter. Wenn die Qualität "
        "bei der ersten Wohnung nicht stimmt — Sie zahlen nichts.\n\n"
        "Zwei Plätze pro Monat. Wie viele Wohnungen nehmen Sie in "
        "{city} typischerweise pro Monat ab?\n\n"
        "— Lukas"
    ),
}

VARIANT_LK = {
    "n": 1,
    "delay_days": 0,
    "angle": "lk_human_v1_de",
    "subject": "47 Verkäufer-Anfragen in 90 Tagen — für {company}?",
    "body": (
        "Guten Tag {first_name},\n\n"
        "Kurz und konkret. Wir haben gerade für ein 4-Makler-Büro in "
        "München 47 verifizierte Verkäufer-Anfragen in 90 Tagen "
        "produziert — Meta und Google, keine Kaltakquise.\n\n"
        "Für {company} in {city} würde das so laufen:\n\n"
        "— Audit Ihrer aktuellen Meta/Google-Konten in Woche 1\n"
        "— Zwei frische Anzeigen-Konzepte gedreht und geschnitten in "
        "derselben Woche\n"
        "— Konto neu strukturiert mit Conversion-Modeling — die meisten "
        "Maklerbüros gewinnen 18-34 Prozent effizienten Spend ab Tag 1\n\n"
        "Sie zahlen erst, wenn wir Ihre aktuelle 30-Tage-ROAS schlagen. "
        "Sonst nichts.\n\n"
        "Drei Konten pro Quartal — zwei Plätze vor Q3 offen. Wie hoch "
        "ist Ihr aktuelles Monatsbudget in {city}?\n\n"
        "— Klara"
    ),
}


SEQ_UPDATES = {
    "aureon-default": (VARIANT_AUREON, "Aureon Global — Real estate growth (human voice, Hormozi, em-dashes)"),
    "algoalpha-default": (VARIANT_ALGOALPHA, "AlgoAlpha — Creator partnership (human voice, Hormozi, em-dashes)"),
    "f2-malergipser-default": (VARIANT_F2, "F2 Maler & Gipser — Liegenschaftsverwalter (kurz, human, Hormozi)"),
    "lk-advertising-default": (VARIANT_LK, "LK Advertising — Maklerbüro-Outreach (kurz, human, Hormozi)"),
}


# ─── Persona voice-note updates: ALLOW em-dashes ───────────────────────────

def remove_em_dash_avoidance(p: dict) -> dict:
    for persona in p.get("personas", []):
        avoid = persona.get("voice", {}).get("avoid", [])
        # Strip any "em-dashes" / "Gedankenstriche" mentions
        avoid = [a for a in avoid if a.lower() not in (
            "em-dashes", "em dashes", "emdashes",
            "gedankenstriche", "—", "no em-dashes", "no em dashes"
        )]
        if "voice" in persona:
            persona["voice"]["avoid"] = avoid
    return p


def main() -> int:
    # Update each variants.json
    for seq_dir, (variant, name) in SEQ_UPDATES.items():
        vf = SEQ / seq_dir / "variants.json"
        if not vf.exists():
            print(f"  ! skip {seq_dir}: no variants file")
            continue
        d = json.loads(vf.read_text(encoding="utf-8"))
        d["name"] = name
        d["voice_notes"] = (
            "Hormozi grand-slam framing in human voice. Em-dashes ALLOWED — "
            "they're how humans actually write. Personal opener (\"quick one\" / "
            "\"kurz und direkt\"). Concrete hook in line 1 (named-city case "
            "study, named numbers). Stack the deliverables visually (em-dash "
            "bullets). Risk reversal sharp. CTA names {company} and {city} "
            "so it feels investigated. Required merges: {first_name}, "
            "{company}" + (", {city}" if "{city}" in variant["body"] else "") + "."
        )
        d["variants"] = [variant]
        vf.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
        word_count = len(variant["body"].split())
        print(f"  + {seq_dir:30s} subj: {variant['subject'][:55]!r:57s} body: {word_count} words")

    # Update each profile's persona voice.avoid lists
    for slug in ("aureon", "algoalpha", "f2-malergipser", "lk-advertising"):
        pf = PROFILES / f"{slug}.json"
        if not pf.exists():
            continue
        d = json.loads(pf.read_text(encoding="utf-8"))
        d = remove_em_dash_avoidance(d)
        pf.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
        pub = PUBLIC / f"{slug}.json"
        if pub.exists():
            pub.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
        print(f"  + profile  {slug:18s} (em-dashes now allowed in persona voice)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
