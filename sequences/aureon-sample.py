# -*- coding: utf-8 -*-
"""aureon-sample.py, fulfil Aureon Global's MAGIC give-first lead magnet.

The magnet (aureon-default sequence, keyword SAMPLE): a prospect who replies the
word SAMPLE is promised a COMPLETE slice of the paid product, free:
  * 3 ready-to-send cold emails written for their business
  * 25 verified leads in their exact ICP (name, company, direct email)

That is Hormozi magnet type 2 (free sample of the actual thing) fused with type 3
(step one of the multi-step engine): finishing it proves the machine works and
reveals the next problem (they can send 25, they need the engine for 2,500), which
is exactly what the paid done-for-you offer solves.

Unlike the one-shot PDF magnets in fulfill-magnets.py, a sample must be BUILT per
replier, so this runs in two phases and never double-fires (idempotent state file):

  py aureon-sample.py                 # INTAKE: scan SAMPLE replies -> work orders + notify
  py aureon-sample.py --auto          # + try to auto-write the 3 emails via local claude CLI
  py aureon-sample.py --deliver       # send every work order the operator moved to ready/
  py aureon-sample.py --dry           # show, never send / never write state

Fulfilment flow:
  pending/<reply_id>.json   intake writes it here (prospect + inferred ICP + brief)
  ready/<reply_id>.json     operator (or --auto) fills emails[3] + leads[25], moves here
  sent/<reply_id>.json      --deliver sends the branded deliverable, moves here, marks done

Safe to schedule now: with no SAMPLE replies it is a clean no-op.
"""
from __future__ import annotations
import argparse, base64, json, re, subprocess, sys, urllib.parse, urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
SEQ = Path(__file__).resolve().parent
WO = REPO / "lead-magnets" / "sample-workorders"
PENDING, READY, SENT = WO / "pending", WO / "ready", WO / "sent"
STATE = WO / ".intake_seen.json"
NOTIFY = WO / "NOTIFY.log"
SLUG = "aureon"
KEYWORDS = ["sample"]
UA = "les-aureon-sample/1.0"
OPERATOR = "info@aureonglobal.de"
ACCENT = "#d4af37"

# ── env + supabase (same pattern as fulfill-magnets.py) ──────────────────────
def load_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); out[k.strip()] = v.strip().strip('"').strip("'")
    return out

SENV = load_env(SEQ / "supabase.env")
URL = SENV.get("SUPABASE_URL", "").rstrip("/")
ANON = SENV.get("SUPABASE_ANON_KEY") or SENV.get("SUPABASE_KEY") or ""
H = {"apikey": ANON, "Authorization": "Bearer " + ANON, "User-Agent": UA}


def supa_get(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=40).read())


def resend_key() -> str:
    for pf in (REPO / "profiles" / "aureon.private.json",
               REPO / "desktop" / "frontend" / "public" / "profiles" / "aureon.private.json"):
        if pf.exists():
            k = (json.loads(pf.read_text(encoding="utf-8")).get("relay") or {}).get("resend_api_key")
            if k:
                return k
    env = load_env(SEQ / "hostinger.env")
    return env.get("RESEND_NEW_ACCOUNT_API_KEY") or env.get("RESEND_API_KEY") or ""


# ── reply parsing (read only the top, before quoted history) ─────────────────
_QUOTE_RE = re.compile(r"^(_{5,}|-{5,}|from:|sent:|to:|subject:|on .+wrote:|>.*|am .+schrieb|le .+a écrit)", re.I)


def top_reply(body: str) -> str:
    out = []
    for ln in (body or "").splitlines():
        if _QUOTE_RE.match(ln.strip()):
            break
        out.append(ln)
    return "\n".join(out)


def keyword_hit(top: str) -> str | None:
    low = (top or "").lower()
    for kw in KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", low):
            return kw
    return None


def is_ours(addr: str) -> bool:
    return "aureonglobal" in addr.split("@")[-1].lower()


# ── phase 1: intake ──────────────────────────────────────────────────────────
def infer_icp(prospect: dict) -> str:
    ctx = prospect.get("enriched_context") or {}
    for key in ("icp", "target_market", "sells_to"):
        if ctx.get(key):
            return str(ctx[key])
    return "the companies this business sells to (operator: confirm from their site before sourcing)"


def brief(prospect: dict, addr: str) -> dict:
    co = (prospect.get("company") or "").strip()
    domain = addr.split("@")[-1]
    return {
        "reply_id": None,
        "prospect": {
            "first_name": (prospect.get("first_name") or "").strip(),
            "company": co,
            "email": addr,
            "domain": domain,
            "website": f"https://{domain}",
        },
        "icp": infer_icp(prospect),
        "sourcing_query": f"Businesses that are the ideal customers of {co or domain}. "
                          f"Operator: refine to the exact ICP, then source 25 with a name, "
                          f"company, and direct email each via the normal lead pipeline.",
        "email_brief": (
            f"Write THREE cold emails {co or domain} could send today to its own ideal "
            f"customers. Give-first, plain, no apostrophes or em-dashes, one clear ask each. "
            f"Email 1: soft value opener. Email 2: name a specific pain + one proof point. "
            f"Email 3: a low-friction offer or question. Sign as {co or 'the business'}."
        ),
        "emails": [],          # operator or --auto fills: list of 3 {subject, body}
        "leads": [],           # operator fills: 25 {name, company, email}
        "status": "pending",
    }


