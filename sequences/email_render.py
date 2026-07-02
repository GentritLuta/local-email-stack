"""email_render.py — shared HTML/text renderer for all outbound mail.

Single source of truth for the wire format. Both `resend-pool-send.py` and
`sequence-runner.py` call into this module so a body always renders the same
way regardless of code path.

Brand-driven. Each profile owns a `brand` block (fonts, colors, wordmark,
unsubscribe URL template). The renderer applies that brand per-send, so a
new client with a different palette gets emails that look like THEIR site,
not Aureon's.

Falls back to a neutral default brand when no brand block is provided
(e.g. ad-hoc test sends without a profile context).
"""
from __future__ import annotations

import re
import uuid
import time
from email.utils import formataddr
from typing import Optional

DEFAULT_BRAND = {
    "wordmark":  "",
    "site":      "",
    "tagline":   "",
    "font_stack": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    "font_url":   "",
    "colors": {
        "accent":   "#1f2937",
        "accent_2": "#374151",
        "text":     "#111827",
        "text_2":   "#4b5563",
        "muted":    "#9ca3af",
        "bg_page":  "#f5f5f5",
        "bg_card":  "#ffffff",
        "rule":     "#e5e7eb",
    },
    "unsubscribe_url_template": "https://gentritluta.github.io/local-email-stack/unsubscribe.html?t={token}",
}

FALLBACK_UNSUB_MAILTO = "info@aureonglobal.de?subject=unsubscribe"

# STANDARD (all clients): the agency inbox is always a Reply-To so replies reach
# Aureon AND the client. Prospect replies go to BOTH the client's mailbox and here.
AGENCY_INBOX = "info@aureonglobal.de"


def _reply_to_list(persona: dict) -> list[str]:
    """Reply-To = [client's reply mailbox, agency inbox], deduped, order-preserved.
    Every cold send routes replies to both the client and Aureon.

    Exception: when a persona sets reply_to_exclusive, Reply-To is just its own
    reply_to and the agency inbox is NOT appended. Used when reply_to is a
    same-domain forwarder that already relays to the agency inbox (e.g. AlgoAlpha
    sends from *.tryalgoalpha.com and replies to reply@tryalgoalpha.com, which
    Cloudflare forwards to info@aureonglobal.de). Keeping From and Reply-To on the
    same registrable domain stops corporate spam filters flagging the mismatch."""
    client = (persona.get("reply_to") or persona.get("from_addr") or "").strip()
    if persona.get("reply_to_exclusive") and client:
        return [client]
    out = []
    for addr in (client, AGENCY_INBOX):
        a = (addr or "").strip()
        if a and a.lower() not in [x.lower() for x in out]:
            out.append(a)
    return out


def unsubscribe_url(token: Optional[str], brand: dict | None = None) -> str:
    """Build the per-prospect unsubscribe URL. Always returns a URL (not a
    mailto:) so the recipient gets a real button. When the token is missing
    we strip it from the template — the static page handles the no-token
    case with a clean error + a fallback contact line."""
    b = brand or DEFAULT_BRAND
    template = b.get("unsubscribe_url_template") or DEFAULT_BRAND["unsubscribe_url_template"]
    if token:
        return template.format(token=token)
    # No token: strip ?t={token} (or &t={token}) from template, keep base URL.
    base = template.split("?")[0]
    return base


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _body_paragraphs_html(body: str, font_stack: str, text_color: str) -> str:
    """`\\n\\n`-separated text paragraphs → <p> blocks with email-safe inline
    styling. Single newlines inside a paragraph become <br>."""
    parts = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
    out = []
    for p in parts:
        escaped = _esc(p).replace("\n", "<br>")
        out.append(
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.65;'
            f'color:{text_color};font-family:{font_stack};">{escaped}</p>'
        )
    return "".join(out)


