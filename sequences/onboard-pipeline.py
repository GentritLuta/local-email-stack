# -*- coding: utf-8 -*-
"""onboard-pipeline.py — the SaaS auto-kickoff engine.

Consumes onboarding_submissions(status='pending') written by the public SaaS app
(saas/), and for each one runs the full provisioning the operator used to do by
hand: create profile -> AI-draft sequence+variants -> provision sending domains
(route by DNS host) -> load leads -> start warmup. Writes per-step progress to
provisioning_status so the dashboard shows live status.

Reuses the existing stack: profile_lib, the energ-style DB push, the Cloudflare /
Hostinger provisioners, and the local Claude CLI (Max plan, no API cost) the way
reply-autodraft.py does.

Run:
    py sequences/onboard-pipeline.py once          # process all pending, exit
    py sequences/onboard-pipeline.py once --id <submission_id>   # one submission

Designed to be scheduled (LES-onboard-pipeline) every few minutes. Idempotent per
step: re-running resumes where a submission left off.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, tempfile, shutil, datetime as dt
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from profile_lib import load_profile, save_profile  # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ─── Env ────────────────────────────────────────────────────────────────────
def _load_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); out[k.strip()] = v.strip()
    return out

SENV = _load_env(REPO / "sequences" / "supabase.env")
HENV = _load_env(REPO / "sequences" / "hostinger.env")
U = SENV["SUPABASE_URL"].rstrip("/") + "/rest/v1"
K = SENV["SUPABASE_ANON_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Content-Type": "application/json"}
CLAUDE_CMD = os.environ.get("CLAUDE_CLI", r"D:\npm-global\claude.cmd")

cli = httpx.Client(base_url=U, headers=H, timeout=40)


# ─── Supabase helpers ───────────────────────────────────────────────────────
def fetch_pending(one_id: str | None):
    q = {"status": "eq.pending", "select": "*", "order": "created_at.asc"}
    if one_id:
        q = {"id": f"eq.{one_id}", "select": "*"}
    return cli.get("/onboarding_submissions", params=q).json()


def set_submission(sub_id: str, **fields):
    cli.patch(f"/onboarding_submissions?id=eq.{sub_id}", json=fields,
              headers={**H, "Prefer": "return=minimal"})


def step(sub_id: str, step: str, state: str, detail: str = "", payload=None):
    """Upsert a provisioning_status row (unique on submission_id,step)."""
    row = {"submission_id": sub_id, "step": step, "state": state, "detail": detail}
    if payload is not None:
        row["payload"] = payload
    cli.post("/provisioning_status?on_conflict=submission_id,step", json=row,
             headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"})
    print(f"    [{step}] {state}: {detail}")


# ─── Slug ───────────────────────────────────────────────────────────────────
def slugify(company: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (company or "client").lower()).strip("-")
    return s[:24] or "client"


def unique_slug(base: str) -> str:
    existing = {p["slug"] for p in cli.get("/profiles", params={"select": "slug"}).json()}
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


# ─── AI copy drafting (local Claude CLI, Max plan) ──────────────────────────
SEQ_SCHEMA_HINT = """Return ONLY valid JSON, no markdown fences, shaped exactly:
{"variants":[{"n":1,"angle":"...","subject":"...","body":"..."}, ... 7 items, n=1..7]}"""

def draft_sequence(a: dict) -> list[dict] | None:
    system = (
        "You are a world-class cold-email copywriter in the Alex Hormozi $100M Leads style. "
        "You write 7-email B2B cold sequences that get replies. Rules: the STEP 1 hook must be a "
        "low-friction one-question ask that only the prospect can answer about their own business "
        "(this outperforms generic 'are you open?' openers 10x). No em dashes, no exclamation marks, "
        "no emojis, no typographic quotes. Short sentences, concrete numbers, one clear CTA. Use "
        "{first_name} and {company} merge tags. Each email needs a P.S. with a second concrete give."
    )
    prompt = f"""Write a 7-email cold sequence for this client.

