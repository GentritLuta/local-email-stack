"""Generate the 32-Punkte-Wohnungsabnahme-Checkliste as a branded PDF
that matches f2-malergipser.ch + the F2 email visual language.

  - Dark teal hero strip with the real F2 logo
  - Green checkboxes (☐) for the operator to tick during walk-through
  - Section headers in dark slate
  - Plus Jakarta Sans typography
  - Dark teal footer with F2 contact info
  - A4 page size, 3 pages, print-safe

Outputs:
  previews/f2-checklist/wohnungsabnahme-checkliste.pdf
  previews/f2-checklist/wohnungsabnahme-checkliste.png   (page-1 screenshot)
"""
from __future__ import annotations
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "previews" / "f2-checklist"
OUT.mkdir(parents=True, exist_ok=True)

LOGO_URL = ("https://horizons-cdn.hostinger.com/2289cef3-cfe1-43c6-8890-321b9bb5fdc5/"
            "6dfa90e1c23f38fcb6efab9b0d2a107b.png")

PALETTE = {
    "teal":      "#0a2620",
    "teal2":     "#0f2e2a",
    "green":     "#6ba94c",
    "text":      "#1a2332",
    "text_2":    "#475569",
    "muted":     "#94a3ab",
    "rule":      "#e2e8f0",
    "cream":     "#f9f9f5",
}

FONT = ("'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', "
        "Roboto, 'Helvetica Neue', Arial, sans-serif")

CHECKLIST = [
    ("Allgemeines", [
        "Zählerstände Strom, Wasser, Gas dokumentieren mit Foto und Datum.",
        "Schlüsselübergabe protokollieren. Anzahl Schlüssel, Codes für Schliessanlagen, Tiefgaragenfernbedienung.",
        "Briefkasten und Klingelschild mit korrektem Mieternamen.",
        "Türen schliessen sauber, keine Klemmungen, Schlösser funktional.",
    ]),
    ("Eingang und Korridor", [
        "Boden auf Kratzer, Flecken, Risse prüfen.",
        "Wände auf Bohrlöcher, Risse, Flecken kontrollieren.",
        "Decken auf Wasserflecken oder Schimmel absuchen.",
        "Steckdosen, Lichtschalter, Sprechanlage funktional.",
    ]),
    ("Wohnräume und Schlafräume", [
        "Fenster schliessen bündig, Dichtungen intakt, Glas ohne Sprünge.",
        "Rollläden und Storen mechanisch und elektrisch testen.",
        "Heizkörper warm werden lassen, kein Rost, keine Lecks.",
        "Parkett oder Laminat auf Kratzer, lose Bretter, Quellungen.",
    ]),
    ("Küche", [
        "Backofen innen, Backblech, Dichtungen kontrollieren.",
        "Kühlschrank und Gefrierfach abgetaut, sauber, Türdichtung intakt.",
        "Geschirrspüler Probelauf, Sieb gereinigt, kein Leck.",
        "Dunstabzugshaube Filter ausgetauscht oder gereinigt.",
        "Kochfeld Funktionstest aller Platten plus Sauberkeit.",
        "Armatur, Spüle, Siphon dicht und ohne Kalkschäden.",
        "Schränke vollständig, Schubladen leicht laufend, Scharniere fest.",
    ]),
    ("Bad und WC", [
        "WC Spülung, Sitz, Dichtung an Vorlauf und Ablauf.",
        "Dusche und Badewanne Silikonfugen, Abfluss, Sieb.",
        "Armaturen tropffrei, Kalk entfernt.",
        "Spiegelschrank, Beleuchtung, Steckdose mit FI getestet.",
        "Badlüftung läuft, Filter sauber.",
    ]),
    ("Balkon, Keller, Estrich", [
        "Balkonboden, Geländer, Glas auf Beschädigungen.",
        "Sonnenstoren funktional, Kurbel oder Motor.",
        "Keller oder Estrichabteil zugewiesen und beschriftet.",
        "Auf Feuchtigkeit oder Schimmel im Keller prüfen.",
    ]),
    ("Technik und Sicherheit", [
        "Rauchmelder Funktionstest, Batterie maximal ein Jahr alt.",
        "Sicherungskasten und FI Schutzschalter testweise auslösen.",
    ]),
    ("Aussenbereich", [
        "Hausnummer, Klingel, Briefkasten beschriftet.",
        "Parkplatz oder Garage. Zustand und Nummer protokollieren.",
    ]),
]

# Flatten and number 1..32
flat: list[tuple[int, str, str]] = []
n = 1
for section_name, items in CHECKLIST:
    for item in items:
        flat.append((n, section_name, item))
        n += 1
assert n - 1 == 32, f"expected 32 items, got {n - 1}"