def intake(dry: bool) -> dict:
    for d in (PENDING, READY, SENT):
        d.mkdir(parents=True, exist_ok=True)
    seen = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    stats = {"new": 0, "skipped": 0}
    if not URL or not ANON:
        print("aureon-sample: no supabase env, cannot read replies (no-op)"); return stats
    rows = supa_get(f"replies?profile_slug=eq.{SLUG}&class=eq.reply"
                    f"&select=id,from_addr,body_snippet&order=received_at.desc&limit=300")
    for r in rows:
        rid = r["id"]
        if rid in seen:
            stats["skipped"] += 1; continue
        addr = (r.get("from_addr") or "").lower()
        if not addr or is_ours(addr):
            continue
        if not keyword_hit(top_reply(r.get("body_snippet"))):
            continue
        ps = supa_get(f"prospects?profile_slug=eq.{SLUG}&email=eq.{urllib.parse.quote(addr)}"
                      f"&select=first_name,company,unsubscribed,enriched_context&limit=1")
        if not ps or ps[0].get("unsubscribed"):
            continue
        wo = brief(ps[0], addr); wo["reply_id"] = rid
        path = PENDING / f"{rid}.json"
        if dry:
            print(f"[dry] work order -> {path.name} for {addr} ({wo['prospect']['company']})")
        else:
            path.write_text(json.dumps(wo, indent=2), encoding="utf-8")
            with NOTIFY.open("a", encoding="utf-8") as fh:
                fh.write(f"SAMPLE reply from {addr} ({wo['prospect']['company']}) -> "
                         f"{path}. Fill 3 emails + 25 leads, move to ready/, run --deliver.\n")
            print(f"NEW SAMPLE: {addr} ({wo['prospect']['company']}) -> {path.name}")
        seen.add(rid); stats["new"] += 1
    if not dry:
        STATE.write_text(json.dumps(sorted(seen)))
    print(f"=== aureon-sample intake === {json.dumps(stats)}")
    return stats


# ── optional: auto-write the 3 emails via the local claude CLI ────────────────
def claude_bin() -> str | None:
    # memory: on Windows the CLI must be claude.exe (the .cmd shim fails WinError 2)
    for name in ("claude.exe", "claude"):
        try:
            subprocess.run([name, "--version"], capture_output=True, timeout=20)
            return name
        except Exception:
            continue
    return None


def auto_emails(dry: bool) -> None:
    PENDING.mkdir(parents=True, exist_ok=True)
    cb = claude_bin()
    if not cb:
        print("aureon-sample --auto: no local claude CLI on PATH (auth/login blocked). "
              "Leaving work orders pending for the operator."); return
    for path in sorted(PENDING.glob("*.json")):
        wo = json.loads(path.read_text(encoding="utf-8"))
        if wo.get("emails"):
            continue
        prompt = (wo["email_brief"] + "\n\nReturn STRICT JSON only: "
                  '{"emails":[{"subject":"...","body":"..."},{...},{...}]}. '
                  "No prose outside the JSON.")
        if dry:
            print(f"[dry] would ask claude to write emails for {path.name}"); continue
        try:
            out = subprocess.run([cb, "-p", prompt], capture_output=True, text=True, timeout=180)
            m = re.search(r"\{.*\}", out.stdout, re.S)
            emails = json.loads(m.group(0))["emails"] if m else []
            if len(emails) == 3:
                wo["emails"] = emails
                path.write_text(json.dumps(wo, indent=2), encoding="utf-8")
                print(f"auto-wrote 3 emails for {path.name} (still needs 25 leads, then move to ready/)")
        except Exception as e:
            print(f"auto-gen failed for {path.name}: {str(e)[:120]}")


# ── phase 2: deliver ─────────────────────────────────────────────────────────
def _esc(s: str) -> str:
    import html
    return html.escape(s or "", quote=True)


