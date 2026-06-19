# -*- coding: utf-8 -*-
"""fulfill-magnets.py, auto-fulfil every client's give-first lead magnet when a
prospect replies the magnet keyword by email.

Generalises the proven fulfill-diraya-magnets pattern to all clients, driven by
lead-magnets/magnet-specs.json (keyword(s) -> branded PDF + cover email + subject).
For each client it sends ONLY from a Resend-verified sender (else it no-ops, safe
to schedule now), attaches the visual PDF, bccs the client's report_to, and marks
the reply fulfilled so it never double-sends. Idempotent via a shared state file.

    py fulfill-magnets.py            # fulfil all pending, all clients
    py fulfill-magnets.py --dry      # show what it would do, no send
    py fulfill-magnets.py --client mark-eting
"""
from __future__ import annotations
import argparse, base64, glob, json, re, sys, urllib.parse, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPECS_FILE = REPO / "lead-magnets" / "magnet-specs.json"
STATE = REPO / "lead-magnets" / ".magnets_fulfilled.json"
OPERATOR = "info@aureonglobal.de"
UA = "les-magnets/1.0"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); out[k.strip()] = v.strip().strip('"').strip("'")
    return out


SENV = load_env(REPO / "sequences" / "supabase.env")
HENV = load_env(REPO / "sequences" / "hostinger.env")
URL = SENV["SUPABASE_URL"].rstrip("/")
ANON = SENV.get("SUPABASE_ANON_KEY") or SENV.get("SUPABASE_KEY")
H = {"apikey": ANON, "Authorization": "Bearer " + ANON, "User-Agent": UA}


def supa_get(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=40).read())


# ── reply parsing: read only the TOP of the reply (before quoted history) ──
_QUOTE_RE = re.compile(r"^(_{5,}|-{5,}|from:|sent:|to:|subject:|on .+wrote:|>.*|am .+schrieb|le .+a écrit)",
                       re.IGNORECASE)


def top_reply(body: str) -> str:
    out = []
    for ln in (body or "").splitlines():
        if _QUOTE_RE.match(ln.strip()):
            break
        out.append(ln)
    return "\n".join(out)


def keyword_hit(top: str, keywords: list[str]) -> str | None:
    low = (top or "").lower()
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw.lower()) + r"\b", low):
            return kw
    return None


def verified_domains(resend_key: str) -> set[str]:
    try:
        data = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://api.resend.com/domains",
            headers={"Authorization": "Bearer " + resend_key, "User-Agent": UA}), timeout=20).read())
    except Exception as e:
        print(f"    ! could not list Resend domains: {str(e)[:80]}"); return set()
    return {d["name"] for d in data.get("data", []) if d.get("status") == "verified"}


def is_ours(addr: str, client_domains: set[str]) -> bool:
    dom = addr.split("@")[-1].lower()
    return ("aureonglobal" in dom or dom in {d.lower() for d in client_domains}
            or any(dom.endswith(d.lower()) for d in client_domains))


def client_cfg(slug: str) -> tuple[str | None, str | None]:
    """(resend_key, report_to) for a client, from its profile files."""
    rk = None
    pp = REPO / "profiles" / f"{slug}.private.json"
    if pp.exists():
        rk = (json.loads(pp.read_text(encoding="utf-8")).get("relay") or {}).get("resend_api_key")
    rk = rk or HENV.get("RESEND_NEW_ACCOUNT_API_KEY")
    rt = None
    pf = REPO / "profiles" / f"{slug}.json"
    if pf.exists():
        p = json.loads(pf.read_text(encoding="utf-8"))
        rt = (p.get("relay") or {}).get("report_to") or ((p.get("brand") or {}).get("legal") or {}).get("contact_email")
    return rk, rt


def pdf_for(slug: str) -> Path | None:
    hits = sorted(glob.glob(str(REPO / "lead-magnets" / f"{slug}--*.pdf")))
    return Path(hits[0]) if hits else None


def merge(text: str, first_name: str, company: str) -> str:
    g = first_name.strip() or "there"
    return (text or "").replace("{greeting}", g).replace("{first_name}", g).replace("{company}", company or "")


def _wrap_html(text: str, accent: str) -> str:
    import html as _h
    paras = "".join(f"<p style='margin:0 0 12px'>{_h.escape(p).strip()}</p>"
                    for p in re.split(r"\n\s*\n", text.strip()) if p.strip())
    return (f"<div style=\"font-family:-apple-system,Segoe UI,Inter,sans-serif;color:#1a1a1a;"
            f"max-width:580px;line-height:1.55;font-size:15px;border-top:3px solid {accent};padding-top:14px\">"
            f"{paras}</div>")


