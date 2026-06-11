# -*- coding: utf-8 -*-
"""7-email German B2B cold-outreach sequence for Atal Solidrocks.

Standalone deliverable. Company + offer data from the Aureon onboarding form
(todos-2026-05-29.txt). ICP = DACH SMEs (20-500 MA) with budget for employee
health / L&D, plus academies/institutes (train-the-trainer angle).

Voice: Hormozi $100M Leads structure, DACH Sie-Form, short sentences, concrete
numbers. Echte Umlaute (ä ö ü). ß als ss. KEINE Ausrufezeichen, KEINE
Gedankenstriche, KEINE Emojis. Positive Antworten -> Calendly.

Merge tags: {first_name}, {company}, {city}.
"""

BRAND = {
    "wordmark": "Atal Solidrocks",
    "site": "atalsolidrocks.com",
    "tagline": "Weniger Krankenstand. Mehr Leistung. Messbar in 90 Tagen.",
    "calendly_url": "https://calendly.com/atal-solidrocks/15min",
    "unsubscribe_url": "https://atalsolidrocks.com/abmelden",
    "legal": {
        "company_name": "Atal Solidrocks",
        "reg_number": "DE432358206",
        "address_lines": ["Feldstr. 43, 41462 Neuss", "Deutschland"],
        "contact_email": "atal.solidrocks@gmail.com",
        "copyright_year": 2026,
    },
    # Signatur fuer die Vorschau (Calls werden von Atal + Gentrit uebernommen)
    "signature": ["Atal Solidrocks", "Gründer, Atal Solidrocks", "Neuss"],
}