def deliverable_html(wo: dict) -> str:
    p = wo["prospect"]; co = _esc(p.get("company") or "your business")
    em_html = ""
    for i, e in enumerate(wo["emails"], 1):
        body = _esc(e.get("body", "")).replace("\n", "<br>")
        em_html += (f"<div style='margin:0 0 18px;border-left:3px solid {ACCENT};padding:2px 0 2px 14px'>"
                    f"<div style='font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#9ca3af'>Email {i}</div>"
                    f"<div style='font-weight:600;margin:2px 0 6px'>{_esc(e.get('subject',''))}</div>"
                    f"<div style='color:#1a1a1a;line-height:1.6'>{body}</div></div>")
    rows = "".join(
        f"<tr><td style='padding:6px 10px;border-bottom:1px solid #eee'>{_esc(l.get('name',''))}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{_esc(l.get('company',''))}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{_esc(l.get('email',''))}</td></tr>"
        for l in wo.get("leads", []))
    lead_table = (f"<table style='border-collapse:collapse;width:100%;font-size:13px'>"
                  f"<tr><th style='text-align:left;padding:6px 10px;border-bottom:2px solid {ACCENT}'>Name</th>"
                  f"<th style='text-align:left;padding:6px 10px;border-bottom:2px solid {ACCENT}'>Company</th>"
                  f"<th style='text-align:left;padding:6px 10px;border-bottom:2px solid {ACCENT}'>Direct email</th></tr>"
                  f"{rows}</table>") if wo.get("leads") else ""
    return f"""<div style="font-family:Inter,-apple-system,Segoe UI,sans-serif;color:#1a1a1a;max-width:640px;line-height:1.6;font-size:15px">
<div style="background:#050505;color:#fff;padding:20px 22px;border-radius:10px 10px 0 0">
  <div style="color:{ACCENT};font-weight:700;letter-spacing:.04em">AUREON GLOBAL</div>
  <div style="font-size:13px;color:#9ca3af">Your free sample: 3 cold emails + {len(wo.get('leads', []))} verified leads for {co}</div>
</div>
<div style="border:1px solid #ececec;border-top:none;padding:22px;border-radius:0 0 10px 10px">
  <p>Here is your sample, exactly as promised. These three emails are written for {co} and ready to send. The leads below are yours to keep and send them to. No call, no pitch to sit through.</p>
  <h3 style="margin:20px 0 10px">Three cold emails, ready to send</h3>
  {em_html}
  <h3 style="margin:22px 0 10px">Your verified leads</h3>
  {lead_table}
  <div style="margin-top:22px;padding:16px;background:#faf7ec;border-radius:8px">
    <b>What happens if you send these yourself:</b> you can work these {len(wo.get('leads', []))} by hand and book a call or two.
    That is the point of the sample. The engine we run for clients does this at volume, a fresh ICP list every week,
    the writing, the sending, and the follow up all done for you, so the booked calls just show up on your calendar.
    If you want to see what the first 30 days would look like for {co}, just reply to this email.
  </div>
</div></div>"""


def send_resend(rk: str, to_addr: str, subject: str, html: str, text: str, csv_bytes: bytes | None, dry: bool) -> bool:
    if dry:
        print(f"    [dry] would send '{subject}' -> {to_addr} (bcc {OPERATOR})"); return True
    payload = {
        "from": "Aureon Global <hello@mail.aureonglobal.de>", "to": [to_addr],
        "bcc": [OPERATOR], "reply_to": OPERATOR, "subject": subject, "text": text, "html": html,
        "tags": [{"name": "kind", "value": "sample_magnet"}],
    }
    if csv_bytes:
        payload["attachments"] = [{"filename": "your-25-leads.csv",
                                   "content": base64.b64encode(csv_bytes).decode()}]
    try:
        urllib.request.urlopen(urllib.request.Request(
            "https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
            headers={"Authorization": f"Bearer {rk}", "Content-Type": "application/json", "User-Agent": UA}),
            timeout=30)
        return True
    except Exception as e:
        err = getattr(e, "read", lambda: b"")()
        print(f"    ! send failed: {e} {err[:160]}"); return False


def deliver(dry: bool) -> dict:
    for d in (READY, SENT):
        d.mkdir(parents=True, exist_ok=True)
    rk = resend_key()
    stats = {"sent": 0, "incomplete": 0}
    if not rk:
        print("aureon-sample --deliver: no Resend key configured (no-op)"); return stats
    for path in sorted(READY.glob("*.json")):
        wo = json.loads(path.read_text(encoding="utf-8"))
        if len(wo.get("emails", [])) != 3 or len(wo.get("leads", [])) < 1:
            print(f"  {path.name}: not ready (needs 3 emails + leads), skipping"); stats["incomplete"] += 1; continue
        p = wo["prospect"]
        csv = ("Name,Company,Email\n" + "\n".join(
            f"{l.get('name','')},{l.get('company','')},{l.get('email','')}" for l in wo["leads"])).encode()
        text = ("Here is your free sample: three cold emails written for you plus your verified leads (attached csv). "
                "Yours to keep and send. Reply if you want to see what a full engine would look like.")
        ok = send_resend(rk, p["email"],
                         f"Your 3 cold emails and {len(wo['leads'])} leads, {p.get('company') or 'as promised'}",
                         deliverable_html(wo), text, csv, dry)
        if ok and not dry:
            wo["status"] = "sent"; (SENT / path.name).write_text(json.dumps(wo, indent=2), encoding="utf-8")
            path.unlink(); stats["sent"] += 1
            print(f"  delivered sample -> {p['email']}")
        elif ok:
            stats["sent"] += 1
    print(f"=== aureon-sample deliver === {json.dumps(stats)}")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", action="store_true", help="send ready work orders")
    ap.add_argument("--auto", action="store_true", help="try to auto-write the 3 emails via local claude CLI")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.deliver:
        deliver(a.dry)
    else:
        intake(a.dry)
        if a.auto:
            auto_emails(a.dry)


if __name__ == "__main__":
    main()
