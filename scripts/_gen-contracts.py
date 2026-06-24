# -*- coding: utf-8 -*-
"""Deterministic generator for the 4 client pilot agreements (Dorian, LK, ENER-G,
AlgoAlpha) from the Diraya base. Every client-specific string is swapped exactly;
the Provider side (Aureon Global L.L.C.) and all body clauses are untouched.
Verifies zero base-template leaks, zero other-client leaks, zero em dashes.

Team Minik is intentionally NOT here (never a client).
"""
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
BASE = REPO / "docs" / "aureon-pilot-agreement-diraya-print.html"

# The exact Diraya client cell (parties table) to replace wholesale.
DIRAYA_CELL = '''The Client</div>
        <div class="name">Diraya Inc.</div>
        a corporation<br>
        Registered office: <span class="placeholder">&nbsp;</span> <em>(to be provided by Client)</em><br>
        Company registration number: <span class="placeholder">&nbsp;</span> <em>(to be provided by Client)</em><br>
        Jurisdiction of incorporation: Canada<br>
        Principal business: artificial intelligence engineering services<br>
        Authorised representative: Mohammed El Amine Amoura, Founder<br>
        Email for notices: amoura.ma@diraya.ca'''

DIRAYA_RECITAL = ('The Client operates Diraya, a provider of artificial intelligence '
                  'engineering services to technology companies, and is presently developing '
                  'its client base among early stage technology companies.')

CLIENTS = {
    "dorian": dict(
        ref="AG MERCURY 2026 01 v1.0", entity="Skiljo Enterprise",
        entity_type="an Einzelunternehmen (sole proprietorship)",
        office="Paulckestrasse 5, 80933 Muenchen, Germany",
        reg="VAT identification: DE361791498", jurisdiction="Germany",
        business="client acquisition services for self-made B2B founders, trading as Mercury Scales",
        rep="Dorian Skiljo, Founder", email="skiljodorian@gmail.com",
        persona='"[First name] from Mercury Scales"',
        recital=("The Client operates Mercury Scales, a client acquisition service for self-made "
                 "B2B founders (AI and automation agencies, high-ticket sales and closing coaches, "
                 "and business educators), and is presently developing its client base among such founders."),
        sig="Dorian Skiljo", title="Founder", place="Munich, Germany",
        domains="mercuryscales.com"),
    "lk-advertising": dict(
        ref="AG LK 2026 01 v1.0", entity="LK Advertising",
        entity_type="an Einzelunternehmen (sole proprietorship) of Lukas Koehler",
        office="Mathystrasse 9, 76133 Karlsruhe, Germany",
        reg="Company registration number: (to be provided by Client)", jurisdiction="Germany",
        business="performance based advertising and lead generation services for real estate agents",
        rep="Lukas Koehler, Owner", email="info@lk-advertising.site",
        persona='"[First name] from LK Advertising"',
        recital=("The Client operates LK Advertising, a performance based advertising service that "
                 "delivers booked listing appointments for real estate agents, and is presently "
                 "developing its client base among such agents."),
        sig="Lukas Koehler", title="Owner", place="Karlsruhe, Germany",
        domains="lk-advertising.site"),
    "energ": dict(
        ref="AG ENERG 2026 01 v1.0", entity="ENER-G Beratung",
        entity_type="a company (ENER G LLC)",
        office="Rincklakeweg 9, 48153 Muenster, Germany",
        reg="Company registration number: (to be provided by Client)", jurisdiction="Germany",
        business="independent energy consulting services for small and medium enterprises",
        rep="Philipp Loisha, Owner", email="info@ener-g-beratung.de",
        persona='"[First name] from ENER-G Beratung"',
        recital=("The Client operates ENER-G Beratung, an independent energy consultancy serving "
                 "small and medium enterprises and commercial businesses, and is presently "
                 "developing its client base among such businesses."),
        sig="Philipp Loisha", title="Owner", place="Muenster, Germany",
        domains="ener-g-beratung.de, ener-g-beratung.org, ener-g-beratung.com, and ener-g-beratung.store"),
}

