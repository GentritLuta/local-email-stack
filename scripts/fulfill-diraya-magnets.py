"""fulfill-diraya-magnets.py - auto-fulfil Diraya's give-first lead magnets when a
prospect replies GHOSTS or REVIEW by email.

  GHOSTS -> instant: email the Agent Ghost-Cases List PDF (attached) from a verified
            Diraya persona, signed, with the Calendly + REVIEW soft CTA. Hands-off.
  REVIEW -> instant ack to the prospect (the personalised architecture review needs
            Mohammed, so we acknowledge + ask the one scoping question) AND alert
            info@diraya.ca (bcc the operator) so the one-pager goes out inside 48h.

Mirrors scripts/fulfill-referral-requests.py:
  - reads only the TOP of the reply (before quoted history) so our own copy never
    self-triggers;
  - ignores replies from our own Diraya / Aureon addresses;
  - requires a real, non-unsubscribed DIRAYA prospect (profile_slug=diraya);
  - idempotent: tracks fulfilled reply ids in referral-lists/.diraya_fulfilled.json.

Sending uses the NEW Resend account (RESEND_NEW_ACCOUNT_API_KEY in hostinger.env)
where the 10 Diraya domains live, and a persona whose domain is currently VERIFIED
in Resend - so this is safe to schedule now and simply no-ops (per intent) until the
senders verify.

Optional: set DIRAYA_GHOSTS_URL in hostinger.env to ALSO include a hosted link to the
PDF in the email body (e.g. once you upload it to diraya.biz). Attachment is sent
either way.

Usage:
  py scripts/fulfill-diraya-magnets.py          # fulfil all pending
  py scripts/fulfill-diraya-magnets.py --dry    # show what it would do
"""
from __future__ import annotations
import argparse
import base64
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PDF = REPO / "lead-magnets" / "Diraya-Agent-Ghost-Cases-List.pdf"
REVIEW_PDF = REPO / "lead-magnets" / "Diraya-Architecture-Review.pdf"
STATE = REPO / "referral-lists" / ".diraya_fulfilled.json"
ALERT_TO = "info@diraya.ca"                 # Mohammed fulfils the REVIEW one-pager
ALERT_BCC = "info@aureonglobal.de"          # operator visibility
CALENDLY = "https://calendly.com/amoura-ma-diraya/30min"
UA = "local-email-stack diraya-fulfil/1.0"
# persona preference order: verified roots first get used
ROOT_PREF = ["diraya.biz", "diraya-agency.shop", "diraya-marketing.shop",
             "cleardiraya.com", "dirayaget.com"]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ----- env / data -----