def render_item(num: int, text: str) -> str:
    """One row: number badge + item text + ruled note line."""
    return f"""
    <tr>
      <td valign="top" style="width:36px;padding:8px 0;font-family:{FONT};
                              font-size:11px;font-weight:700;color:{PALETTE['green']};
                              letter-spacing:.5px;">{num:02d}</td>
      <td valign="top" style="width:22px;padding:9px 8px 0 0;">
        <div style="width:14px;height:14px;border:2px solid {PALETTE['green']};
                    border-radius:3px;"></div>
      </td>
      <td valign="top" style="padding:8px 0 8px 0;font-family:{FONT};
                              font-size:12.5px;line-height:1.55;color:{PALETTE['text']};">
        {text}
        <div style="margin-top:6px;height:1px;background:{PALETTE['rule']};"></div>
      </td>
    </tr>"""


def render_section(title: str, items_html: str) -> str:
    return f"""
    <div style="margin-top:18px;">
      <div style="font-family:{FONT};font-size:11px;font-weight:800;letter-spacing:1.4px;
                  color:{PALETTE['green']};text-transform:uppercase;padding-bottom:4px;
                  border-bottom:2px solid {PALETTE['green']};display:inline-block;">
        {title}
      </div>
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
             style="margin-top:8px;">
        <tbody>{items_html}</tbody>
      </table>
    </div>"""


# Group items by their section for rendering
section_blocks = []
for section_name, items in CHECKLIST:
    rows = ""
    for item in items:
        # Find the global number
        for gn, sname, txt in flat:
            if sname == section_name and txt == item:
                rows += render_item(gn, item)
                break
    section_blocks.append(render_section(section_name, rows))