def render_html(*, body: str, persona: dict, unsubscribe_token: Optional[str] = None,
                brand: dict | None = None, step_n: int = 1) -> str:
    """Render the email HTML.

    `step_n` is the sequence step number. Step 1 (the initial cold email)
    omits the CTA button across every per-client template — best-practice
    cold-email hygiene says the first touch should look like a plain
    personal email, with a "just reply" ask in the body. From step 2
    onwards the branded CTA button reappears.
    """
    # Per-client custom templates — dispatch by brand.template. Each brand
    # with a non-"default" template gets its own HTML structure entirely;
    # the generic template below only runs when no custom is declared.
    template = (brand or {}).get("template", "default")
    if template == "aureon-custom":
        from email_template_aureon import render_html_aureon
        return render_html_aureon(body=body, persona=persona,
                                   unsubscribe_token=unsubscribe_token, brand=brand,
                                   step_n=step_n)
    if template == "algoalpha-custom":
        from email_template_algoalpha import render_html_algoalpha
        return render_html_algoalpha(body=body, persona=persona,
                                      unsubscribe_token=unsubscribe_token, brand=brand,
                                      step_n=step_n)
    if template == "lk-custom":
        from email_template_lk import render_html_lk
        return render_html_lk(body=body, persona=persona,
                               unsubscribe_token=unsubscribe_token, brand=brand,
                               step_n=step_n)
    if template == "atalsolidrocks-custom":
        from email_template_atalsolidrocks import render_html_atalsolidrocks
        return render_html_atalsolidrocks(body=body, persona=persona,
                                          unsubscribe_token=unsubscribe_token, brand=brand,
                                          step_n=step_n)
    if template == "diraya-custom":
        from email_template_diraya import render_html_diraya
        return render_html_diraya(body=body, persona=persona,
                                  unsubscribe_token=unsubscribe_token, brand=brand,
                                  step_n=step_n)
    if template == "energ-custom":
        from email_template_energ import render_html_energ
        return render_html_energ(body=body, persona=persona,
                                 unsubscribe_token=unsubscribe_token, brand=brand,
                                 step_n=step_n)
    if template == "mark-eting-custom":
        from email_template_mark_eting import render_html_mark_eting
        return render_html_mark_eting(body=body, persona=persona,
                                      unsubscribe_token=unsubscribe_token, brand=brand,
                                      step_n=step_n)

    b = {**DEFAULT_BRAND, **(brand or {})}
    # Deep-merge colors so a profile can override one color without losing the rest.
    b["colors"] = {**DEFAULT_BRAND["colors"], **((brand or {}).get("colors") or {})}
    c = b["colors"]
    font = b["font_stack"]
    wordmark = b.get("wordmark") or ""
    tagline = b.get("tagline") or ""
    site = b.get("site") or ""
    unsub = unsubscribe_url(unsubscribe_token, b)

    # Professional signature block:
    #   • Full name (bold, body text size)
    #   • Title (or any subsequent lines from persona.signature) in slightly
    #     smaller, muted secondary color
    # The company line below this is the site only — the wordmark already
    # sits in the top header and the bottom logo block, no need to repeat it.
    sig_lines = [line.strip() for line in (persona.get("signature") or "").split("\n") if line.strip()]
    if not sig_lines:
        sig_lines = [persona.get("from_name", "")]
    name_line = _esc(sig_lines[0])
    title_lines = [_esc(l) for l in sig_lines[1:]]
    sig_html = (
        f'<div style="font-family:{font};font-size:14px;font-weight:600;color:{c["text"]};">{name_line}</div>'
        + "".join(
            f'<div style="font-family:{font};font-size:13px;color:{c["text_2"]};margin-top:1px;">{l}</div>'
            for l in title_lines
        )
    )

    header_html = ""
    if wordmark:
        header_html = f'''
        <tr><td style="padding:32px 36px 0;">
          <div style="font-family:{font};font-size:18px;font-weight:600;letter-spacing:.01em;color:{c['text']};">
            <span style="color:{c['accent']};">{_esc(wordmark)}</span>
          </div>
          {f'<div style="font-family:{font};font-size:12px;color:{c["muted"]};margin-top:2px;">{_esc(tagline)}</div>' if tagline else ''}
          <div style="height:1px;background:{c['accent']};opacity:.35;margin-top:18px;"></div>
        </td></tr>'''

    body_html = _body_paragraphs_html(body, font, c['text'])

    # Quiet website link directly under the signature. No wordmark here — it's
    # already in the top header + bottom logo block. Triple-stating it reads
    # marketing-y, not professional.
    company_line = (f'<a href="https://{_esc(site)}" style="color:{c["text_2"]};text-decoration:none;">{_esc(site)}</a>'
                    if site else "")

    # Corporate footer (the user's preferred style) — only renders when the
    # profile has a brand.legal block. Otherwise we fall back to the simpler
    # accent-rule + unsubscribe footer below.
    # footer_style: "dark" (default — premium black block with white wordmark)
    # or "light" (white block with brand-accent wordmark — fits brands whose
    # actual website is light-themed, e.g. F2's white-with-green palette).
    legal = (brand or {}).get("legal") or {}
    footer_style = (brand or {}).get("footer_style") or "dark"
    if legal.get("company_name"):
        footer_html = _corporate_footer_html(legal, unsub, accent=c["accent"],
                                             style=footer_style, font=font)
    else:
        footer_html = _simple_footer_html(c, font, wordmark, tagline, unsub)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <title>{_esc(wordmark or 'Email')}</title>
