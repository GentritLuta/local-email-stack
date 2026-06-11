"""Custom email template for LK Advertising.

Designed from the brand positioning (the lk-advertising.com domain itself
is parked / 404). Performance-marketing agency identity:
  - Light, modern card
  - Electric blue #0052ff → navy #001b73 gradient bar at top
  - Inter font
  - Slate text on white
  - Clean, professional, mid-market enterprise feel
  - Wordmark in blue, no logo image (no site to source one from)

Body parsing supports line-start em-dash bullets ('— ') converting to
blue-checkmark rows for any future variants that use them; current LK
variant uses prose so it just renders paragraphs.
"""
from __future__ import annotations
import html as _html
from typing import Optional

PAL = {
    "blue":           "#0052ff",
    "blue_dark":      "#001b73",
    "blue_tint":      "#eff6ff",
    "bg":             "#f8fafc",
    "card":           "#ffffff",
    "text":           "#0f172a",
    "text_2":         "#475569",
    "muted":          "#94a3b8",
    "rule":           "#e2e8f0",
}
FONT = ("'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
        "'Helvetica Neue', Arial, sans-serif")


def _esc(s: str) -> str:
    return _html.escape(s, quote=True) if s else ""


def _body_html(body: str) -> str:
    paragraphs = [p for p in body.strip().split("\n\n") if p.strip()]
    out = []
    for para in paragraphs:
        lines = [l for l in para.split("\n") if l.strip()]
        is_bullets = len(lines) >= 2 and all(
            l.strip().startswith("— ") or l.strip().startswith("* ") for l in lines
        )
        if is_bullets:
            bullet_html = ""
            for line in lines:
                stripped = line.strip()
                content = stripped[2:].strip() if stripped[:2] in ("— ", "* ") else stripped
                bullet_html += (
                    f'<tr><td valign="top" style="padding:6px 0;font-family:{FONT};'
                    f'font-size:15px;line-height:1.6;color:{PAL["text"]};">'
                    f'<span style="display:inline-block;width:22px;color:{PAL["blue"]};'
                    f'font-weight:800;font-size:16px;">✓</span>'
                    f'<span>{_esc(content)}</span>'
                    f'</td></tr>'
                )
            out.append(
                f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                f'style="margin:8px 0 16px 0;"><tbody>{bullet_html}</tbody></table>'
            )
        else:
            escaped = _esc(para).replace("\n", "<br>")
            out.append(
                f'<p style="margin:0 0 16px 0;font-family:{FONT};font-size:15px;'
                f'line-height:1.7;color:{PAL["text"]};">{escaped}</p>'
            )
    return "".join(out)


