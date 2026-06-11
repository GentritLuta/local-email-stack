"""Custom email template for Diraya — matches diraya.ca (verified 2026-05-31).

Pulled from the live site via headless browser DOM inspection:
  - Wordmark: "Diraya Inc." in bold Kanit + ORANGE dot accent
  - Tiny square logo icon: orange + dark grey blocks
  - Accent: warm orange #FF6B00 (verified from live CSS)
  - Body text: warm dark grey #454545 (verified)
  - Font: Kanit (Google Fonts) — display sans, used for both heading and body
  - Pages alternate white sheets with full-bleed near-black sections
  - Headings are very bold, tight letterspacing, title case (NOT uppercase)
  - Tiny kicker pattern: short horizontal rule + small grey label, often with
    a trailing orange dot
  - Reply-based steps (1,6,7) omit the CTA button to keep the personal tone
"""
from __future__ import annotations
import html as _html
from typing import Optional

PAL = {
    "page":     "#FFFFFF",   # pure white page
    "sheet":    "#FFFFFF",   # pure white sheet
    "ink":      "#0A0A0A",   # near-black for headings (matches site H1)
    "body":     "#454545",   # warm dark grey body text (verified from site)
    "muted":    "#8A8A8A",   # muted grey for kicker/footer
    "rule":     "#E8E8E8",   # hairline rule
    "orange":   "#FF6B00",   # Diraya brand orange (verified from site)
    "orange_d": "#CC5500",   # darker orange for hover-ish accent
    "dark":     "#0A0A0A",   # near-black for the dark service-section feel
}
SANS = "'Kanit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
LOGO = "https://diraya.ca/logo.png"


def _esc(s: str) -> str:
    return _html.escape(s, quote=True) if s else ""


def _body_html(body: str) -> str:
    out = []
    for para in [p for p in body.strip().split("\n\n") if p.strip()]:
        escaped = _esc(para).replace("\n", "<br>")
        out.append(
            f'<p style="margin:0 0 18px 0;font-family:{SANS};font-size:16px;'
            f'line-height:1.7;color:{PAL["body"]};font-weight:400;">{escaped}</p>'
        )
    return "".join(out)


def _diraya_logo_inline() -> str:
    """Small inline SVG of the Diraya icon: orange + dark squares.
    Matches the site logo so emails render even when external images are blocked."""
    return (
        '<svg width="22" height="22" viewBox="0 0 22 22" xmlns="http://www.w3.org/2000/svg" '
        'style="vertical-align:middle;display:inline-block;margin-right:8px;">'
        '<rect x="0" y="0" width="14" height="14" fill="#0A0A0A"/>'
        '<rect x="8" y="8" width="14" height="14" fill="#FF6B00"/>'
        '</svg>'
    )


