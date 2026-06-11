"""LK Advertising pivot — target shift to German real estate agents.

Rewrites:
  - profile name + brand.legal.partner_notice (German)
  - personas array (3 German names, distributed across both LK subdomains)
  - sequences/lk-advertising-default/variants.json (German Hormozi copy)
  - keeps reply_to = info@aureonglobal.de (shared reply mailbox)

Idempotent. Run after a manual edit if you change your mind.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILES = REPO / "profiles"
PUBLIC = REPO / "desktop" / "frontend" / "public" / "profiles"
SEQ = REPO / "sequences" / "lk-advertising-default" / "variants.json"


LK_PERSONAS_DE = [
    {
        "slug": "klara",
        "from_name": "Klara Hofmann",
        "from_addr": "klara@connect.aureonglobal.de",
        "reply_to": "info@aureonglobal.de",
        "title": "Performance-Strategin",
        "voice": {
            "register": "calm-direct",
            "quirks": ["konkrete Zahlen", "eine Frage pro Mail"],
            "avoid": ["Marketing-Floskeln", "Gedankenstriche", "Ausrufezeichen", "Anglizismen wenn vermeidbar"],
        },
        "signature": "Klara Hofmann\nPerformance-Strategin, LK Advertising",
    },
    {
        "slug": "jonas",
        "from_name": "Jonas Vogel",
        "from_addr": "jonas@connect.aureonglobal.de",
        "reply_to": "info@aureonglobal.de",
        "title": "Senior Mediabuyer",
        "voice": {
            "register": "direct-technisch",
            "quirks": ["konkrete ROAS-/Budget-Zahlen", "kurze Absätze"],
            "avoid": ["Hype", "Gedankenstriche", "Ausrufezeichen"],
        },
        "signature": "Jonas Vogel\nSenior Mediabuyer, LK Advertising",
    },
    {
        "slug": "lena",
        "from_name": "Lena Brandt",
        "from_addr": "lena@partners.aureonglobal.de",
        "reply_to": "info@aureonglobal.de",
        "title": "Account-Direktorin",
        "voice": {
            "register": "warm-direkt",
            "quirks": ["nennt die Stadt zurück", "ein Vorschlag pro Mail"],
            "avoid": ["Floskeln", "Gedankenstriche", "Ausrufezeichen"],
        },
        "signature": "Lena Brandt\nAccount-Direktorin, LK Advertising",
    },
]


LK_NEW_NAME = "LK Advertising — Performance-Media für Maklerbüros in Deutschland"

LK_PARTNER_NOTICE_DE = (
    "Sie erhalten diese Nachricht, weil wir glauben, dass die Performance-"
    "Arbeit von LK Advertising für Ihr Maklerbüro relevant sein könnte. "
    "Mit einem Klick abmelden."
)

LK_DISCLAIMER_DE = (
    "Diese Nachricht ist ausschliesslich für den Empfänger bestimmt. "
    "Wenn Sie nicht der richtige Empfänger sind, löschen Sie die E-Mail "
    "bitte und informieren Sie den Absender."
)


LK_VARIANT_DE = {
    "n": 1,
    "delay_days": 0,
    "angle": "real_estate_de_grand_slam",
    "subject": "47 verifizierte Verkäufer-Anfragen in 90 Tagen (München, 4-Makler-Büro)",
    "body": (
        "Guten Tag {first_name},\n\n"
        "Ein 4-Makler-Büro in München hatte 47 verifizierte Verkäufer-Anfragen "
        "in 90 Tagen. Wir haben Meta und Google laufen lassen. Sie haben die "
        "Termine geführt.\n\n"
        "Ein 2-Makler-Team in Stuttgart ging in 5 Monaten von 100 Prozent "
        "Empfehlungsgeschäft auf 40 Prozent Inbound. Drei persönliche Best-"
        "monate im selben Quartal.\n\n"
        "Hier ist, was beide Teams bekommen haben.\n\n"
        "1. Audit Ihrer laufenden Meta- und Google-Konten. Sie sehen die "
        "Verschwendung bevor Sie irgendetwas unterschreiben.\n\n"
        "2. Zwei frische Anzeigen-Konzepte gedreht und geschnitten in Woche 1. "
        "Die Creatives behalten Sie auf jeden Fall.\n\n"
        "3. Konto neu strukturiert mit Conversion-Modeling und sauberer "
        "Signal-Hygiene. Die meisten Maklerbüros gewinnen 18 bis 34 Prozent "
        "effizienten Spend ab dem ersten Tag.\n\n"
        "4. Wöchentlicher Strategie-Call mit einem Senior Mediabuyer. Kein "
        "Account-Manager. Kein Junior.\n\n"
        "Der Knackpunkt. Sie zahlen erst, wenn wir Ihre aktuelle 30-Tage-"
        "ROAS schlagen.\n\n"
        "Wenn wir es nicht schaffen, schulden Sie uns nichts. Die Anzeigen "
        "gehören Ihnen.\n\n"
        "Wenn wir es schaffen, sind unsere Kosten flache 12 Prozent vom "
        "zusätzlichen Bruttogewinn. Kein Retainer. Keine Setup-Gebühr. Kein "
        "Langzeitvertrag.\n\n"
        "Wer wir sind. Performance-Mediaagentur, aufgebaut von ehemaligen "
        "Mediabuyern aus Marken, die Sie schon kennen. Durchschnittliche "
        "Kundenbindung 16 Monate. Die meisten kamen als Agentur-Wechsler.\n\n"
        "Wer passt nicht. Maklerbüros mit weniger als 5.000 Euro monatlichem "
        "Werbebudget oder ohne eigene Webseite. Dafür rechnet sich der "
        "Aufwand nicht.\n\n"
        "Warum jetzt. Wir onboarden 3 neue Konten pro Quartal, dann wird die "
        "Aufnahme geschlossen. Zwei Plätze sind vor Q3 noch offen.\n\n"
        "Antworten Sie mit Ihrem aktuellen Monatsbudget und der Stadt, in "
        "der Sie tätig sind. Ich schicke Ihnen heute noch einen kostenlosen "
        "Audit-Slot.\n\n"
        "Klara"
    ),
}


def main() -> int:
    # 1. Profile changes
    pf = PROFILES / "lk-advertising.json"
    data = json.loads(pf.read_text(encoding="utf-8"))
    data["name"] = LK_NEW_NAME
    data["company"]["tagline"] = "Performance-Media für Maklerbüros in Deutschland"
    data["brand"]["tagline"] = "Performance-Media für Maklerbüros in Deutschland"
    data["brand"]["legal"]["partner_notice"] = LK_PARTNER_NOTICE_DE
    data["brand"]["legal"]["legal_disclaimer"] = LK_DISCLAIMER_DE
    data["personas"] = LK_PERSONAS_DE
    pf.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                  encoding="utf-8")
    pub = PUBLIC / "lk-advertising.json"
    if pub.exists():
        pub.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    print(f"  + profile  lk-advertising  name={data['name'][:70]!r}")
    print(f"             personas=[klara, jonas, lena]")

    # 2. Variants
    v = json.loads(SEQ.read_text(encoding="utf-8"))
    v["name"] = "LK Advertising — Performance-Media für deutsche Maklerbüros (Hormozi, DE)"
    v["target"] = (
        "Maklerbüros (Immobilienmakler) in Deutschland mit 2+ Maklern und "
        "≥5.000 EUR/Monat aktuellem Werbebudget. Ideal: aktiver Wettbewerb mit "
        "anderen Maklerbüros in derselben Stadt, eigene Webseite vorhanden, "
        "verkauft (nicht nur Vermietung) als Hauptgeschäft."
    )
    v["voice_notes"] = (
        "Hormozi grand-slam-offer Framing in Schweizer-deutscher Direktheit. "
        "Echte Zahlen voran (47 Anfragen, 90 Tage, 18-34% Spend-Gewinn). "
        "Stack vor Preis. Risikoumkehr ('zahlen erst wenn wir Ihre ROAS "
        "schlagen'). Knappheit ehrlich (3 Konten/Quartal). Keine Marketing-"
        "Floskeln, keine Gedankenstriche, keine Ausrufezeichen."
    )
    v["variants"] = [LK_VARIANT_DE]
    SEQ.write_text(json.dumps(v, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"  + variant  lk-advertising-default n=1 ({len(LK_VARIANT_DE['body'])} chars body)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
