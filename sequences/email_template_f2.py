"""Custom email template for F2 Maler & Gipser.

Mirrors the visual identity of f2-malergipser.ch:
  - Dark teal hero strip with F2 logo + "HANDWERKSKUNST SEIT 2007" line
  - Plus Jakarta Sans typography (with safe fallbacks)
  - Cream/white body section with em-dash bullets converted to green checkmarks
  - Bright green CTA button (#6ba94c, 10px radius, weight 700)
  - Dark teal footer matching the site's footer bar
  - Slate-on-white signature block
  - Swiss-German tagline below the logo

Designed for cold outreach: looks branded but stays close enough to a
personal email that it doesn't read as marketing automation. No marketing
hero, no oversized banners.

NOT a drop-in replacement for the generic render_html(). Invoked only when
profile.brand.template == "f2-custom".
"""
from __future__ import annotations

import html
import re
from typing import Optional


# F2 brand palette (extracted live from f2-malergipser.ch)
PALETTE = {
    "teal_dark":     "#0a2620",   # hero + footer bg (deep teal)
    "teal_dark_2":   "#0f2e2a",   # subtle gradient stop
    "green":         "#6ba94c",   # CTA / accent
    "green_dark":    "#5a9340",   # green hover (text shadows)
    "text_dark":     "#1a2332",   # body slate
    "text_muted":    "#475569",   # secondary text
    "card_bg":       "#ffffff",   # main email card
    "section_bg":    "#f9f9f5",   # warm cream body bg
    "divider":       "#e2e8f0",   # rule lines
    "footer_muted":  "#94a3ab",   # footer secondary text
}

# Font stack — Plus Jakarta Sans declared, with email-safe fallbacks
FONT = ("'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', "
        "Roboto, 'Helvetica Neue', Arial, sans-serif")


def _esc(s: str) -> str:
    return html.escape(s, quote=True) if s else ""


def _body_html(body: str, palette: dict) -> str:
    """Convert plain-text body into styled HTML.

    Line-starting "— " becomes a green checkmark bullet row.
    Blank lines become paragraph breaks.
    Other content stays as flowing paragraphs.
    """
    # Split into paragraphs (double-newline separated)
    paragraphs = [p for p in body.strip().split("\n\n") if p.strip()]
    out = []

    for para in paragraphs:
        lines = [l for l in para.split("\n") if l.strip()]
        # Treat as a bullet list only if 2+ lines AND every line starts with
        # the bullet marker. Supports "* " (preferred — no em-dash tell) or
        # legacy "— ". The marker is stripped from each rendered row.
        markers = ("* ", "— ")
        is_bullet_list = len(lines) >= 2 and all(
            any(l.strip().startswith(m) for m in markers) for l in lines
        )
        if is_bullet_list:
            # Render as styled bullet rows with green checkmarks
            bullet_html = ""
            for line in lines:
                stripped = line.strip()
                content_raw = None
                for m in markers:
                    if stripped.startswith(m):
                        content_raw = stripped[len(m):].strip()
                        break
                if content_raw is None:
                    continue
                content = _esc(content_raw)
                bullet_html += (
                    f'<tr><td valign="top" style="padding:6px 0;font-family:{FONT};'
                    f'font-size:15px;line-height:1.6;color:{palette["text_dark"]};">'
                    f'<span style="display:inline-block;width:22px;color:{palette["green"]};'
                    f'font-weight:800;font-size:16px;line-height:1.6;">✓</span>'
                    f'<span>{content}</span>'
                    f'</td></tr>'
                )
            out.append(
                f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                f'style="margin:8px 0 16px 0;"><tbody>{bullet_html}</tbody></table>'
            )
        else:
            # Regular paragraph — keep \n as <br> within
            escaped = _esc(para).replace("\n", "<br>")
            out.append(
                f'<p style="margin:0 0 16px 0;font-family:{FONT};font-size:15px;'
                f'line-height:1.7;color:{palette["text_dark"]};">{escaped}</p>'
            )

    return "".join(out)