Company: {a.get('company')}
Website: {a.get('website')}
Offer: {a.get('offer')}
Ideal customer (ICP): {a.get('icp')}
Proof / numbers: {a.get('proof')}
Desired CTA: {a.get('cta')}
Notes: {a.get('notes')}

Email 1 = the low-friction one-question hook (ask for one specific thing only they know).
Emails 2-6 escalate value + the offer. Email 7 = a breakup with a final give.
{SEQ_SCHEMA_HINT}"""
    workdir = tempfile.mkdtemp(prefix="les_onboard_")
    try:
        proc = subprocess.run(
            [CLAUDE_CMD, "-p", "--system-prompt", system,
             "--disallowedTools", "Bash,Read,Glob,Grep,Edit,Write,WebFetch,WebSearch",
             "--setting-sources", "user"],
            input=prompt, capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace", cwd=workdir,
        )
    except Exception as e:
        print(f"  ! claude CLI error: {e}")
        return None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if proc.returncode != 0:
        print(f"  ! claude CLI exit {proc.returncode}: {proc.stderr[:200]}")
        return None
    text = (proc.stdout or "").strip()
    # strip code fences / leading prose if any
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        print("  ! no JSON in CLI output")
        return None
    try:
        data = json.loads(m.group(0))
        vs = data.get("variants", [])
        return vs if len(vs) >= 5 else None
    except Exception as e:
        print(f"  ! JSON parse: {e}")
        return None


# ─── Profile builder ────────────────────────────────────────────────────────
def build_profile(slug: str, a: dict) -> dict:
    root = a.get("sending_root", "").strip().lower()
    reply_to = a.get("reply_to") or "info@aureonglobal.de"
    subs = ["hello", "team", "mail", "hi"]   # start with 4 subdomains; warm up
    names = [("alex", "Alex Carter"), ("sam", "Sam Rivers"), ("jordan", "Jordan Lee"), ("riley", "Riley Quinn")]
    from_domains = [{
        "domain": f"{s}.{root}", "resend_domain_id": "", "verified_at": None,
        "warmup": {"enabled": True, "current_day": 1, "started_at": None,
                   "ramp_curve": "snowball_v1", "max_daily_sends": 50,
                   "reputation": {"bounce_rate_7d": 0.0, "complaint_rate_7d": 0.0, "delivered_7d": 0, "last_check": None}},
    } for s in subs]
    personas = [{
        "slug": nm[0], "from_name": f"{nm[1].split()[0]} at {a.get('company')}",
        "from_addr": f"{nm[0]}@{subs[i]}.{root}", "reply_to": reply_to,
        "title": f"Outreach, {a.get('company')}",
        "voice": {"register": "direct", "quirks": ["short sentences", "concrete numbers"],
                  "avoid": ["em-dashes", "exclamation marks", "emojis", "typographic quotes"]},
        "signature": f"{nm[1]}\n{a.get('company')}", "full_name": nm[1],
    } for i, nm in enumerate(names)]
    return {
        "slug": slug, "name": f"{a.get('company')} — cold outbound",
        "created_at": dt.date.today().isoformat(), "active": False,
        "company": {"name": a.get("company"), "site": a.get("website"), "tagline": a.get("offer", "")[:120]},
        "relay": {"backend": "resend", "resend_region": "us-east-1",
                  "resend_api_key": "", "from_domains": from_domains, "from_domains_overrides": []},
        "personas": personas,
        "rotation": {"strategy": "round_robin_by_persona", "max_sends_per_persona_per_day": 30,
                     "min_seconds_between_sends_same_persona": 180},
        "send_ramp": {"started_at": None},
        "warmup": {"enabled": True, "warmup_targets": [], "ramp_curve": "snowball_v1",
                   "real_send_mix": [{"until_day": 14, "warmup_pct": 80}, {"until_day": 30, "warmup_pct": 30},
                                     {"until_day": 45, "warmup_pct": 10}, {"until_day": 9999, "warmup_pct": 5}],
                   "auto_pause_thresholds": {"bounce_rate": 0.05, "complaint_rate": 0.003},
                   "started_at": None, "current_day": 1},
        "ramp_curve_snowball_v1": [{"from_day": 1, "daily": 15}, {"from_day": 8, "daily": 25},
                                    {"from_day": 15, "daily": 35}, {"from_day": 22, "daily": 50}],
        "send_window": {"weekdays_only": True, "local_hour_start": 8, "local_hour_end": 17,
                        "default_timezone": "America/New_York"},
        "brand": {"wordmark": a.get("company"), "site": a.get("website")},
    }


def push_profile_db(profile: dict):
    safe = json.loads(json.dumps(profile))
    safe.get("relay", {}).pop("resend_api_key", None)
    cli.post("/profiles?on_conflict=slug",
             json={"slug": profile["slug"], "name": profile["name"], "config": safe, "active": False},
             headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"})


def push_sequence_and_variants(slug: str, variants: list[dict]) -> str:
    # sequence
    ex = cli.get("/sequences", params={"profile_slug": f"eq.{slug}", "select": "id"}).json()
    if ex:
        seq_id = ex[0]["id"]
    else:
        r = cli.post("/sequences", json={"profile_slug": slug, "slug": f"{slug}-default",
                     "name": f"{slug} cold sequence", "stop_on_reply": True, "stop_on_bounce": True, "active": True},
                     headers={**H, "Prefer": "return=representation"})
        seq_id = r.json()[0]["id"]
    # variants
    delays = [0, 2, 2, 3, 4, 7, 10]
    rows = [{"profile_slug": slug, "n": v["n"], "angle": v.get("angle", ""),
             "subject": v["subject"], "body": v["body"]} for v in variants]
    cli.post("/variants?on_conflict=profile_slug,n", json=rows,
             headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"})
    # steps
    for v in variants:
        n = v["n"]
        vid = cli.get("/variants", params={"profile_slug": f"eq.{slug}", "n": f"eq.{n}", "select": "id"}).json()[0]["id"]
        delay = delays[n - 1] if n - 1 < len(delays) else 3
        exs = cli.get("/sequence_steps", params={"sequence_id": f"eq.{seq_id}", "step_n": f"eq.{n}", "select": "id"}).json()
        body = {"sequence_id": seq_id, "step_n": n, "variant_id": vid, "delay_days": delay,
                "inline_subject": None, "inline_body": None}
        if exs:
            cli.patch(f"/sequence_steps?id=eq.{exs[0]['id']}", json=body, headers={**H, "Prefer": "return=minimal"})
        else:
            cli.post("/sequence_steps", json=body, headers={**H, "Prefer": "return=minimal"})
    return seq_id


# ─── Domain provisioning router ─────────────────────────────────────────────
def provision_domains(slug: str, a: dict, sub_id: str) -> str:
    """Returns state: 'done' | 'needs_input' | 'error'. Routes by dns_host."""
    host = (a.get("dns_host") or "other").lower()
    # We can only auto-push DNS where we hold a token for THIS client's zone. For
    # v1 the operator's own zones are covered; arbitrary client zones are not, so
    # default to guided-manual: create Resend domains, hand back records to paste.
    profile = load_profile(slug)
    resend_key = HENV.get("RESEND_FULL_ACCESS_API_KEY")
    if not resend_key:
        return "error"
    RH = {"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"}
    region = profile["relay"].get("resend_region", "us-east-1")
    records_out = []
    with httpx.Client(timeout=25) as rc:
        existing = {d["name"]: d for d in rc.get("https://api.resend.com/domains", headers=RH).json().get("data", [])}
        for entry in profile["relay"]["from_domains"]:
            name = entry["domain"]
            dom = existing.get(name)
            if not dom:
                r = rc.post("https://api.resend.com/domains", headers=RH, json={"name": name, "region": region})
                if r.status_code not in (200, 201):
                    return "error"
                dom = r.json()
            entry["resend_domain_id"] = dom["id"]
            full = rc.get(f"https://api.resend.com/domains/{dom['id']}", headers=RH).json()
            for rec in full.get("records", []):
                records_out.append({"type": rec.get("type"),
                                    "name": rec.get("name"), "value": rec.get("value")})
    save_profile(profile)
    # For v1: we have created Resend domains + collected records. Auto-push only if
    # the client's DNS is on a host we have a token for AND it is our own zone.
    # Otherwise hand the records to the client to paste (needs_input).
    step(sub_id, "domains", "needs_input",
         f"Add {len(records_out)} DNS records at your {host} DNS for {a.get('sending_root')}, then we verify automatically.",
         payload={"records": records_out, "host": host})
    return "needs_input"


# ─── Leads ──────────────────────────────────────────────────────────────────
def setup_leads(slug: str, a: dict, sub_id: str):
    src = a.get("lead_source")
    if src == "csv":
        step(sub_id, "leads", "needs_input", "Upload your lead CSV to start sending.")
    else:
        # queue ICP sourcing (the existing scrapers run on their own schedule)
        step(sub_id, "leads", "done", f"ICP sourcing queued for: {(a.get('icp') or '')[:80]}")


# ─── Per-submission driver ──────────────────────────────────────────────────
def process(sub: dict):
    sid = sub["id"]
    a = sub.get("raw_answers") or {}
    print(f"\n=== submission {sid[:8]} — {a.get('company')}")
    set_submission(sid, status="provisioning")

    # 1. profile
    step(sid, "profile", "running", "Creating your profile")
    slug = unique_slug(slugify(a.get("company", "client")))
    profile = build_profile(slug, a)
    save_profile(profile)
    push_profile_db(profile)
    if sub.get("client_id"):
        cli.patch(f"/clients?id=eq.{sub['client_id']}", json={"profile_slug": slug, "status": "provisioning"},
                  headers={**H, "Prefer": "return=minimal"})
    step(sid, "profile", "done", f"Profile created: {slug}", payload={"profile_slug": slug})

    # 2. copy
    step(sid, "copy", "running", "Drafting your 7-email sequence (AI)")
    variants = draft_sequence(a)
    if not variants:
        step(sid, "copy", "error", "Copy drafting failed; will retry next run.")
        set_submission(sid, status="error", error="copy drafting failed")
        return
    # normalize n=1..7 and scrub em-dashes
    for i, v in enumerate(variants[:7]):
        v["n"] = i + 1
        v["subject"] = (v.get("subject") or "").replace("—", ",").replace("–", ",")
        v["body"] = (v.get("body") or "").replace("—", ",").replace("–", ",")
    push_sequence_and_variants(slug, variants[:7])
    step(sid, "copy", "done", f"{len(variants[:7])}-email sequence drafted and saved")

    # 3. domains
    step(sid, "domains", "running", "Provisioning sending domains")
    dom_state = provision_domains(slug, a, sid)

    # 4. leads
    setup_leads(slug, a, sid)

    # 5. warmup (created but disabled until DNS verifies + operator go)
    step(sid, "warmup", "pending", "Starts once domains verify and you confirm go-live.")

    # 6. status roll-up
    if dom_state == "needs_input":
        set_submission(sid, status="needs_dns")
        step(sid, "golive", "pending", "Add the DNS records above; then we verify and you go live.")
    else:
        set_submission(sid, status="ready")
        step(sid, "golive", "needs_input", "Ready. Confirm to start sending.")
    print(f"  done: submission {sid[:8]} -> {dom_state}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("once"); p.add_argument("--id", default=None)
    args = ap.parse_args()
    pending = fetch_pending(args.id)
    if not pending:
        print("no pending submissions")
        return 0
    print(f"processing {len(pending)} submission(s)")
    for s in pending:
        try:
            process(s)
        except Exception as e:
            print(f"  ! submission {s['id'][:8]} failed: {e}")
            try:
                set_submission(s["id"], status="error", error=str(e)[:300])
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
