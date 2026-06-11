"""Custom email template for Atal SolidRocks — matches atalsolidrocks.com.

Editorial / print aesthetic pulled live from the site:
  - Warm cream paper (#f7f3ec) background, near-white sheet (#fdfbf6)
  - Fraunces serif wordmark + headings (Georgia fallback for Gmail etc.)
  - Inter body in warm taupe (#5a544b)
  - Sharp square (border-radius:0) terracotta-red CTA (#c5302a), cream text
  - Hairline cream rules, no shadows, no rounded corners
  - Reply-based steps (1,6,7) omit the CTA button to keep the personal tone

Brand fields flow through from profiles/atalsolidrocks.json (site, legal,
unsubscribe template), so finalizing the profile updates every send.
"""
from __future__ import annotations
import html as _html
from typing import Optional

PAL = {
    "page":        "#f7f3ec",   # cream page bg
    "sheet":       "#fdfbf6",   # near-white warm sheet
    "ink":         "#1f1b16",   # near-black headings
    "body":        "#5a544b",   # warm taupe body text
    "muted":       "#8c8579",   # muted footer text
    "rule":        "#e6ddc9",   # hairline cream rule
    "red":         "#c5302a",   # terracotta CTA / accent
    "navy":        "#0b2f6b",   # secondary label accent
}
SERIF = "'Fraunces', Georgia, 'Times New Roman', Times, serif"
SANS  = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
LOGO  = "https://atalsolidrocks.com/logo.png"


def _esc(s: str) -> str:
    return _html.escape(s, quote=True) if s else ""


def _body_html(body: str) -> str:
    out = []
    for para in [p for p in body.strip().split("\n\n") if p.strip()]:
        escaped = _esc(para).replace("\n", "<br>")
        out.append(
            f'<p style="margin:0 0 18px 0;font-family:{SANS};font-size:16px;'
            f'line-height:1.72;color:{PAL["body"]};">{escaped}</p>'
        )
    return "".join(out)


def render_html_atalsolidrocks(*, body: str, persona: dict,
                               unsubscribe_token: Optional[str] = None,
                               brand: Optional[dict] = None,
                               step_n: int = 1) -> str:
    brand = brand or {}
    legal = brand.get("legal") or {}

    body_html = _body_html(body)

    sig_raw = persona.get("signature") or persona.get("from_name", "")
    sig_lines = [_esc(l.strip()) for l in sig_raw.split("\n") if l.strip()]
    sig_name = sig_lines[0] if sig_lines else _esc(persona.get("from_name", ""))
    sig_rest = sig_lines[1:]

    site = brand.get("site", "atalsolidrocks.com")
    site_url = f"https://{site}"
    contact_email = _esc(legal.get("contact_email", "info@atalsolidrocks.com"))
    company = _esc(legal.get("company_name", "Atal SolidRocks"))
    addr = legal.get("address_lines") or []
    addr_line = " · ".join(_esc(a) for a in addr)
    year = str(legal.get("copyright_year") or 2026)
    priv = _esc(legal.get("privacy_policy_url", f"{site_url}/datenschutz"))
    terms = _esc(legal.get("terms_of_service_url", f"{site_url}/agb"))

    tpl = brand.get("unsubscribe_url_template",
                    "https://gentritluta.github.io/local-email-stack/unsubscribe/atalsolidrocks.html?t={token}")
    unsub_url = _esc(tpl.replace("{token}", unsubscribe_token or "preview"))

    # CTA only on the persuasion steps (2-5); reply/value/breakup steps stay clean.
    cta = ""
    if step_n in (2, 3, 4, 5):
        cta = f"""
      <tr><td style="background:{PAL['sheet']};padding:6px 40px 8px 40px;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0">
          <tr><td style="background:{PAL['red']};border-radius:0;">
            <a href="{site_url}" style="display:inline-block;padding:14px 30px;font-family:{SANS};
               font-size:13px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase;
               color:{PAL['page']};text-decoration:none;border-radius:0;">Vorgespräch vereinbaren</a>
          </td></tr>
        </table>
      </td></tr>"""

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <title>Atal SolidRocks</title>
</head>
<body style="margin:0;padding:0;background:{PAL['page']};font-family:{SANS};">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:{PAL['page']};">
  <tr><td align="center" style="padding:28px 12px;">
    <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0"
           style="max-width:600px;width:100%;background:{PAL['sheet']};border:1px solid {PAL['rule']};border-radius:0;">

      <!-- HEADER: logo + serif wordmark + red rule + kicker -->
      <tr><td style="padding:34px 40px 18px 40px;border-bottom:1px solid {PAL['rule']};">
        <img src="{LOGO}" width="44" height="44" alt="Atal SolidRocks"
             style="display:block;border:0;outline:none;margin:0 0 14px 0;">
        <div style="font-family:{SERIF};font-size:26px;font-weight:600;color:{PAL['ink']};
                    letter-spacing:-0.3px;line-height:1;">Atal Solidrocks</div>
        <div style="height:3px;width:40px;background:{PAL['red']};margin:12px 0 10px 0;"></div>
        <div style="font-family:{SANS};font-size:11px;font-weight:600;color:{PAL['muted']};
                    letter-spacing:1.8px;text-transform:uppercase;">
          Präventionsseminare &nbsp;·&nbsp; DACH Mittelstand
        </div>
      </td></tr>

      <!-- BODY -->
      <tr><td style="padding:26px 40px 6px 40px;">
        {body_html}
      </td></tr>
{cta}
      <!-- SIGNATURE -->
      <tr><td style="padding:20px 40px 26px 40px;border-top:1px solid {PAL['rule']};">
        <div style="font-family:{SERIF};font-size:17px;font-weight:600;color:{PAL['ink']};">{sig_name}</div>
        {"".join(f'<div style="font-family:{SANS};font-size:13px;color:{PAL["muted"]};margin-top:3px;">{l}</div>' for l in sig_rest)}
        <div style="font-family:{SANS};font-size:13px;margin-top:8px;">
          <a href="{site_url}" style="color:{PAL['red']};text-decoration:none;font-weight:600;">{_esc(site)}</a>
        </div>
      </td></tr>

      <!-- FOOTER -->
      <tr><td style="background:{PAL['page']};padding:22px 40px 26px 40px;border-top:1px solid {PAL['rule']};">
        <div style="font-family:{SERIF};font-size:14px;font-weight:600;color:{PAL['ink']};letter-spacing:.2px;">{company}</div>
        <div style="font-family:{SANS};font-size:11px;color:{PAL['muted']};margin-top:6px;line-height:1.7;">
          {addr_line}<br>
          <a href="mailto:{contact_email}" style="color:{PAL['navy']};text-decoration:none;">{contact_email}</a>
        </div>
        <div style="font-family:{SANS};font-size:11px;margin-top:12px;color:{PAL['muted']};">
          <a href="{priv}" style="color:{PAL['muted']};text-decoration:underline;margin-right:10px;">Datenschutz</a>
          <a href="{terms}" style="color:{PAL['muted']};text-decoration:underline;margin-right:10px;">AGB</a>
          <a href="{unsub_url}" style="color:{PAL['muted']};text-decoration:underline;">Abmelden</a>
        </div>
        <div style="font-family:{SANS};font-size:10px;color:#b8ae9a;margin-top:14px;">© {year} {company}</div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