# delay_days = Abstand zum vorigen Schritt. 0,2,2,3,4,7,10 -> Tag 0,2,4,7,11,18,28
SEQUENCE = [
    {
        "n": 1,
        "delay_days": 0,
        "angle": "hormozi_sind_sie_offen",
        "subject": "Sind Sie offen?",
        "kicker": "Prävention · DACH Mittelstand",
        "headline": "Weniger Krankenstand in 90 Tagen.",
        "show_cta": False,
        "body": (
            "Guten Tag {first_name},\n\n"
            "sind Sie gerade offen für etwas?\n\n"
            "Ich sehe, was {company} in {city} aufgebaut hat.\n\n"
            "Wir helfen Unternehmen im DACH Mittelstand, den Krankenstand spürbar "
            "zu senken. Mit praxisnahen Präventionsseminaren zu Schlaf, Stress, "
            "Resilienz, Regeneration, Konzentration und Leistung. Online oder inhouse, "
            "in Gruppen bis zehn Personen.\n\n"
            "Macht ein 15 Minuten Gespräch Sinn?\n\n"
            "P.s. einfach mit nein antworten, falls kein Interesse."
        ),
    },
    {
        "n": 2,
        "delay_days": 2,
        "angle": "hormozi_checking_out",
        "subject": "kurz nach {company} geschaut",
        "kicker": "Schlaf · Stress · Resilienz",
        "headline": "Gesunde Teams arbeiten besser.",
        "show_cta": True,
        "cta_label": "Vorgespräch buchen",
        "body": (
            "Guten Tag {first_name},\n\n"
            "habe kurz nach {company} geschaut.\n\n"
            "Kurzer Kontext: wir reduzieren Stress, Fehltage und Erschöpfung in "
            "mittelständischen Teams. Vom Gründer persönlich begleitet, keine "
            "anonymen Trainer Pools, keine Standardfolien.\n\n"
            "Für Akademien und Institute geht das auch als Train the Trainer, damit "
            "Ihre eigenen Coaches das Wissen weitergeben können.\n\n"
            "15 Minuten zum Kennenlernen?"
        ),
    },
    {
        "n": 3,
        "delay_days": 2,
        "angle": "hormozi_data_point",
        "subject": "ein Datenpunkt zu Fehltagen",
        "kicker": "Mess­barer Effekt",
        "headline": "Was ein Fehltag wirklich kostet.",
        "show_cta": True,
        "cta_label": "Termin sichern",
        "body": (
            "Guten Tag {first_name},\n\n"
            "noch ein Datenpunkt.\n\n"
            "Jeder krankheitsbedingte Fehltag kostet pro Mitarbeitenden mehrere "
            "hundert Euro. Bei einem Team von 100 Personen summiert sich das schnell "
            "auf einen sechsstelligen Betrag pro Jahr.\n\n"
            "Unsere Seminare setzen genau dort an: bei Schlaf, Stress und Erholung, "
            "den Hebeln mit dem schnellsten Effekt auf Anwesenheit und Leistung.\n\n"
            "Das gleiche Modell könnte für {company} in {city} funktionieren."
        ),
    },
    {
        "n": 4,
        "delay_days": 3,
        "angle": "hormozi_sind_sie_beschaeftigt",
        "subject": "viel zu tun..?",
        "kicker": "Vierte Nachricht",
        "headline": "Sieben Hebel, einer wirkt zuerst.",
        "show_cta": True,
        "cta_label": "15 Minuten buchen",
        "body": (
            "Guten Tag {first_name},\n\n"
            "ich nochmal, das ist die vierte Nachricht, ich nehme an Sie haben viel "
            "zu tun.\n\n"
            "Problem: bleiben Stress und Fehltage bei {company} auf dem aktuellen "
            "Niveau, zahlt das Unternehmen Jahr für Jahr drauf, ohne dass jemand die "
            "Rechnung sieht.\n\n"
            "Lösung: 15 Minuten am Telefon und ich zeige, welches Seminar bei Ihrem "
            "Team am schnellsten wirkt.\n\n"
            "Wann passt es?"
        ),
    },
    {
        "n": 5,
        "delay_days": 4,
        "angle": "hormozi_forced_yes_or_no",
        "subject": "{first_name}, ja oder nein",
        "kicker": "Kurze Frage",
        "headline": "Eine Frage, eine Antwort.",
        "show_cta": True,
        "cta_label": "Ja, Termin buchen",
        "body": (
            "Guten Tag {first_name},\n\n"
            "wenn wir Stress und Fehltage bei {company} in 90 Tagen messbar senken "
            "würden, mit Vorher Nachher Vergleich, würden Sie ja sagen?\n\n"
            "Ein klares ja oder nein, beides reicht."
        ),
    },
    {
        "n": 6,
        "delay_days": 7,
        "angle": "hormozi_pure_value",
        "subject": "Schlaf Check für {company}",
        "kicker": "Geschenk · kein Anruf",
        "headline": "Der Schlaf Check gehört Ihnen.",
        "show_cta": False,
        "body": (
            "Guten Tag {first_name},\n\n"
            "ob {company} mit uns arbeitet oder nicht, der Schlaf Check für Ihr Team "
            "gehört Ihnen.\n\n"
            "Es ist ein kompaktes PDF, mit dem Ihre Mitarbeitenden in zehn Minuten "
            "ihre grössten Schlaf- und Erholungsbremsen erkennen.\n\n"
            "Antworten Sie mit dem Wort Check und ich schicke es innerhalb von 24 "
            "Stunden. Kein Anruf, kein Verkaufsgespräch."
        ),
    },
    {
        "n": 7,
        "delay_days": 10,
        "angle": "hormozi_breakup",
        "subject": "schliesse Ihre Akte",
        "kicker": "Letzte Nachricht",
        "headline": "Ich schliesse Ihre Akte.",
        "show_cta": False,
        "body": (
            "Guten Tag {first_name},\n\n"
            "ich schliesse Ihre Akte bei Atal Solidrocks heute, da ich pro Quartal "
            "nur eine begrenzte Zahl an Teams persönlich begleite.\n\n"
            "Falls der Zeitpunkt nicht passt, verstehe ich das. Falls das Angebot "
            "nicht passt, sagen Sie es kurz. Sonst melde ich mich nicht mehr.\n\n"
            "Alles Gute für {company} und das Team in {city}."
        ),
    },
]