</head>
<body style="margin:0;padding:0;background:{c['bg_page']};font-family:{font};">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:{c['bg_page']};">
    <tr><td align="center" style="padding:32px 12px;">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;width:100%;background:{c['bg_card']};border-radius:6px;">
        {header_html}
        <tr><td style="padding:28px 36px 8px;">
          {body_html}
        </td></tr>
        <tr><td style="padding:0 36px 24px;">
          <div style="font-family:{font};font-size:14px;line-height:1.5;color:{c['text']};">
            {sig_html}
          </div>
          <div style="font-family:{font};font-size:13px;line-height:1.5;color:{c['text_2']};margin-top:4px;">
            {company_line}
          </div>
        </td></tr>
        {footer_html}
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _simple_footer_html(c: dict, font: str, wordmark: str, tagline: str, unsub: str) -> str:
    """The old minimal footer — wordmark + accent rule + small unsubscribe.
    Used when a profile hasn't filled in its brand.legal block yet."""
    bottom = ""
    if wordmark:
        bottom = f'''
        <tr><td style="padding:32px 36px 8px;border-top:1px solid {c['rule']};text-align:center;">
          <div style="font-family:{font};font-size:20px;font-weight:700;letter-spacing:.04em;color:{c['accent']};">
            {_esc(wordmark).upper()}
          </div>
          {f'<div style="font-family:{font};font-size:11px;color:{c["muted"]};margin-top:4px;letter-spacing:.02em;">{_esc(tagline)}</div>' if tagline else ''}
          <div style="height:2px;width:40px;background:{c['accent']};margin:14px auto 0;opacity:.7;"></div>
        </td></tr>'''
    return bottom + f'''
        <tr><td style="padding:16px 36px 28px;text-align:center;font-family:{font};font-size:12px;line-height:1.5;color:{c['muted']};">
          You're receiving this because we believe it's relevant to your business.<br>
          <a href="{_esc(unsub)}" style="color:{c['accent_2']};text-decoration:underline;">Unsubscribe with one click</a>
          and we won't contact you again.
        </td></tr>'''


