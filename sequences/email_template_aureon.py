"""Custom email template for Aureon Global.

Mirrors aureonglobal.de's premium dark-on-gold visual identity:
  - Near-black hero (#050505) with inlined gold-gradient globe SVG logo
  - Gold #d4af37 accents and CTA pill
  - Inter font stack
  - Uppercase tagline pair (REAL ESTATE GROWTH PARTNER)
  - Light prose body card
  - Premium dark footer with L.L.C. legal block + gold accent rule
"""
from __future__ import annotations
import html as _html
from typing import Optional

PAL = {
    "bg":          "#050505",
    "card":        "#ffffff",
    "text":        "#0a0a0a",
    "text_2":      "#4b5563",
    "muted":       "#9ca3af",
    "gold":        "#d4af37",
    "gold_dark":   "#b8941f",
    "slate":       "#1a1a1a",
    "rule":        "#ececec",
}
FONT = ("'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
        "'Helvetica Neue', Arial, sans-serif")

# The exact globe SVG extracted from aureonglobal.de — inlined so no
# external URL is needed and the logo always renders.
AUREON_LOGO_SVG = """<svg width="56" height="56" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" style="filter:drop-shadow(0 2px 10px rgba(212,175,55,0.4));display:block;">
  <defs>
    <linearGradient id="aureonGlobeGradient" x1="10%" y1="10%" x2="90%" y2="90%">
      <stop offset="5%"  stop-color="#FFF8D6"/>
      <stop offset="35%" stop-color="#E6C259"/>
      <stop offset="65%" stop-color="#B68E2D"/>
      <stop offset="95%" stop-color="#755615"/>
    </linearGradient>
  </defs>
  <g fill="url(#aureonGlobeGradient)">
    <ellipse cx="50" cy="15" rx="20" ry="7"/>
    <path d="M 18 26 Q 50 33 82 26 L 82 34 Q 50 41 18 34 Z"/>
    <path d="M 8 40 Q 50 47 92 40 L 92 49 Q 50 56 8 49 Z"/>
    <path d="M 8 55 Q 50 62 92 55 L 92 64 Q 50 71 8 64 Z"/>
    <path d="M 18 70 Q 50 77 82 70 L 82 78 Q 50 85 18 78 Z"/>
    <path d="M 32 84 Q 50 89 68 84 L 68 89 Q 50 94 32 89 Z"/>
  </g>
</svg>"""


def _esc(s: str) -> str:
    return _html.escape(s, quote=True) if s else ""


def _body_html(body: str) -> str:
    paragraphs = [p for p in body.strip().split("\n\n") if p.strip()]
    out = []
    for para in paragraphs:
        escaped = _esc(para).replace("\n", "<br>")
        out.append(
            f'<p style="margin:0 0 16px 0;font-family:{FONT};font-size:15px;'
            f'line-height:1.7;color:{PAL["text"]};">{escaped}</p>'
        )
    return "".join(out)