def render_html_f2(*, body: str, persona: dict, unsubscribe_token: Optional[str] = None,
                    brand: Optional[dict] = None, step_n: int = 1) -> str:
    """Render an F2-custom HTML email.

    Args mirror email_render.render_html() so the call site is the same.
    """
    p = PALETTE
    brand = brand or {}
    legal = brand.get("legal") or {}
    logo_url = _esc(legal.get("logo_url", ""))

    # Signature lines from persona
    sig_raw = (persona.get("signature") or persona.get("from_name", ""))
    sig_lines = [_esc(l.strip()) for l in sig_raw.split("\n") if l.strip()]
    sig_name = sig_lines[0] if sig_lines else _esc(persona.get("from_name", ""))
    sig_title_lines = sig_lines[1:]

    site = _esc(brand.get("site") or "f2-malergipser.ch")
    site_url = f"https://{site}"

    body_html = _body_html(body, p)

    # Unsubscribe URL
    tpl = brand.get("unsubscribe_url_template",
                    "https://gentritluta.github.io/local-email-stack/unsubscribe.html?t={token}")
    unsub_url = tpl.replace("{token}", unsubscribe_token or "preview") if unsubscribe_token else (
        tpl.replace("{token}", "preview")
    )

    # Address block
    addr_lines = legal.get("address_lines") or []
    addr_html = "<br>".join(_esc(l) for l in addr_lines)
    email = _esc(legal.get("contact_email", "info@f2-malergipser.ch"))
    year = str(legal.get("copyright_year") or 2026)

    # Hero logo image (left-aligned, small)
    hero_logo = (
        f'<img src="{logo_url}" alt="F2 Maler Gipser" width="56" height="56" '
        f'style="display:block;border:0;border-radius:50%;background:#ffffff;">'
        if logo_url else ""
    )

    # Footer logo (white-background contained circle to match hero treatment)
    footer_logo = (
        f'<img src="{logo_url}" alt="F2 Maler Gipser" width="64" height="64" '
        f'style="display:block;margin:0 auto 12px auto;border:0;border-radius:50%;background:#ffffff;">'
        if logo_url else ""
    )

    return f"""<!doctype html>
<html lang="de-CH">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <title>F2 Maler &amp; Gipser</title>
</head>
<body style="margin:0;padding:0;background:{p['section_bg']};font-family:{FONT};">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
       style="background:{p['section_bg']};">
  <tr><td align="center" style="padding:24px 12px;">
    <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0"
           style="max-width:600px;width:100%;background:{p['card_bg']};border-radius:12px;
                  overflow:hidden;box-shadow:0 1px 3px rgba(15,46,42,0.06);">

      <!-- ── HERO STRIP (dark teal, matches site hero band) ── -->
      <tr><td style="background:{p['teal_dark']};
                     background-image:linear-gradient(135deg,{p['teal_dark_2']} 0%,{p['teal_dark']} 100%);
                     padding:24px 28px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td valign="middle" width="64" style="padding-right:14px;">
              {hero_logo}
            </td>
            <td valign="middle">
              <div style="font-family:{FONT};font-size:17px;font-weight:800;letter-spacing:.2px;
                          color:#ffffff;line-height:1.2;">F2 Maler &amp; Gipser</div>
              <div style="font-family:{FONT};font-size:11px;font-weight:700;letter-spacing:1.2px;
                          color:{p['green']};text-transform:uppercase;margin-top:3px;">
                Handwerkskunst seit 2007
              </div>
            </td>
            <td valign="middle" align="right" style="font-family:{FONT};font-size:12px;
                                                       color:{p['footer_muted']};line-height:1.4;
                                                       text-align:right;">
              <div style="color:#ffffff;font-weight:600;">Bern · Burgdorf</div>
              <div style="font-style:italic;">Gueti Arbeit, wo mä gseht.</div>
            </td>
          </tr>
        </table>
      </td></tr>

      <!-- ── BODY ── -->
      <tr><td style="padding:32px 32px 8px 32px;background:{p['card_bg']};">
        {body_html}
      </td></tr>

      {"" if step_n in (1, 6, 7) else f'''
      <!-- ── CTA (Persuasions-Schritte 2-5). Schritt 6 ist das reine
           Wertgeschenk ("Kein Anruf, kein Verkaufsgespräch") und Schritt 7
           ist die Soft-Breakup-Mail — beide widersprechen dem Button. ── -->
      <tr><td style="padding:0 32px 8px 32px;background:{p['card_bg']};">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0">
          <tr><td style="border-radius:10px;background:{p['green']};">
            <a href="{site_url}/#kontakt"
               style="display:inline-block;padding:14px 26px;font-family:{FONT};font-size:14px;
                      font-weight:700;color:#ffffff;text-decoration:none;border-radius:10px;
                      letter-spacing:.2px;">
              Jetzt anrufen
            </a>
          </td></tr>
        </table>
      </td></tr>'''}

      <!-- ── SIGNATURE ── -->
      <tr><td style="padding:24px 32px 28px 32px;background:{p['card_bg']};">
        <div style="font-family:{FONT};font-size:15px;font-weight:700;
                    color:{p['text_dark']};">{sig_name}</div>
        {"".join(f'<div style="font-family:{FONT};font-size:13px;color:{p["text_muted"]};margin-top:1px;">{l}</div>' for l in sig_title_lines)}
        <div style="font-family:{FONT};font-size:13px;margin-top:4px;">
          <a href="{site_url}" style="color:{p['green']};text-decoration:none;font-weight:600;">{site}</a>
        </div>
      </td></tr>

      <!-- ── FOOTER (dark teal, matches site footer) ── -->
      <tr><td style="background:{p['teal_dark']};padding:36px 32px 28px 32px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr><td align="center" style="padding-bottom:18px;border-bottom:1px solid rgba(255,255,255,0.08);">
            {footer_logo}
            <div style="font-family:{FONT};font-size:16px;font-weight:800;color:#ffffff;
                        letter-spacing:.2px;">F2 Maler &amp; Gipser</div>
            <div style="font-family:{FONT};font-size:11px;font-weight:700;letter-spacing:1.2px;
                        color:{p['green']};text-transform:uppercase;margin-top:4px;">
              Handwerkskunst seit 2007
            </div>
          </td></tr>
          <tr><td align="center" style="padding-top:18px;">
            <div style="font-family:{FONT};font-size:13px;line-height:1.65;
                        color:{p['footer_muted']};">
              {addr_html}<br>
              <a href="mailto:{email}" style="color:{p['green']};text-decoration:none;font-weight:600;">{email}</a>
            </div>
            <div style="font-family:{FONT};font-size:13px;margin-top:14px;color:{p['footer_muted']};">
              <a href="{site_url}" style="color:#ffffff;text-decoration:none;margin:0 8px;">Website</a>
              <span style="opacity:0.4;">|</span>
              <a href="https://{site}/datenschutz" style="color:#ffffff;text-decoration:none;margin:0 8px;">Datenschutz</a>
              <span style="opacity:0.4;">|</span>
              <a href="https://{site}/agb" style="color:#ffffff;text-decoration:none;margin:0 8px;">AGB</a>
              <span style="opacity:0.4;">|</span>
              <a href="{_esc(unsub_url)}" style="color:#ffffff;text-decoration:none;margin:0 8px;">Abmelden</a>
            </div>
            <div style="margin-top:22px;font-family:{FONT};font-size:11px;line-height:1.55;
                        color:rgba(148,163,171,0.7);">
              © {year} F2 Maler &amp; Gipser. Alle Rechte vorbehalten.
            </div>
            <div style="margin-top:8px;font-family:{FONT};font-size:11px;line-height:1.55;
                        color:rgba(148,163,171,0.55);max-width:480px;display:inline-block;">
              Sie erhalten diese Nachricht, weil F2 Maler &amp; Gipser glaubt,
              dass unsere Dienstleistung für Ihre Liegenschaft relevant sein könnte.
              Mit einem Klick abmelden.
            </div>
          </td></tr>
        </table>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
