"""Generate one HTML unsubscribe page per client, each in its own brand
language. Pages live at docs/unsubscribe/<slug>.html — served by GitHub
Pages at https://gentritluta.github.io/local-email-stack/unsubscribe/<slug>.html.

Each page is self-contained: brand-specific HTML structure, brand colors,
brand language (DE/EN), brand logo. The token from ?t= in the URL still
identifies the prospect; the unsubscribe POST hits the same Supabase
table. No backend code change required.

After running, each profile's brand.unsubscribe_url_template is updated
to point at its dedicated page.
"""
from __future__ import annotations
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS_UNSUB = REPO / "docs" / "unsubscribe"
DOCS_UNSUB.mkdir(parents=True, exist_ok=True)
PROFILES = REPO / "profiles"
PUBLIC = REPO / "desktop" / "frontend" / "public" / "profiles"

# Shared Supabase config (public read/update — token IS the auth)
SUPABASE_URL  = "https://ccmqkljsjiuavpydbkva.supabase.co"
SUPABASE_ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                  "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNjbXFrbGpzaml1YXZweWRia3ZhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzkwMTYzNjUsImV4cCI6MjA5NDU5MjM2NX0."
                  "cCUuVEYMlShJkM4FlaCwYYYEn_-pQeuZAZgCRob0ONc")

BASE_URL = "https://gentritluta.github.io/local-email-stack/unsubscribe"


# ─── Shared JS for the unsubscribe POST ──────────────────────────────────

def unsub_js(success_msg: str, already_msg: str, error_msg: str,
             missing_token_msg: str, lookup_fail_msg: str) -> str:
    """Inline JS — same logic for every client, just localized strings."""
    return f"""
<script>
const SUPABASE_URL  = "{SUPABASE_URL}";
const SUPABASE_ANON = "{SUPABASE_ANON}";

const params = new URLSearchParams(location.search);
const token  = params.get("t") || "";
const btn    = document.getElementById("btn");
const lead   = document.getElementById("lead");
const status = document.getElementById("status");
const successWrap = document.getElementById("success-state");
const errorWrap   = document.getElementById("error-state");
const emailEl     = document.getElementById("email");

function escapeHtml(s) {{
  return String(s).replace(/[&<>"']/g, c => ({{ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }}[c]));
}}

function showSuccess(email) {{
  if (emailEl) emailEl.textContent = email || "Ihre Adresse";
  if (successWrap) successWrap.style.display = "block";
  if (btn) btn.style.display = "none";
  if (lead) lead.style.display = "none";
}}

function showError(msg) {{
  if (errorWrap) {{
    errorWrap.textContent = msg;
    errorWrap.style.display = "block";
  }}
  if (btn) btn.disabled = false;
}}

async function loadProspect() {{
  if (!token) {{ showError("{missing_token_msg}"); if (btn) btn.disabled = true; return; }}
  try {{
    const r = await fetch(
      `${{SUPABASE_URL}}/rest/v1/prospects?unsubscribe_token=eq.${{encodeURIComponent(token)}}&select=email,unsubscribed`,
      {{ headers: {{ apikey: SUPABASE_ANON, Authorization: "Bearer " + SUPABASE_ANON }} }}
    );
    if (!r.ok) throw new Error("HTTP " + r.status);
    const rows = await r.json();
    if (!rows.length) {{ showError("{lookup_fail_msg}"); if (btn) btn.disabled = true; return; }}
    if (rows[0].unsubscribed) {{
      showSuccess(rows[0].email);
      if (status) status.textContent = "{already_msg}";
    }}
  }} catch (err) {{ showError("{error_msg}: " + err.message); }}
}}

async function doUnsubscribe() {{
  if (btn) btn.disabled = true;
  try {{
    const find = await fetch(
      `${{SUPABASE_URL}}/rest/v1/prospects?unsubscribe_token=eq.${{encodeURIComponent(token)}}&select=email`,
      {{ headers: {{ apikey: SUPABASE_ANON, Authorization: "Bearer " + SUPABASE_ANON }} }}
    );
    if (!find.ok) throw new Error("HTTP " + find.status);
    const rows = await find.json();
    if (!rows.length) {{ showError("{lookup_fail_msg}"); return; }}
    const email = rows[0].email;
    const patch = await fetch(
      `${{SUPABASE_URL}}/rest/v1/prospects?unsubscribe_token=eq.${{encodeURIComponent(token)}}`,
      {{
        method: "PATCH",
        headers: {{
          apikey: SUPABASE_ANON, Authorization: "Bearer " + SUPABASE_ANON,
          "Content-Type": "application/json", Prefer: "return=minimal"
        }},
        body: JSON.stringify({{ unsubscribed: true, unsubscribed_at: new Date().toISOString() }})
      }}
    );
    if (!patch.ok && patch.status !== 204) throw new Error("HTTP " + patch.status);
    showSuccess(email);
  }} catch (err) {{ showError("{error_msg}: " + err.message); }}
}}

if (btn) btn.addEventListener("click", doUnsubscribe);
loadProspect();
</script>
"""