def _corporate_footer_html(legal: dict, unsub: str, accent: str = "#d4af37",
                            style: str = "dark", font: str | None = None) -> str:
    """Two-tier corporate email footer matching the user's spec.

    style="dark"  — premium black wordmark block with white wordmark + accent
                    links. Default. Fits dark-themed brand sites (Aureon, AlgoAlpha).
    style="light" — clean white wordmark block with brand-accent wordmark +
                    accent links + dark text. Fits brands whose website is
                    light-themed (F2 — green-on-white).

    The per-prospect unsubscribe URL is slotted into the link row so legal
    compliance + the existing one-click unsubscribe flow both apply.
    """
    name      = _esc(legal.get("company_name", ""))
    addr_lines = legal.get("address_lines") or []
    email     = _esc(legal.get("contact_email", ""))
    ceo       = _esc(legal.get("ceo", ""))
    vat       = _esc(legal.get("vat_number", ""))
    reg       = _esc(legal.get("registration_number", ""))
    year      = str(legal.get("copyright_year") or 2026)
    logo_url  = _esc(legal.get("logo_url", ""))
    logo_w    = int(legal.get("logo_width") or 50)
    privacy   = _esc(legal.get("privacy_policy_url", ""))
    terms     = _esc(legal.get("terms_of_service_url", ""))
    website   = "https://" + _esc(legal.get("contact_email", "").split("@")[-1]) if email else ""
    disclaim  = _esc(legal.get("legal_disclaimer", ""))
    partner   = _esc(legal.get("partner_notice", ""))

    # Wordmark text in the dark block — uppercase, strip the legal-form dots
    # so "Aureon Global L.L.C." reads as "AUREON GLOBAL LLC".
    wordmark_dark = name.replace(".", "").upper().strip()

    # Light block: street, city, country on one inline line.
    addr_inline = ", ".join(_esc(l) for l in addr_lines)
    # Dark block: collapse all but the last line (country) into one row with a
    # trailing comma, then country on its own line. Mirrors the user's spec.
    if len(addr_lines) >= 2:
        addr_block = ", ".join(_esc(l) for l in addr_lines[:-1]) + f",<br>{_esc(addr_lines[-1])}"
    elif addr_lines:
        addr_block = _esc(addr_lines[0])
    else:
        addr_block = ""

    # ── LIGHT confidentiality block ────────────────────────────────────────
    light = f'''
        <tr><td style="padding:0 36px 16px;">
          <div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.45;color:#333333;border-top:1px solid #ececec;padding-top:18px;">
            <div style="font-weight:700;color:#111111;margin:0 0 2px;">{name}</div>
            {f'<div>Address: {addr_inline}</div>' if addr_inline else ''}
            {f'<div>Email: <a href="mailto:{email}" style="color:#333333;text-decoration:none;">{email}</a></div>' if email else ''}
            {f'<div style="margin-top:8px;">CEO: {ceo}</div>' if ceo else ''}
            {f'<div>VAT Number: {vat}</div>' if vat else ''}
            {f'<div style="margin-bottom:8px;">Registration Number: {reg}</div>' if reg else ''}
            <div>© {year} {name} {disclaim}</div>
          </div>
        </td></tr>'''

    # Color palette depends on `style`. The DARK palette is the original
    # premium-feel black block with white wordmark + muted gray text.
    # The LIGHT palette inverts to white-on-white with the brand accent
    # carrying the wordmark — fits brands whose own websites are light.
    if style == "light":
        # Light footer — white card with brand-accent wordmark
        pal = {
            "bg":           "#ffffff",
            "wordmark":     accent,        # brand color carries the wordmark
            "body_text":    "#475569",     # slate-600
            "strong_text":  "#0f172a",     # slate-900
            "muted_text":   "#94a3b8",     # slate-400
            "divider":      "#e2e8f0",     # slate-200
            "sep_pipe":     "#cbd5e1",     # slate-300
        }
        wordmark_font = (font or "'Inter', system-ui, sans-serif")
        wordmark_display = name  # keep title-cased; light brands rarely want SHOUTING
    else:
        # Dark footer (default)
        pal = {
            "bg":           "#050505",
            "wordmark":     "#ffffff",
            "body_text":    "#888888",
            "strong_text":  "#ffffff",
            "muted_text":   "#555555",
            "divider":      "#1a1a1a",
            "sep_pipe":     "#333333",
        }
        wordmark_font = "Verdana, sans-serif"
        wordmark_display = wordmark_dark

    logo_img = (
        f'<img src="{logo_url}" alt="{name} Logo" width="{logo_w}" '
        f'style="display:block;margin:0 auto 10px auto;border:0;">'
        if logo_url else ""
    )
    # Links row: Website | Privacy | Terms | Unsubscribe — only show what we have.
    parts = []
    if website:  parts.append(f'<a href="{website}" style="color:{accent};text-decoration:none;margin:0 8px;font-weight:500;">Website</a>')
    if privacy:  parts.append(f'<a href="{privacy}" style="color:{accent};text-decoration:none;margin:0 8px;font-weight:500;">Privacy Policy</a>')
    if terms:    parts.append(f'<a href="{terms}" style="color:{accent};text-decoration:none;margin:0 8px;font-weight:500;">Terms of Service</a>')
    if unsub:    parts.append(f'<a href="{_esc(unsub)}" style="color:{accent};text-decoration:none;margin:0 8px;font-weight:500;">Unsubscribe</a>')
    sep = f'<span style="color:{pal["sep_pipe"]};margin:0 4px;">|</span>'
    links_row = sep.join(parts)

    block_font = wordmark_font

    dark = f'''
        <tr><td style="padding:0;">
          <div style="background-color:{pal['bg']};padding:40px 30px;text-align:center;color:{pal['body_text']};border-top:4px solid {accent};font-family:{block_font};">
            <table width="100%" border="0" cellspacing="0" cellpadding="0">
              <tr>
                <td align="center">
                  <div style="margin-bottom:20px;padding-top:20px;border-top:1px solid {pal['divider']};">
                    <a href="{website or '#'}" style="text-decoration:none;">
                      {logo_img}
                      <span style="color:{pal['wordmark']};font-weight:800;letter-spacing:{'0.5px' if style == 'light' else '1px'};{'text-transform:uppercase;' if style == 'dark' else ''}display:block;margin-bottom:5px;font-family:{block_font};font-size:{'18px' if style == 'light' else '16px'};">{wordmark_display}</span>
                    </a>
                  </div>
                  <p style="font-size:12px;line-height:1.6;margin:5px 0;color:{pal['body_text']};font-family:{block_font};">
                    <b style="color:{pal['strong_text']};">{name}</b><br>
                    {addr_block}
                  </p>
                  {f'<p style="font-size:12px;line-height:1.6;margin:5px 0;font-family:{block_font};"><a href="mailto:{email}" style="color:{accent};text-decoration:none;font-weight:500;">{email}</a></p>' if email else ''}
                  <p style="font-size:12px;line-height:1.6;margin:10px 0;font-family:{block_font};">
                    {links_row}
                  </p>
                  <div style="margin-top:25px;padding-top:25px;border-top:1px solid {pal['divider']};">
                    <p style="font-size:10px;color:{pal['muted_text']};margin:0;font-family:{block_font};">
                      © {year} {wordmark_display}. All rights reserved.<br>
                      {f'VAT ID: {vat} | Reg. No: {reg}' if vat or reg else ''}
                    </p>
                    {f'<p style="font-size:10px;color:{pal["muted_text"]};margin-top:10px;line-height:1.4;font-family:{block_font};">{partner}</p>' if partner else ''}
                  </div>
                </td>
              </tr>
            </table>
          </div>
        </td></tr>'''

    return light + dark