def render_html_lk(*, body: str, persona: dict,
                   unsubscribe_token: Optional[str] = None,
                   brand: Optional[dict] = None,
                   step_n: int = 1) -> str:
    brand = brand or {}
    legal = brand.get("legal") or {}
    body_html = _body_html(body)

    sig_raw = (persona.get("signature") or persona.get("from_name", ""))
    sig_lines = [_esc(l.strip()) for l in sig_raw.split("\n") if l.strip()]
    sig_name = sig_lines[0] if sig_lines else _esc(persona.get("from_name", ""))
    sig_title_lines = sig_lines[1:]

    site = "lk-advertising.com"
    site_url = f"https://{site}"

    tpl = brand.get("unsubscribe_url_template",
                    "https://gentritluta.github.io/local-email-stack/unsubscribe/lk-advertising.html?t={token}")
    unsub_url = tpl.replace("{token}", unsubscribe_token or "preview")

    contact_email = _esc(legal.get("contact_email", "hello@lk-advertising.com"))
    addr = "<br>".join(_esc(l) for l in (legal.get("address_lines") or []))
    year = str(legal.get("copyright_year") or 2026)

    return f"""<!doctype html>
<html lang="de-DE">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <title>LK Advertising</title>
</head>
<body style="margin:0;padding:0;background:{PAL['bg']};font-family:{FONT};">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
       style="background:{PAL['bg']};">
  <tr><td align="center" style="padding:32px 12px;">
    <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0"
           style="max-width:600px;width:100%;background:{PAL['card']};border-radius:12px;
                  overflow:hidden;
                  box-shadow:0 1px 3px rgba(0,82,255,.08),0 4px 16px rgba(0,82,255,.04);">

      <!-- BLUE GRADIENT TOP BAR -->
      <tr><td style="background:linear-gradient(90deg,{PAL['blue']} 0%,{PAL['blue_dark']} 100%);
                     height:6px;line-height:6px;font-size:0;">&nbsp;</td></tr>

      <!-- HERO (light, wordmark-led) -->
      <tr><td style="padding:28px 32px 4px 32px;">
        <div style="font-family:{FONT};font-size:24px;font-weight:800;color:{PAL['blue']};
                    letter-spacing:-.4px;line-height:1.1;">LK Advertising</div>
        <div style="font-family:{FONT};font-size:12.5px;color:{PAL['text_2']};margin-top:6px;
                    font-weight:500;letter-spacing:.2px;">
          Performance-Media für Maklerbüros in Deutschland
        </div>
        <div style="height:1px;background:{PAL['rule']};margin-top:20px;"></div>
      </td></tr>

      <!-- BODY -->
      <tr><td style="padding:24px 32px 8px 32px;">
        {body_html}
      </td></tr>

      {"" if step_n == 1 else f'''
      <!-- CTA (Folgemails ab Schritt 2). href = mailto an die überwachte
           reply-Adresse info@aureonglobal.de, da lk-advertising.com aktuell
           als geparkte Hostinger-Seite 404 zurückgibt. -->
      <tr><td style="padding:0 32px 8px 32px;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0">
          <tr><td style="border-radius:8px;background:{PAL['blue']};">
            <a href="mailto:info@aureonglobal.de?subject=Audit%20Slot%20LK%20Advertising&body=Hallo%20Klara%2C%0A%0AIch%20m%C3%B6chte%20einen%20Audit%20Slot%20reservieren.%0A%0AMein%20Monatsbudget%3A%20%0AMeine%20Stadt%3A%20%0A%0A"
               style="display:inline-block;padding:13px 26px;font-family:{FONT};font-size:14px;
                      font-weight:700;color:#ffffff;text-decoration:none;border-radius:8px;
                      letter-spacing:.2px;">
              Audit Slot reservieren
            </a>
          </td></tr>
        </table>
      </td></tr>'''}

      <!-- SIGNATURE -->
      <tr><td style="padding:22px 32px 28px 32px;">
        <div style="font-family:{FONT};font-size:15px;font-weight:700;color:{PAL['text']};">{sig_name}</div>
        {"".join(f'<div style="font-family:{FONT};font-size:13px;color:{PAL["text_2"]};margin-top:1px;">{l}</div>' for l in sig_title_lines)}
        <div style="font-family:{FONT};font-size:13px;margin-top:4px;">
          <a href="{site_url}" style="color:{PAL['blue']};text-decoration:none;font-weight:600;">{site}</a>
        </div>
      </td></tr>

      <!-- FOOTER (light, professional) -->
      <tr><td style="background:{PAL['blue_tint']};padding:24px 32px;border-top:1px solid {PAL['rule']};">
        <div style="font-family:{FONT};font-size:13px;line-height:1.6;color:{PAL['text_2']};">
          <b style="color:{PAL['text']};">LK Advertising</b><br>
          {addr and addr + '<br>'}
          <a href="mailto:{contact_email}" style="color:{PAL['blue']};text-decoration:none;
                                                   font-weight:600;">{contact_email}</a>
        </div>
        <div style="font-family:{FONT};font-size:12.5px;margin-top:14px;">
          <a href="{site_url}" style="color:{PAL['text_2']};text-decoration:none;margin:0 8px 0 0;">Website</a>
          <span style="color:{PAL['muted']};">·</span>
          <a href="{site_url}/datenschutz" style="color:{PAL['text_2']};text-decoration:none;margin:0 8px;">Datenschutz</a>
          <span style="color:{PAL['muted']};">·</span>
          <a href="{site_url}/agb" style="color:{PAL['text_2']};text-decoration:none;margin:0 8px;">AGB</a>
          <span style="color:{PAL['muted']};">·</span>
          <a href="{_esc(unsub_url)}" style="color:{PAL['text_2']};text-decoration:none;margin:0 8px;">Abmelden</a>
        </div>
        <div style="font-family:{FONT};font-size:11px;color:{PAL['muted']};margin-top:14px;
                    line-height:1.5;">
          © {year} LK Advertising. Alle Rechte vorbehalten.
        </div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