# ─── F2 Maler & Gipser — German, dark teal hero matching email/site ──────

F2_LOGO = ("https://horizons-cdn.hostinger.com/2289cef3-cfe1-43c6-8890-321b9bb5fdc5/"
           "6dfa90e1c23f38fcb6efab9b0d2a107b.png")

AUREON_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Unsubscribe · Aureon Global</title>
<style>
  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: #050505; min-height: 100vh; }
  body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         color: #ffffff; padding: 32px 16px; display: grid; place-items: center; }
  .card { width: 100%; max-width: 560px; background: #0e0e0e; border: 1px solid #1a1a1a;
          border-radius: 8px; overflow: hidden; }
  .accent-rule { height: 3px; background: #d4af37; }
  .body { padding: 40px 36px 28px; }
  .wordmark { font-size: 20px; font-weight: 700; color: #d4af37; letter-spacing: .5px; }
  .tagline { font-size: 12px; color: #888888; margin-top: 6px;
             text-transform: uppercase; letter-spacing: 1.4px; }
  h1 { font-size: 24px; font-weight: 700; margin: 28px 0 12px; color: #ffffff; }
  p { font-size: 15px; line-height: 1.65; margin: 0 0 14px; color: #cbd5e1; }
  p .email { color: #d4af37; font-weight: 600; }
  .btn { display: inline-block; margin-top: 14px; padding: 13px 26px;
         background: #d4af37; color: #050505; font-size: 14px; font-weight: 700;
         border: none; border-radius: 4px; cursor: pointer; letter-spacing: .3px; }
  .btn:hover { background: #b8941f; }
  .btn:disabled { opacity: .5; cursor: not-allowed; }
  .success { display: none; margin-top: 16px; padding: 14px 16px;
             background: rgba(212,175,55,.08); border-left: 3px solid #d4af37;
             font-size: 14px; line-height: 1.5; color: #d4af37; border-radius: 4px; }
  .err { display: none; margin-top: 16px; padding: 14px 16px;
         background: rgba(220,38,38,.1); border-left: 3px solid #dc2626;
         font-size: 13.5px; line-height: 1.5; color: #fca5a5; border-radius: 4px; }
  .footer { padding: 22px 36px 28px; border-top: 1px solid #1a1a1a;
            font-size: 12px; color: #555555; }
  .footer a { color: #d4af37; text-decoration: none; }
</style>
</head>
<body>
  <div class="card">
    <div class="accent-rule"></div>
    <div class="body">
      <div class="wordmark">Aureon Global</div>
      <div class="tagline">Real Estate Growth Partner</div>

      <h1>Stop receiving Aureon emails</h1>
      <p id="lead">Click below and we will remove your address from every Aureon
        campaign. No follow-up, no second attempt. If you change your mind later,
        the door is always open at <a href="https://aureonglobal.de" style="color:#d4af37">aureonglobal.de</a>.</p>
      <button class="btn" id="btn" type="button">Confirm unsubscribe</button>

      <div class="success" id="success-state">
        <b><span id="email">Your address</span></b> has been unsubscribed.
        You will not hear from us again.
      </div>

      <div class="err" id="error-state"></div>
      <div id="status" style="display:none"></div>
    </div>

    <div class="footer">
      Aureon Global L.L.C. · Kacanik, Republic of Kosovo<br>
      <a href="mailto:info@aureonglobal.de">info@aureonglobal.de</a>
      &nbsp;·&nbsp;
      <a href="https://aureonglobal.de">aureonglobal.de</a><br>
      © 2026 Aureon Global L.L.C.
    </div>
  </div>
""" + unsub_js(
    success_msg="unsubscribed",
    already_msg="You are already unsubscribed.",
    error_msg="Something went wrong",
    missing_token_msg="This link is incomplete. Please use the link from the email.",
    lookup_fail_msg="We could not find this link. It may have already been used."
) + """
</body></html>"""


# ─── AlgoAlpha — English, dark with yellow + magenta accents ─────────────

ALGOALPHA_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Unsubscribe · AlgoAlpha</title>
<style>
  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: #08090d; min-height: 100vh; }
  body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         color: #f4f4f5; padding: 32px 16px; display: grid; place-items: center; }
  .card { width: 100%; max-width: 560px; background: #0f1117; border: 1px solid #1f2230;
          border-radius: 12px; overflow: hidden; }
  .accent-rule { height: 4px;
                  background: linear-gradient(90deg,#ffd400 0%,#c9165b 100%); }
  .body { padding: 38px 32px 28px; }
  .wordmark { font-size: 22px; font-weight: 800; color: #ffd400; letter-spacing: -.3px; }
  .tagline { font-size: 12.5px; color: #94a3b8; margin-top: 6px; }
  h1 { font-size: 23px; font-weight: 700; margin: 26px 0 12px; color: #ffffff; }
  p { font-size: 15px; line-height: 1.65; margin: 0 0 14px; color: #cbd5e1; }
  p .email { color: #ffd400; font-weight: 600; }
  .btn { display: inline-block; margin-top: 14px; padding: 13px 28px;
         background: #ffd400; color: #08090d; font-size: 14px; font-weight: 800;
         border: none; border-radius: 8px; cursor: pointer; letter-spacing: .3px; }
  .btn:hover { background: #e6c000; }
  .btn:disabled { opacity: .5; cursor: not-allowed; }
  .success { display: none; margin-top: 16px; padding: 14px 16px;
             background: rgba(255,212,0,.06); border-left: 3px solid #ffd400;
             font-size: 14px; line-height: 1.5; color: #ffd400; border-radius: 6px; }
  .err { display: none; margin-top: 16px; padding: 14px 16px;
         background: rgba(220,38,38,.1); border-left: 3px solid #dc2626;
         font-size: 13.5px; line-height: 1.5; color: #fca5a5; border-radius: 6px; }
  .footer { padding: 20px 32px 26px; border-top: 1px solid #1f2230;
            font-size: 12px; color: #64748b; }
  .footer a { color: #c9165b; text-decoration: none; font-weight: 600; }
</style>
</head>
<body>
  <div class="card">
    <div class="accent-rule"></div>
    <div class="body">
      <div style="display:flex;align-items:center;gap:14px;margin-bottom:4px;">
        <img src="https://algoalpha.io/file.svg" alt="AlgoAlpha" width="44" height="44"
             style="display:block;border:0;">
        <div>
          <div class="wordmark">AlgoAlpha</div>
          <div class="tagline">TradingView indicators &amp; live crypto signals · 75k+ traders</div>
        </div>
      </div>

      <h1>Unsubscribe from AlgoAlpha</h1>
      <p id="lead">One click and we are out of your inbox. Our creator partnership
        emails will stop coming. The free indicators on TradingView keep working
        either way at <a href="https://algoalpha.io" style="color:#ffd400">algoalpha.io</a>.</p>
      <button class="btn" id="btn" type="button">Confirm unsubscribe</button>

      <div class="success" id="success-state">
        <b><span id="email">Your address</span></b> has been unsubscribed.
        We will not contact you again.
      </div>

      <div class="err" id="error-state"></div>
      <div id="status" style="display:none"></div>
    </div>

    <div class="footer">
      AlgoAlpha · Lisbon, Portugal<br>
      <a href="mailto:support@algoalpha.io">support@algoalpha.io</a>
      &nbsp;·&nbsp;
      <a href="https://algoalpha.io">algoalpha.io</a><br>
      © 2026 AlgoAlpha
    </div>
  </div>
""" + unsub_js(
    success_msg="unsubscribed",
    already_msg="You are already unsubscribed.",
    error_msg="Something went wrong",
    missing_token_msg="This link is incomplete. Please use the link from the email.",
    lookup_fail_msg="We could not find this link. It may have already been used."
) + """
</body></html>"""


# ─── LK Advertising — German, electric blue, performance-agency feel ─────

LK_HTML = """<!doctype html>
<html lang="de-DE">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Abmelden · LK Advertising</title>
<style>
  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: #f8fafc; min-height: 100vh; }
  body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         color: #0a0a0a; padding: 32px 16px; display: grid; place-items: center; }
  .card { width: 100%; max-width: 560px; background: #ffffff;
          border-radius: 12px; overflow: hidden;
          box-shadow: 0 1px 3px rgba(0,82,255,.08), 0 4px 16px rgba(0,82,255,.04); }
  .top-bar { height: 5px; background: linear-gradient(90deg,#0052ff 0%,#001b73 100%); }
  .body { padding: 38px 32px 28px; }
  .wordmark { font-size: 22px; font-weight: 800; color: #0052ff;
              letter-spacing: -.4px; }
  .tagline { font-size: 12.5px; color: #64748b; margin-top: 6px; font-weight: 500; }
  h1 { font-size: 22px; font-weight: 700; margin: 26px 0 12px; color: #0f172a; }
  p { font-size: 15px; line-height: 1.65; margin: 0 0 14px; color: #475569; }
  p .email { color: #0052ff; font-weight: 700; }
  .btn { display: inline-block; margin-top: 14px; padding: 13px 28px;
         background: #0052ff; color: #ffffff; font-size: 14px; font-weight: 700;
         border: none; border-radius: 8px; cursor: pointer; letter-spacing: .2px; }
  .btn:hover { background: #001b73; }
  .btn:disabled { opacity: .5; cursor: not-allowed; }
  .success { display: none; margin-top: 16px; padding: 14px 16px;
             background: #eff6ff; border-left: 3px solid #0052ff;
             font-size: 14px; line-height: 1.5; color: #0052ff; border-radius: 6px; }
  .err { display: none; margin-top: 16px; padding: 14px 16px;
         background: #fef2f2; border-left: 3px solid #dc2626;
         font-size: 13.5px; line-height: 1.5; color: #991b1b; border-radius: 6px; }
  .footer { padding: 20px 32px 26px; border-top: 1px solid #e2e8f0;
            font-size: 12px; color: #94a3b8; }
  .footer a { color: #0052ff; text-decoration: none; font-weight: 600; }
</style>
</head>
<body>
  <div class="card">
    <div class="top-bar"></div>
    <div class="body">
      <div class="wordmark">LK Advertising</div>
      <div class="tagline">Performance-Media für Maklerbüros in Deutschland</div>

      <h1>Vom LK-Verteiler abmelden</h1>
      <p id="lead">Ein Klick und wir sind aus Ihrem Postfach raus. Wir nehmen
        Ihre Adresse aus jedem Verteiler. Wenn Sie später doch noch über
        Performance-Werbung sprechen wollen, schreiben Sie einfach an
        <a href="mailto:hello@lk-advertising.com" style="color:#0052ff">hello@lk-advertising.com</a>.</p>
      <button class="btn" id="btn" type="button">Jetzt abmelden</button>

      <div class="success" id="success-state">
        <b><span id="email">Ihre Adresse</span></b> ist abgemeldet. Sie hören
        nichts mehr von uns.
      </div>

      <div class="err" id="error-state"></div>
      <div id="status" style="display:none"></div>
    </div>

    <div class="footer">
      LK Advertising · c/o LK Advertising<br>
      <a href="mailto:hello@lk-advertising.com">hello@lk-advertising.com</a><br>
      © 2026 LK Advertising
    </div>
  </div>
""" + unsub_js(
    success_msg="abgemeldet",
    already_msg="Sie sind bereits abgemeldet.",
    error_msg="Etwas ist schiefgelaufen",
    missing_token_msg="Der Link ist unvollständig. Bitte verwenden Sie den Link aus der E-Mail.",
    lookup_fail_msg="Wir konnten diesen Link nicht finden. Möglicherweise wurde er bereits verwendet."
) + """
</body></html>"""


# ─── Write files + update profile URL templates ─────────────────────────

PAGES = {
    "aureon":         AUREON_HTML,
    "algoalpha":      ALGOALPHA_HTML,
    "lk-advertising": LK_HTML,
}

for slug, html in PAGES.items():
    path = DOCS_UNSUB / f"{slug}.html"
    path.write_text(html, encoding="utf-8")
    print(f"wrote {path}  ({len(html)} bytes)")

    # Update the profile's unsubscribe URL template to point to its dedicated page
    pf = PROFILES / f"{slug}.json"
    if pf.exists():
        data = json.loads(pf.read_text(encoding="utf-8"))
        new_url = f"{BASE_URL}/{slug}.html?t={{token}}"
        data["brand"]["unsubscribe_url_template"] = new_url
        pf.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
        pub = PUBLIC / f"{slug}.json"
        if pub.exists():
            pub.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
        print(f"  + {slug}: unsubscribe_url_template = {new_url}")