def render_text(*, body: str, persona: dict, unsubscribe_token: Optional[str] = None,
                brand: dict | None = None) -> str:
    b = {**DEFAULT_BRAND, **(brand or {})}
    sig = (persona.get("signature") or persona.get("from_name", "")).strip()
    site_line = f"\n{b.get('wordmark','')} · {b.get('site','')}" if b.get("site") else ""
    unsub = unsubscribe_url(unsubscribe_token, b)
    return (
        body.strip()
        + "\n\n" + sig
        + site_line
        + "\n\n---"
        + f"\nDon't want these emails? Unsubscribe: {unsub}"
    )


def _inject_tracking(html: str, track_token: str, tracker_base: str) -> str:
    """Inject a self-hosted open-tracking pixel + rewrite click links to go
    through our tracker. Resend's domain-level open_tracking flag is set true
    on all subdomains but their pipeline does not actually inject the pixel
    or rewrite links into outbound HTML (verified empirically). So we do it
    ourselves and own the data.

    track_token: a URL-safe unique id for this send (we use the hex part of
    Message-ID, which we already generate). The Cloudflare Worker at
    `tracker_base` resolves it back to a send_log row via LIKE-match on
    message_id, then sets opened_at / clicked_at.
    """
    if not tracker_base or not track_token:
        return html

    pixel = (
        f'<img src="{tracker_base}/open/{track_token}.gif" '
        f'width="1" height="1" alt="" '
        f'style="display:block;border:0;width:1px;height:1px;">'
    )

    # Inject pixel just before </body> (or append if no body close)
    lower = html.lower()
    body_close = lower.rfind("</body>")
    if body_close >= 0:
        html = html[:body_close] + pixel + html[body_close:]
    else:
        html = html + pixel

    # Click-tracking: rewrite outbound <a href="..."> to go through the
    # tracker. Skip anchors and unsubscribe links (those have their own
    # one-click pathway and we don't want to break compliance).
    def _rewrite(match: re.Match) -> str:
        url = match.group(1)
        if url.startswith("#") or url.startswith("mailto:"):
            return match.group(0)
        if "/unsubscribe/" in url or "unsubscribe" in url.lower():
            return match.group(0)
        import urllib.parse as _up
        wrapped = f"{tracker_base}/click/{track_token}?u={_up.quote(url, safe='')}"
        return match.group(0).replace(url, wrapped)

    html = re.sub(r'<a[^>]+href="([^"]+)"', _rewrite, html)
    return html