def render_html_diraya(*, body: str, persona: dict,
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

    site = brand.get("site", "diraya.ca")
    site_url = f"https://{site}"
    # CTA button target: the client's live booking flow (Calendly). Falls back
    # to the brand site if no cta_url is set. Wordmark/footer still use site_url.
    cta_url = brand.get("cta_url") or site_url
    contact_email = _esc(legal.get("contact_email", "info@diraya.ca"))
    company = _esc(legal.get("company_name", "Diraya Inc"))
    addr = legal.get("address_lines") or []
    addr_line = " · ".join(_esc(a) for a in addr)
    year = str(legal.get("copyright_year") or 2026)
    priv = _esc(legal.get("privacy_policy_url", f"{site_url}/privacy"))
    terms = _esc(legal.get("terms_of_service_url", f"{site_url}/terms"))

    tpl = brand.get("unsubscribe_url_template",
                    "https://gentritluta.github.io/local-email-stack/unsubscribe/diraya.html?t={token}")
    unsub_url = _esc(tpl.replace("{token}", unsubscribe_token or "preview"))

    # CTA only on persuasion steps (2-5); reply/value/breakup stay clean.
    cta = ""
    if step_n in (2, 3, 4, 5):
        cta = f"""
      <tr><td style="background:{PAL['sheet']};padding:2px 36px 10px 36px;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0">
          <tr><td style="background:{PAL['orange']};">
            <a href="{cta_url}" style="display:inline-block;padding:11px 24px;font-family:{SANS};
               font-size:12px;font-weight:600;letter-spacing:0.5px;text-transform:uppercase;
               color:#ffffff;text-decoration:none;">Book a 15-minute call &nbsp;&rarr;</a>
          </td></tr>
        </table>
      </td></tr>"""

    # Dark band — single tight row, echoes diraya.ca's dark service sections.
    dark_strip = f"""
      <tr><td style="background:{PAL['dark']};padding:12px 36px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="font-family:{SANS};font-size:13px;font-weight:700;color:#ffffff;letter-spacing:-0.2px;">
              The Future Starts Now<span style="color:{PAL['orange']};">.</span>
            </td>
            <td align="right" style="font-family:{SANS};font-size:10px;font-weight:400;color:#B8B8B8;letter-spacing:0.3px;">
              Custom AI engineering &middot; diraya.ca
            </td>
          </tr>
        </table>
      </td></tr>"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Kanit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <title>Diraya</title>
</head>
<body style="margin:0;padding:0;background:#F4F4F4;font-family:{SANS};">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#F4F4F4;">
  <tr><td align="center" style="padding:28px 12px;">
    <table role="presentation" width="620" cellspacing="0" cellpadding="0" border="0"
           style="max-width:620px;width:100%;background:{PAL['sheet']};border:1px solid {PAL['rule']};">

      <!-- HEADER: logo icon + wordmark with orange dot + kicker on the right -->
      <tr><td style="padding:18px 36px 14px 36px;border-bottom:1px solid {PAL['rule']};">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="line-height:1;">
              {_diraya_logo_inline()}<span style="font-family:{SANS};font-size:20px;font-weight:700;
                                                  color:{PAL['ink']};letter-spacing:-0.3px;
                                                  vertical-align:middle;">Diraya Inc<span style="color:{PAL['orange']};">.</span></span>
            </td>
            <td align="right" style="font-family:{SANS};font-size:10px;font-weight:500;
                       color:{PAL['muted']};letter-spacing:1.4px;text-transform:uppercase;">
              The Future Starts Now<span style="color:{PAL['orange']};">.</span>
            </td>
          </tr>
        </table>
      </td></tr>

      <!-- BODY -->
      <tr><td style="padding:18px 36px 4px 36px;">
        {body_html}
      </td></tr>
{cta}
      <!-- SIGNATURE -->
      <tr><td style="padding:8px 36px 16px 36px;border-top:1px solid {PAL['rule']};">
        <div style="font-family:{SANS};font-size:15px;font-weight:700;color:{PAL['ink']};
                    letter-spacing:-0.2px;">{sig_name}</div>
        {"".join(f'<div style="font-family:{SANS};font-size:12px;font-weight:400;color:{PAL["muted"]};margin-top:2px;">{l}</div>' for l in sig_rest)}
        <div style="font-family:{SANS};font-size:12px;margin-top:6px;font-weight:500;">
          <a href="{site_url}" style="color:{PAL['orange']};text-decoration:none;">{_esc(site)} &rarr;</a>
        </div>
      </td></tr>

      <!-- DARK TAGLINE STRIP (single-row, tight) -->
{dark_strip}

      <!-- FOOTER (compact) -->
      <tr><td style="background:{PAL['page']};padding:10px 36px 14px 36px;border-top:1px solid {PAL['rule']};">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="font-family:{SANS};font-size:10px;color:{PAL['muted']};line-height:1.5;">
              <strong style="color:{PAL['ink']};font-weight:700;">{company}<span style="color:{PAL['orange']};">.</span></strong> &middot; {addr_line} &middot;
              <a href="mailto:{contact_email}" style="color:{PAL['orange']};text-decoration:none;">{contact_email}</a>
            </td>
            <td align="right" style="font-family:{SANS};font-size:10px;color:{PAL['muted']};white-space:nowrap;">
              <a href="{priv}" style="color:{PAL['muted']};text-decoration:underline;">Privacy</a> &middot;
              <a href="{terms}" style="color:{PAL['muted']};text-decoration:underline;">Terms</a> &middot;
              <a href="{unsub_url}" style="color:{PAL['muted']};text-decoration:underline;">Unsubscribe</a>
            </td>
          </tr>
        </table>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