HTML = f"""<!doctype html>
<html lang="de-CH">
<head>
  <meta charset="utf-8">
  <title>Wohnungsabnahme Checkliste · F2 Maler &amp; Gipser</title>
  <style>
    @page {{ size: A4; margin: 0; }}
    html, body {{ margin: 0; padding: 0; background: #ffffff; }}
    body {{ font-family: {FONT}; color: {PALETTE['text']}; }}
    .page {{ width: 210mm; min-height: 297mm; box-sizing: border-box;
             padding: 0; margin: 0 auto; background: #ffffff; }}
    .hero {{ background: {PALETTE['teal']};
             background-image: linear-gradient(135deg,{PALETTE['teal2']} 0%, {PALETTE['teal']} 100%);
             padding: 28px 36px; color: #ffffff; }}
    .body {{ padding: 28px 36px 24px; }}
    .footer {{ background: {PALETTE['teal']}; color: {PALETTE['muted']};
               padding: 22px 36px; font-family: {FONT}; }}
    .pagebreak {{ page-break-after: always; }}
    a {{ color: {PALETTE['green']}; text-decoration: none; }}
  </style>
</head>
<body>

<!-- ─── PAGE 1: Cover + first sections ─────────────────────────────── -->
<div class="page pagebreak">
  <div class="hero">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td valign="middle" width="76">
          <img src="{LOGO_URL}" width="64" height="64"
               style="display:block;border-radius:50%;background:#ffffff;border:0;">
        </td>
        <td valign="middle">
          <div style="font-family:{FONT};font-size:13px;font-weight:700;letter-spacing:1.4px;
                      text-transform:uppercase;color:{PALETTE['green']};">F2 Maler &amp; Gipser</div>
          <div style="font-family:{FONT};font-size:28px;font-weight:800;
                      color:#ffffff;line-height:1.15;margin-top:6px;">
            Wohnungsabnahme Checkliste
          </div>
          <div style="font-family:{FONT};font-size:13px;color:{PALETTE['muted']};
                      margin-top:10px;font-style:italic;">
            32 Punkte aus 17 Jahren Erfahrung und über 500 abgenommenen Wohnungen.
          </div>
        </td>
      </tr>
    </table>
  </div>

  <div class="body">
    <p style="margin:0 0 6px 0;font-family:{FONT};font-size:13.5px;line-height:1.6;
              color:{PALETTE['text_2']};">
      Guten Tag,
    </p>
    <p style="margin:0 0 16px 0;font-family:{FONT};font-size:13.5px;line-height:1.6;
              color:{PALETTE['text']};">
      Hier ist die Liste, die wir bei uns intern bei jeder Wohnungsabnahme
      verwenden. Sie ist über die Jahre gewachsen, weil wir gemerkt haben:
      Was nicht aufgeschrieben ist, wird vergessen, und was vergessen wird,
      kostet am Schluss richtig Geld. Einfach ausdrucken, mitnehmen, abhaken.
      Wenn Ihnen ein Punkt fehlt, schreiben Sie uns. Wir nehmen ihn auf.
    </p>

    {section_blocks[0]}
    {section_blocks[1]}
    {section_blocks[2]}
    {section_blocks[3]}
  </div>
</div>

<!-- ─── PAGE 2: Bath / Balcony / Tech / Aussen ─────────────────────── -->
<div class="page pagebreak">
  <div class="body" style="padding-top:36px;">
    {section_blocks[4]}
    {section_blocks[5]}
    {section_blocks[6]}
    {section_blocks[7]}

    <div style="margin-top:32px;padding:16px 18px;background:{PALETTE['cream']};
                border-left:4px solid {PALETTE['green']};font-family:{FONT};
                font-size:12.5px;line-height:1.6;color:{PALETTE['text']};">
      <b>Ein Tipp aus der Praxis.</b> Bei jedem Mangel ein Foto machen. Mit
      Datum, mit Uhrzeit, am besten direkt vom Telefon, dann ist das Datum
      automatisch drauf. Wenn es später zum Streit mit der ausziehenden
      Partei kommt, ist das die einzige Evidenz, die wirklich zählt.
    </div>
  </div>
</div>

<!-- ─── PAGE 3: Notes + F2 contact ─────────────────────────────────── -->
<div class="page">
  <div class="body" style="padding-top:36px;">
    <div style="font-family:{FONT};font-size:11px;font-weight:800;letter-spacing:1.4px;
                color:{PALETTE['green']};text-transform:uppercase;
                border-bottom:2px solid {PALETTE['green']};padding-bottom:4px;display:inline-block;">
      Notizen
    </div>
    <div style="margin-top:14px;">""" + "".join(
        f'<div style="height:24px;border-bottom:1px solid {PALETTE["rule"]};"></div>'
        for _ in range(18)
    ) + f"""
    </div>

    <div style="margin-top:24px;padding:18px 20px;background:{PALETTE['cream']};
                border-radius:8px;font-family:{FONT};color:{PALETTE['text']};">
      <div style="font-size:11px;font-weight:800;letter-spacing:1.4px;
                  color:{PALETTE['green']};text-transform:uppercase;">Wenn Sie die Abnahme abgeben wollen</div>
      <div style="margin-top:8px;font-size:13.5px;line-height:1.6;">
        Wenn Sie die nächste Abnahme nicht selbst machen wollen, machen wir
        sie. 5 Werktage ab Auftrag, Festpreis schriftlich, eine
        Telefonnummer für alles. Bei der ersten Wohnung sind wir 10 Prozent
        unter Ihrem aktuellen Anbieter, und wenn die Qualität nicht stimmt,
        zahlen Sie nichts.
      </div>
      <div style="margin-top:14px;">
        <a href="https://f2-malergipser.ch/#kontakt"
           style="display:inline-block;padding:12px 22px;background:{PALETTE['green']};
                  color:#ffffff;font-family:{FONT};font-size:13px;font-weight:700;
                  border-radius:10px;text-decoration:none;letter-spacing:.2px;">
          Jetzt anrufen →
        </a>
      </div>
    </div>
  </div>

  <div class="footer">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td valign="middle" width="68">
          <img src="{LOGO_URL}" width="52" height="52"
               style="display:block;border-radius:50%;background:#ffffff;border:0;">
        </td>
        <td valign="middle">
          <div style="font-family:{FONT};font-size:13px;font-weight:800;color:#ffffff;
                      letter-spacing:.2px;">F2 Maler &amp; Gipser</div>
          <div style="font-family:{FONT};font-size:11px;color:{PALETTE['muted']};
                      margin-top:2px;">Bern · Burgdorf · Emmental · Oberaargau</div>
          <div style="font-family:{FONT};font-size:11px;color:{PALETTE['muted']};
                      margin-top:2px;">
            <a href="https://f2-malergipser.ch" style="color:{PALETTE['green']};
                                                       font-weight:600;">f2-malergipser.ch</a>
            &nbsp;·&nbsp;
            <a href="mailto:info@f2-malergipser.ch" style="color:{PALETTE['green']};
                                                            font-weight:600;">info@f2-malergipser.ch</a>
          </div>
        </td>
        <td valign="middle" align="right" style="font-family:{FONT};font-size:11px;
                                                  color:{PALETTE['muted']};font-style:italic;">
          Gueti Arbeit, wo mä gseht.<br>
          <span style="color:rgba(148,163,171,0.6);">© 2026 F2 Maler &amp; Gipser</span>
        </td>
      </tr>
    </table>
  </div>
</div>

</body>
</html>"""


# Write HTML + render PDF + take a PNG of page 1
html_path = OUT / "wohnungsabnahme-checkliste.html"
pdf_path = OUT / "wohnungsabnahme-checkliste.pdf"
png_path = OUT / "wohnungsabnahme-checkliste-page1.png"
html_path.write_text(HTML, encoding="utf-8")
print(f"wrote {html_path}")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 794, "height": 1123})  # A4 @ 96dpi
    page = ctx.new_page()
    page.goto(html_path.absolute().as_uri(), wait_until="domcontentloaded")
    page.wait_for_timeout(800)

    page.pdf(path=str(pdf_path), format="A4",
              margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
              print_background=True)
    print(f"wrote {pdf_path}")

    # Screenshot just the first page (viewport-sized)
    page.screenshot(path=str(png_path), full_page=False)
    print(f"wrote {png_path}")

    # Also a full-page version for chat preview
    full_png_path = OUT / "wohnungsabnahme-checkliste-fullpage.png"
    page.screenshot(path=str(full_png_path), full_page=True)
    print(f"wrote {full_png_path}")

    ctx.close(); b.close()