# Diraya's real sending domains appear in clause 1.1.12 and Schedule 1 of the base.
# These are client-specific and MUST be replaced with each client's own domains.
DIRAYA_DOMAINS_INLINE = ("cleardiraya.com, dirayaget.com, diraya.biz, diraya-agency.shop, "
                         "and diraya-marketing.shop")


def build_cell(c: dict) -> str:
    return (f'''The Client</div>
        <div class="name">{c["entity"]}</div>
        {c["entity_type"]}<br>
        Registered office: {c["office"]}<br>
        {c["reg"]}<br>
        Jurisdiction of incorporation: {c["jurisdiction"]}<br>
        Principal business: {c["business"]}<br>
        Authorised representative: {c["rep"]}<br>
        Email for notices: {c["email"]}''')


def generate(slug: str, c: dict) -> None:
    s = BASE.read_text(encoding="utf-8")
    swaps = 0

    # 1. Parties client cell (wholesale).
    if DIRAYA_CELL in s:
        s = s.replace(DIRAYA_CELL, build_cell(c)); swaps += 1

    # 2. Recital B.
    if DIRAYA_RECITAL in s:
        s = s.replace(DIRAYA_RECITAL, c["recital"]); swaps += 1

    # 3. Persona form.
    s2 = s.replace('"[First name] from Diraya"', c["persona"])
    if s2 != s:
        swaps += 1; s = s2

    # 4. Reference (title page + footer), all occurrences.
    s2 = s.replace("AG DIRAYA 2026 01 v1.0", c["ref"])
    if s2 != s:
        swaps += 1; s = s2

    # 5. Client signature block.
    s = s.replace('<div class="sig-entity">Diraya Inc.</div>',
                  f'<div class="sig-entity">{c["entity"]}</div>')
    s = s.replace('<span class="sig-line filled">Mohammed El Amine Amoura</span>',
                  f'<span class="sig-line filled">{c["sig"]}</span>')
    # Client sig Title (Diraya's was 'Founder'); Place was blank for Diraya.
    s = s.replace('<span class="label">Title</span><span class="sig-line filled">Founder</span>',
                  f'<span class="label">Title</span><span class="sig-line filled">{c["title"]}</span>')
    s = s.replace('<div class="sig-field"><span class="label">Place of signature</span><span class="sig-line">&nbsp;</span></div>',
                  f'<div class="sig-field"><span class="label">Place of signature</span><span class="sig-line filled">{c["place"]}</span></div>', 1)

    # 5b. Diraya's actual sending domains (clause 1.1.12 + Schedule 1) -> this client's.
    s = s.replace(DIRAYA_DOMAINS_INLINE, c["domains"])

    # 6. Any residual Diraya/SMH tokens -> this client.
    for tok, repl in [("Diraya Inc.", c["entity"]), ("Diraya", c["entity"]),
                      ("Mohammed El Amine Amoura", c["sig"]), ("Mohammed", c["sig"]),
                      ("amoura.ma@diraya.ca", c["email"]), ("diraya.ca", c["entity"]),
                      ("Name: Mohammed El Amine Amoura", f"Name: {c['sig']}")]:
        s = s.replace(tok, repl)

    # 7. No em/en dashes.
    s = s.replace(" — ", " - ").replace("—", "-").replace(" – ", " - ").replace("–", "-")

    out = REPO / "docs" / f"aureon-pilot-agreement-{slug}-print.html"
    out.write_text(s, encoding="utf-8")

    # Verify
    base_leak = ["Diraya", "Mohammed", "amoura", "Sales Methodology Hub",
                 "Founder Academy", "Ashraf", "Tilbury"]
    leaks = [t for t in base_leak if t.lower() in s.lower()]
    others = []
    for oslug, oc in CLIENTS.items():
        if oslug == slug:
            continue
        for tok in (oc["entity"], oc["sig"]):
            if re.search(r"\b" + re.escape(tok) + r"\b", s):
                others.append(f"{oslug}:{tok}")
    emd = "—" in s or "–" in s
    status = "OK" if not leaks and not others and not emd else "LEAK"
    print(f"  [{status}] {slug:16} swaps={swaps} base_leaks={leaks} other_clients={others} em_dash={emd}")


def main() -> int:
    for slug, c in CLIENTS.items():
        generate(slug, c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
