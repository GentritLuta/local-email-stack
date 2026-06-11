"""Custom email template for ENER-G Beratung — matches ener-g-beratung.de.

Design tokens pulled LIVE from the site (2026-06-07, computed styles):
  - DARK theme. Page bg rgb(16,21,37) = #101525, deeper panel #0B0F20
  - Accent green rgb(34,197,94) = #22C55E ; green-tint panel rgba(34,197,94,.12)
  - Text light #F1F5F9 ; muted #94A3B8 ; secondary #64748B
  - Font: Inter
  - Buttons: solid green, white text, 8px radius, "Kostenlose Analyse"
  - Promise: "100 % transparent. 100 % auf Ihrer Seite."

Reply-based steps (1, 6, 7) omit the CTA button to keep the personal tone;
persuasion steps (2-5) show the green CTA button. Dispatched when
brand.template == "energ-custom".
"""
from __future__ import annotations
import html as _html
from typing import Optional

PAL = {
    "page":     "#070A14",   # outer page (near-black, frames the card)
    "sheet":    "#101525",   # dark navy card (matches site bg)
    "panel":    "#0B0F20",   # deeper panel / bands
    "ink":      "#F1F5F9",   # light heading text
    "body":     "#CBD5E1",   # light body text
    "muted":    "#94A3B8",   # muted grey-blue
    "muted_2":  "#64748B",   # dimmer footer text
    "rule":     "#1E293B",   # subtle dark hairline
    "green":    "#22C55E",   # ENER-G energy green (live accent)
    "green_d":  "#16A34A",
    "green_tint": "#13241F",  # approx rgba(34,197,94,.12) flattened on dark
}
SANS = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"


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


def _energ_logo_inline() -> str:
    """Inline SVG bolt mark (green energy bolt in a rounded square)."""
    return (
        '<svg width="22" height="22" viewBox="0 0 22 22" xmlns="http://www.w3.org/2000/svg" '
        'style="vertical-align:middle;display:inline-block;margin-right:8px;">'
        '<rect x="0" y="0" width="22" height="22" rx="5" fill="#22C55E"/>'
        '<path d="M12 3 L6 12 H10 L9 19 L16 9 H11.5 Z" fill="#101525"/>'
        '</svg>'
    )