def build_payload(*, persona: dict, to_addr: str, subject: str, body: str,
                  unsubscribe_token: Optional[str] = None,
                  brand: dict | None = None,
                  tags: list[dict] | None = None,
                  step_n: int = 1,
                  tracker_base: Optional[str] = None) -> tuple[dict, str]:
    """Build the Resend API JSON payload + the Message-ID we generated.

    step_n=1 (the cold-outreach initial touch) is rendered without a CTA
    button so it reads as a plain personal email; step_n>=2 (follow-ups)
    show the branded button.

    tracker_base (optional): self-hosted tracker URL like
    "https://track.aureonglobal.de". When provided, an open-pixel and
    click-link rewrites are injected so we capture opens/clicks even though
    Resend's domain-level tracking flag isn't actually applied on outbound.
    """
    domain = persona["from_addr"].split("@", 1)[1]
    track_token = uuid.uuid4().hex
    msg_id = f"<{track_token}.{int(time.time())}@{domain}>"
    unsub = unsubscribe_url(unsubscribe_token, brand)
    html = render_html(body=body, persona=persona, unsubscribe_token=unsubscribe_token,
                       brand=brand, step_n=step_n)
    text = render_text(body=body, persona=persona, unsubscribe_token=unsubscribe_token, brand=brand)
    if tracker_base:
        html = _inject_tracking(html, track_token, tracker_base)
    headers = {
        "Message-ID":            msg_id,
        # Gmail prefers URL form (RFC 8058 one-click); mailto fallback for older clients.
        "List-Unsubscribe":      f"<{unsub}>, <mailto:{FALLBACK_UNSUB_MAILTO}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    # Use formataddr so non-ASCII display names (e.g. "Tomás Silva") get
    # encoded per RFC 5322 as =?UTF-8?B?...?= instead of being sent raw.
    # Raw UTF-8 in From headers gets reinterpreted as Latin-1 by some MTAs
    # / receiver display layers, producing mojibake like "TomÃ¡s".
    payload = {
        "from":     formataddr((persona["from_name"], persona["from_addr"])),
        "to":       [to_addr],
        "reply_to": _reply_to_list(persona),
        "subject":  subject,
        "text":     text,
        "html":     html,
        "headers":  headers,
        "tags":     tags or [],
    }
    return payload, msg_id