def render_html_aureon(*, body: str, persona: dict,
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

    site = "aureonglobal.de"
    site_url = f"https://{site}"

    tpl = brand.get("unsubscribe_url_template",
                    "https://gentritluta.github.io/local-email-stack/unsubscribe/aureon.html?t={token}")
    unsub_url = tpl.replace("{token}", unsubscribe_token or "preview")

    company_name = _esc(legal.get("company_name", "Aureon Global L.L.C."))
    addr = "<br>".join(_esc(l) for l in (legal.get("address_lines") or []))
    contact_email = _esc(legal.get("contact_email", "info@aureonglobal.de"))
    vat = _esc(legal.get("vat_number", ""))
    reg = _esc(legal.get("registration_number", ""))
    year = str(legal.get("copyright_year") or 2026)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <title>Aureon Global</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
  <style>@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');</style>
</head>
<body style="margin:0;padding:0;background:{PAL['bg']};font-family:{FONT};">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
       style="background:{PAL['bg']};">
  <tr><td align="center" style="padding:24px 12px;">
    <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0"
           style="max-width:600px;width:100%;background:{PAL['card']};border-radius:6px;
                  overflow:hidden;border:1px solid {PAL['slate']};">

      <!-- BODY (no top header, email opens straight into the message) -->
      <tr><td style="padding:32px 36px 4px 36px;background:{PAL['card']};">
        {body_html}
      </td></tr>

      {"" if step_n in (1, 6, 7) else f'''
      <!-- CTA (persuasion steps 2-5 only). Steps 1, 6, 7 explicitly tell
      the prospect no call is required (cold opener, pure-value gift, and
      breakup respectively) — showing the button there contradicts the body
      and undermines the offer. -->
      <tr><td style="padding:0 36px 8px 36px;background:{PAL['card']};">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0">
          <tr><td style="border-radius:4px;background:{PAL['gold']};">
            <a href="https://calendly.com/aureonglobal-info/30min"
               style="display:inline-block;padding:13px 26px;font-family:{FONT};font-size:14px;
                      font-weight:700;color:{PAL['bg']};text-decoration:none;border-radius:4px;
                      letter-spacing:.3px;">
              Book a 30 minute call
            </a>
          </td></tr>
        </table>
      </td></tr>'''}

      <!-- SIGNATURE -->
      <tr><td style="padding:24px 36px 32px 36px;background:{PAL['card']};">
        <div style="font-family:{FONT};font-size:15px;font-weight:700;color:{PAL['text']};">{sig_name}</div>
        {"".join(f'<div style="font-family:{FONT};font-size:13px;color:{PAL["text_2"]};margin-top:1px;">{l}</div>' for l in sig_title_lines)}
        <div style="font-family:{FONT};font-size:13px;margin-top:4px;">
          <a href="{site_url}" style="color:{PAL['gold']};text-decoration:none;font-weight:600;">{site}</a>
        </div>
      </td></tr>

      <!-- FOOTER (single dark corporate block, kept as provided; only the
           logo src and Privacy/Terms hrefs corrected). -->
      <tr><td style="padding:0;">
        <div style="background-color:#050505;padding:40px 30px;text-align:center;color:#999999;border-top:4px solid #d4af37;font-family:Verdana,sans-serif;">
          <table width="100%" border="0" cellspacing="0" cellpadding="0">
            <tbody>
              <tr>
                <td align="center">
                  <div style="margin-bottom:20px;padding-top:20px;border-top:1px solid #1a1a1a;">
                    <a href="https://aureonglobal.de" style="text-decoration:none;">
                      <img src="https://aureonglobal.de/logo.png" alt="Aureon Global Logo" width="50" style="display:block;margin:0 auto 10px auto;">
                      <span style="color:rgb(255,255,255);font-weight:800;text-transform:uppercase;letter-spacing:1px;display:block;margin-bottom:5px;">
                        <span class="size" style="font-size:16px">AUREON GLOBAL LLC</span>
                      </span>
                    </a>
                  </div>
                  <p style="font-size:12px;line-height:1.6;margin:5px 0;color:#888888;">
                    <b style="color:#ffffff;">Aureon Global L.L.C.</b>
                    <br>
                    Dushkaja 20, 71000 Kacanik,
                    <br>
                    Republic of Kosovo
                  </p>
                  <p style="font-size:12px;line-height:1.6;margin:5px 0;">
                    <a href="mailto:info@aureonglobal.de" style="color:#d4af37;text-decoration:none;font-weight:500;">info@aureonglobal.de</a>
                  </p>
                  <p style="font-size:12px;line-height:1.6;margin:10px 0;">
                    <a href="https://aureonglobal.de" style="color:#d4af37;text-decoration:none;margin:0 8px;font-weight:500;">Website</a>
                    <span style="color:#333333;margin:0 4px;">|</span>
                    <a href="https://aureonglobal.de/privacy.html" style="color:#d4af37;text-decoration:none;margin:0 8px;font-weight:500;">Privacy Policy</a>
                    <span style="color:#333333;margin:0 4px;">|</span>
                    <a href="https://aureonglobal.de/terms.html" style="color:#d4af37;text-decoration:none;margin:0 8px;font-weight:500;">Terms of Service</a>
                  </p>
                  <div style="margin-top:25px;padding-top:25px;border-top:1px solid #1a1a1a;">
                    <p style="font-size:10px;color:#555555;margin:0;">
                      © 2026 Aureon Global LLC. All rights reserved.
                      <br>
                      VAT ID: 330681892 | Reg. No: 812368240
                    </p>
                    <p style="font-size:10px;color:#444444;margin-top:10px;line-height:1.4;">You are receiving this email because you are a registered partner or have requested information from Aureon Global.</p>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