def render_html_energ(*, body: str, persona: dict,
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

    site = brand.get("site", "ener-g-beratung.de")
    site_url = f"https://{site}"
    cta_url = brand.get("cta_url") or site_url
    contact_email = _esc(legal.get("contact_email", "info@ener-g-beratung.de"))
    company = _esc(legal.get("company_name", "ENER-G Beratung"))
    addr = legal.get("address_lines") or []
    addr_line = " · ".join(_esc(a) for a in addr)
    priv = _esc(legal.get("privacy_policy_url", f"{site_url}/datenschutz"))
    terms = _esc(legal.get("terms_of_service_url", f"{site_url}/impressum"))

    tpl = brand.get("unsubscribe_url_template",
                    "https://gentritluta.github.io/local-email-stack/unsubscribe/energ.html?t={token}")
    unsub_url = _esc(tpl.replace("{token}", unsubscribe_token or "preview"))

    # CTA only on persuasion steps (2-5).
    cta = ""
    if step_n in (2, 3, 4, 5):
        cta = f"""
      <tr><td style="background:{PAL['sheet']};padding:2px 36px 12px 36px;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0">
          <tr><td style="background:{PAL['green']};border-radius:8px;">
            <a href="{cta_url}" style="display:inline-block;padding:14px 30px;font-family:{SANS};
               font-size:14px;font-weight:700;letter-spacing:0.2px;
               color:#06210F;text-decoration:none;">Kostenlose Analyse &nbsp;&rarr;</a>
          </td></tr>
        </table>
      </td></tr>"""

    # Dark promise band (slightly deeper than the card).
    dark_strip = f"""
      <tr><td style="background:{PAL['panel']};padding:14px 36px;border-top:1px solid {PAL['rule']};">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="font-family:{SANS};font-size:13px;font-weight:700;color:{PAL['ink']};letter-spacing:-0.2px;">
              100 % transparent. 100 % auf Ihrer Seite<span style="color:{PAL['green']};">.</span>
            </td>
            <td align="right" style="font-family:{SANS};font-size:10px;font-weight:400;color:{PAL['muted']};letter-spacing:0.3px;">
              Unabhängige Energieberatung &middot; ener-g-beratung.de
            </td>
          </tr>
        </table>
      </td></tr>"""

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <meta name="color-scheme" content="dark">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <title>ENER-G Beratung</title>
</head>
<body style="margin:0;padding:0;background:{PAL['page']};font-family:{SANS};">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:{PAL['page']};">
  <tr><td align="center" style="padding:28px 12px;">
    <table role="presentation" width="620" cellspacing="0" cellpadding="0" border="0"
           style="max-width:620px;width:100%;background:{PAL['sheet']};border:1px solid {PAL['rule']};border-radius:14px;overflow:hidden;">

      <!-- HEADER -->
      <tr><td style="padding:18px 36px 14px 36px;border-bottom:1px solid {PAL['rule']};">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="line-height:1;">
              {_energ_logo_inline()}<span style="font-family:{SANS};font-size:20px;font-weight:800;
                                                  color:{PAL['ink']};letter-spacing:-0.3px;
                                                  vertical-align:middle;">ENER-G<span style="color:{PAL['green']};">.</span></span><span
                style="font-family:{SANS};font-size:13px;font-weight:500;color:{PAL['muted']};
                       vertical-align:middle;margin-left:6px;letter-spacing:0.2px;">Beratung</span>
            </td>
            <td align="right" style="font-family:{SANS};font-size:10px;font-weight:500;
                       color:{PAL['muted']};letter-spacing:1.2px;text-transform:uppercase;">
              Energiekosten senken<span style="color:{PAL['green']};">.</span>
            </td>
          </tr>
        </table>
      </td></tr>

      <!-- BODY -->
      <tr><td style="padding:20px 36px 6px 36px;">
        {body_html}
      </td></tr>
{cta}
      <!-- SIGNATURE -->
      <tr><td style="padding:10px 36px 18px 36px;border-top:1px solid {PAL['rule']};">
        <div style="font-family:{SANS};font-size:15px;font-weight:700;color:{PAL['ink']};
                    letter-spacing:-0.2px;">{sig_name}</div>
        {"".join(f'<div style="font-family:{SANS};font-size:12px;font-weight:400;color:{PAL["muted"]};margin-top:2px;">{l}</div>' for l in sig_rest)}
        <div style="font-family:{SANS};font-size:12px;margin-top:6px;font-weight:600;">
          <a href="{site_url}" style="color:{PAL['green']};text-decoration:none;">{_esc(site)} &rarr;</a>
        </div>
      </td></tr>

      <!-- DARK PROMISE STRIP -->
{dark_strip}

      <!-- FOOTER -->
      <tr><td style="background:{PAL['sheet']};padding:12px 36px 16px 36px;border-top:1px solid {PAL['rule']};">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="font-family:{SANS};font-size:10px;color:{PAL['muted_2']};line-height:1.5;">
              <strong style="color:{PAL['ink']};font-weight:700;">{company}<span style="color:{PAL['green']};">.</span></strong> &middot; {addr_line} &middot;
              <a href="mailto:{contact_email}" style="color:{PAL['green']};text-decoration:none;">{contact_email}</a>
            </td>
            <td align="right" style="font-family:{SANS};font-size:10px;color:{PAL['muted_2']};white-space:nowrap;">
              <a href="{priv}" style="color:{PAL['muted_2']};text-decoration:underline;">Datenschutz</a> &middot;
              <a href="{terms}" style="color:{PAL['muted_2']};text-decoration:underline;">Impressum</a> &middot;
              <a href="{unsub_url}" style="color:{PAL['muted_2']};text-decoration:underline;">Abmelden</a>
            </td>
          </tr>
        </table>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