def load_env() -> dict:
    env = {}
    for fn in ("hostinger.env", "supabase.env"):
        p = REPO / "sequences" / fn
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def supa_get(env: dict, path: str) -> list:
    URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
    KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
    req = urllib.request.Request(URL + path, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def personas() -> list[dict]:
    prof = json.loads((REPO / "profiles" / "diraya.json").read_text(encoding="utf-8"))
    return prof.get("personas", [])


def verified_roots(resend_key: str) -> set[str]:
    """Diraya root domains whose sender subdomains are VERIFIED in Resend."""
    H = {"Authorization": "Bearer " + resend_key, "User-Agent": UA}
    try:
        data = json.loads(urllib.request.urlopen(
            urllib.request.Request("https://api.resend.com/domains", headers=H), timeout=20).read())
    except Exception as e:
        print(f"  ! could not list Resend domains: {e}")
        return set()
    out = set()
    for d in data.get("data", []):
        if "diraya" in d["name"] and d.get("status") == "verified":
            out.add(d["name"])          # e.g. hello.diraya.biz
    return out


def pick_persona(verified_subdomains: set[str]) -> dict | None:
    """First persona (by ROOT_PREF) whose from_addr domain is verified."""
    ps = personas()
    def root_rank(p):
        dom = p["from_addr"].split("@")[-1]
        for i, r in enumerate(ROOT_PREF):
            if dom.endswith(r):
                return i
        return 99
    for p in sorted(ps, key=root_rank):
        if p["from_addr"].split("@")[-1] in verified_subdomains:
            return p
    return None


# ----- reply parsing -----
_QUOTE_RE = re.compile(
    r"^(_{5,}|-{5,}|from:|sent:|to:|subject:|on .+wrote:|>.*|le .+a écrit\s*:)",
    re.IGNORECASE)


def top_reply(body: str) -> str:
    out = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if _QUOTE_RE.match(s) or "________" in s:
            break
        out.append(ln)
    return "\n".join(out).strip()


def intent_of(body: str) -> str | None:
    top = top_reply(body)
    if not top or len(top) > 400:
        return None
    low = top.lower()
    if re.search(r"\breview\b", low):
        return "review"
    if re.search(r"\bghosts?\b", low):
        return "ghosts"
    return None


def is_ours(addr: str) -> bool:
    dom = addr.split("@")[-1].lower()
    return (dom.endswith("diraya.ca") or "diraya" in dom and dom.endswith((".com", ".biz", ".shop"))
            or dom == "aureonglobal.de" or dom.endswith(".aureonglobal.de"))


# ----- send -----
def _post_email(resend_key: str, payload: dict) -> bool:
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception as e:
        body = getattr(e, "read", lambda: b"")()
        print(f"     ! send failed: {e} {body[:160]}")
        return False


def _wrap_html(paras: list[str], sig: str) -> str:
    import html as _h
    body = "".join(f'<p>{_h.escape(p)}</p>' for p in paras)
    sig_html = sig.replace("\n", "<br>")
    return ('<div style="font-family:-apple-system,Segoe UI,sans-serif;color:#1a1a1a;'
            'max-width:560px;line-height:1.55;font-size:15px">' + body
            + f'<p style="margin-top:18px;color:#454545">{sig_html}</p></div>')


def send_ghosts(env, to_addr, first_name, persona, link, dry) -> bool:
    name = persona["from_name"].split(" from ")[0]
    greet = f"Hi {first_name}," if first_name else "Hi,"
    link_line = (f"If you would rather have it as a link, here it is: {link}"
                 if link else None)
    paras = [
        greet,
        "As promised, the Agent Ghost-Cases List is attached. It is the 40 "
        "production-killers we check every build against before it reaches a customer.",
        "The short version of all 40: write the eval first, then the agent, then "
        "harden the agent against the evals. That one inversion is what separates a "
        "demo from a product.",
    ]
    if link_line:
        paras.append(link_line)
    paras.append(
        "No call attached. If you ever want a second set of eyes on what you are "
        f"building, reply REVIEW and I send a free architecture review for your stack, "
        f"or grab 30 minutes here: {CALENDLY}")
    sig = persona.get("signature", f"{name}\nDiraya Inc")
    text = "\n\n".join(paras) + "\n\n" + sig
    if dry:
        print(f"     [dry] would GHOSTS->{to_addr} from {persona['from_addr']} "
              f"(attach {PDF.name}, link={'yes' if link else 'no'})")
        return True
    if not PDF.exists():
        print(f"     ! missing PDF at {PDF}")
        return False
    payload = {
        "from": f"{persona['from_name']} <{persona['from_addr']}>",
        "to": [to_addr], "reply_to": persona.get("reply_to", ALERT_TO),
        "subject": "The Agent Ghost-Cases List",
        "html": _wrap_html(paras, sig), "text": text,
        "attachments": [{"filename": PDF.name,
                         "content": base64.b64encode(PDF.read_bytes()).decode()}],
        "tags": [{"name": "kind", "value": "diraya_ghosts_fulfil"}],
    }
    return _post_email(env["RESEND_NEW_ACCOUNT_API_KEY"], payload)


def send_review(env, to_addr, first_name, company, persona, link, dry) -> bool:
    name = persona["from_name"].split(" from ")[0]
    greet = f"Hi {first_name}," if first_name else "Hi,"
    link_line = (f"Prefer a link: {link}" if link else None)
    paras = [
        greet,
        "As promised, your architecture review is attached. It is the reference build we "
        "start from, the three risks that kill most AI features before they ship, and a "
        "realistic 8-week timeline to production.",
    ]
    if link_line:
        paras.append(link_line)
    paras.append(
        "This is the general version. For the review tailored to your exact stack and data, "
        "reply with two lines on what you are building and I send it back inside 48 hours, or "
        f"grab 15 minutes here: {CALENDLY}")
    sig = persona.get("signature", f"{name}\nDiraya Inc")
    text = "\n\n".join(paras) + "\n\n" + sig
    if dry:
        print(f"     [dry] would REVIEW->{to_addr} from {persona['from_addr']} "
              f"(attach {REVIEW_PDF.name}, link={'yes' if link else 'no'}, bcc {ALERT_TO})")
        return True
    if not REVIEW_PDF.exists():
        print(f"     ! missing REVIEW PDF at {REVIEW_PDF}"); return False
    # bcc Mohammed (info@diraya.ca) for visibility + to follow up with the tailored version
    return _post_email(env["RESEND_NEW_ACCOUNT_API_KEY"], {
        "from": f"{persona['from_name']} <{persona['from_addr']}>",
        "to": [to_addr], "bcc": [ALERT_TO], "reply_to": persona.get("reply_to", ALERT_TO),
        "subject": "Your architecture review",
        "html": _wrap_html(paras, sig), "text": text,
        "attachments": [{"filename": REVIEW_PDF.name,
                         "content": base64.b64encode(REVIEW_PDF.read_bytes()).decode()}],
        "tags": [{"name": "kind", "value": "diraya_review_fulfil"}],
    })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    env = load_env()
    rk = env.get("RESEND_NEW_ACCOUNT_API_KEY")
    if not rk:
        print("! no RESEND_NEW_ACCOUNT_API_KEY in hostinger.env"); return 1

    verified = verified_roots(rk)
    persona = pick_persona(verified)
    if not persona:
        print(f"No verified Diraya sender yet (verified subdomains: {sorted(verified) or 'none'}). "
              f"Nothing can send; will fulfil once a domain verifies. [no-op]")
        # still record nothing; safe to re-run
        return 0
    print(f"using sender: {persona['from_name']} <{persona['from_addr']}>  "
          f"(verified roots: {len(verified)})")
    link = env.get("DIRAYA_GHOSTS_URL") or ""
    review_link = env.get("DIRAYA_REVIEW_URL") or ""

    fulfilled = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    replies = supa_get(env, "replies?select=id,from_addr,body_snippet,received_at"
                            "&order=received_at.desc&limit=500")
    cand = []
    for r in replies:
        addr = (r.get("from_addr") or "").lower()
        if not addr or is_ours(addr) or r["id"] in fulfilled:
            continue
        it = intent_of(r.get("body_snippet"))
        if it:
            cand.append((r, addr, it))
    print(f"replies: {len(replies)} | pending GHOSTS/REVIEW: {len(cand)}")

    n_done = 0
    newly = []
    for r, addr, it in cand:
        ps = supa_get(env, f"prospects?profile_slug=eq.diraya&email=eq.{urllib.parse.quote(addr)}"
                           f"&select=first_name,company,unsubscribed&limit=1")
        if not ps:
            print(f"  - {addr}: not a diraya prospect (skip)")
            continue
        p = ps[0]
        if p.get("unsubscribed"):
            print(f"  - {addr}: unsubscribed (skip)")
            continue
        fn = (p.get("first_name") or "").strip()
        co = (p.get("company") or "").strip()
        if it == "ghosts":
            print(f"  + {addr} [GHOSTS] -> send list")
            if send_ghosts(env, addr, fn, persona, link, args.dry):
                newly.append(r["id"]); n_done += 1
        else:
            print(f"  + {addr} [REVIEW] -> send architecture review")
            if send_review(env, addr, fn, co, persona, review_link, args.dry):
                newly.append(r["id"]); n_done += 1

    if not args.dry and newly:
        STATE.write_text(json.dumps(sorted(fulfilled | set(newly))))
    print(f"\nfulfilled {n_done}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