def send(resend_key, from_name, from_addr, to_addr, report_to, subject, body, pdf: Path, accent, dry) -> bool:
    if dry:
        print(f"    [dry] would send '{subject}' from {from_addr} -> {to_addr} "
              f"(attach {pdf.name}, bcc {report_to or OPERATOR})")
        return True
    payload = {
        "from": f"{from_name} <{from_addr}>", "to": [to_addr],
        "bcc": [report_to or OPERATOR], "reply_to": report_to or from_addr,
        "subject": subject, "text": body, "html": _wrap_html(body, accent),
        "attachments": [{"filename": pdf.name, "content": base64.b64encode(pdf.read_bytes()).decode()}],
        "tags": [{"name": "kind", "value": "magnet_fulfil"}],
    }
    try:
        urllib.request.urlopen(urllib.request.Request(
            "https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json", "User-Agent": UA}),
            timeout=30)
        return True
    except Exception as e:
        body_err = getattr(e, "read", lambda: b"")()
        print(f"    ! send failed: {e} {body_err[:140]}"); return False


def run(only: str | None, dry: bool) -> dict:
    specs = json.loads(SPECS_FILE.read_text(encoding="utf-8"))
    fulfilled = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    stats = {"clients": 0, "sent": 0, "no_sender": 0, "pending": 0}
    newly = []
    for spec in specs:
        slug = spec["client_slug"]
        if only and slug != only:
            continue
        resend_key, report_to = client_cfg(slug)
        pdf = pdf_for(slug)
        if not resend_key or not pdf:
            print(f"{slug}: missing resend key or pdf, skip"); continue
        stats["clients"] += 1
        vds = verified_domains(resend_key)
        fa = spec.get("from_addr") or ""
        fa_dom = fa.split("@")[-1] if "@" in fa else ""
        # Send ONLY from the client's OWN registrable domain. Several clients share
        # one Resend account, so never borrow another client's verified domain: a
        # client whose own domain is not verified must no-op, not send from someone
        # else's address.
        root = ".".join(fa_dom.split(".")[-2:]) if fa_dom.count(".") >= 1 else fa_dom
        own = {d for d in vds if d == root or d.endswith("." + root)}
        if fa_dom in own:
            from_addr = fa
        elif own:
            from_addr = f"{(fa.split('@')[0] or 'hello')}@{sorted(own)[0]}"
        else:
            print(f"{slug}: no verified sender on {root} yet, no-op (arms when its domain verifies)")
            stats["no_sender"] += 1; continue
        from_name = spec.get("from_name") or slug
        rows = supa_get(f"replies?profile_slug=eq.{slug}&class=eq.reply"
                        f"&select=id,from_addr,body_snippet&order=received_at.desc&limit=300")
        pend = 0
        for r in rows:
            if r["id"] in fulfilled:
                continue
            addr = (r.get("from_addr") or "").lower()
            if not addr or is_ours(addr, vds):
                continue
            kw = keyword_hit(top_reply(r.get("body_snippet")), spec["magnet_keywords"])
            if not kw:
                continue
            ps = supa_get(f"prospects?profile_slug=eq.{slug}&email=eq.{urllib.parse.quote(addr)}"
                          f"&select=first_name,company,unsubscribed&limit=1")
            if not ps or ps[0].get("unsubscribed"):
                continue
            pend += 1; stats["pending"] += 1
            fn = (ps[0].get("first_name") or "").strip(); co = (ps[0].get("company") or "").strip()
            body = merge(spec["cover_email"], fn, co)
            print(f"{slug}: [{kw}] -> fulfil {addr}")
            if send(resend_key, from_name, from_addr, addr, report_to,
                    spec.get("email_subject", "Your free resource"), body, pdf, spec.get("accent_hex", "#1a1a1a"), dry):
                newly.append(r["id"]); stats["sent"] += 1
        print(f"{slug}: sender {from_addr}, pending {pend}")
    if not dry and newly:
        STATE.write_text(json.dumps(sorted(fulfilled | set(newly))))
    print(f"\n=== fulfill-magnets === {json.dumps(stats)}")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--client", default=None)
    a = ap.parse_args()
    run(a.client, a.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
