"""sequence-runner.py — picks up due steps from runs in Supabase and sends them.

The brain that ties variants, sequences, and the rotating persona pool together.
Reads pending runs from Supabase, finds the right step + variant, picks an
eligible persona via rotation, sends via Resend, logs the outcome back to
Supabase, and advances the run to the next step (or pauses if reply/bounce).

Designed to run as a cron tick every 5 minutes:
    schtasks /Create /TN "LES-sequence-runner" /TR "py C:\\...\\sequence-runner.py tick" /SC MINUTE /MO 5

CLI:
    py sequence-runner.py tick                          # advance all due runs
    py sequence-runner.py enqueue <sequence_slug> <prospect_email>  # add a run
    py sequence-runner.py status                        # show queued/running counts
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
import uuid
from pathlib import Path

import httpx

from profile_lib import load_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE  = REPO_ROOT / "sequences" / "supabase.env"
RESEND_API = "https://api.resend.com/emails"


def load_supabase() -> tuple[str, str]:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        sys.exit(f"missing SUPABASE_URL / SUPABASE_ANON_KEY in {ENV_FILE}")
    return url.rstrip("/"), key


def supa(url: str, key: str) -> httpx.Client:
    return httpx.Client(
        base_url=f"{url}/rest/v1", timeout=20,
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Prefer": "return=representation"},
    )


# ─── Persona rotation (mirrors resend-pool-send.py) ────────────────────────

def pick_persona(profile_config: dict, send_log_rows: list[dict]) -> dict:
    personas = profile_config.get("personas", [])
    if not personas:
        sys.exit("profile has no personas")
    rot = profile_config.get("rotation", {})
    quota = int(rot.get("max_sends_per_persona_per_day", 30))
    min_gap = int(rot.get("min_seconds_between_sends_same_persona", 60))
    now_ts = time.time()
    today_start = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    usage = {p["slug"]: {"count_today": 0, "last_ts": 0.0} for p in personas}
    for row in send_log_rows:
        slug = row.get("persona_slug")
        if slug not in usage:
            continue
        try:
            ts = dt.datetime.fromisoformat(row["sent_at"].replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if ts >= today_start:
            usage[slug]["count_today"] += 1
        usage[slug]["last_ts"] = max(usage[slug]["last_ts"], ts)

    candidates = []
    for p in personas:
        u = usage[p["slug"]]
        if u["count_today"] >= quota: continue
        if (now_ts - u["last_ts"]) < min_gap: continue
        candidates.append((u["count_today"], u["last_ts"], p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]


# ─── Step lookup ───────────────────────────────────────────────────────────

def fetch_due_runs(c: httpx.Client) -> list[dict]:
    """Pull runs where status='queued' and (next_send_at <= now OR next_send_at IS NULL)."""
    now_iso = dt.datetime.utcnow().isoformat() + "Z"
    r = c.get(f"/runs?status=eq.queued&or=(next_send_at.lte.{now_iso},next_send_at.is.null)&select=*")
    r.raise_for_status()
    return r.json()


def fetch_sequence_step(c: httpx.Client, sequence_id: str, step_n: int) -> dict | None:
    r = c.get(f"/sequence_steps?sequence_id=eq.{sequence_id}&step_n=eq.{step_n}"
              f"&select=*,variants(subject,body)")
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


def fetch_max_step(c: httpx.Client, sequence_id: str) -> int:
    r = c.get(f"/sequence_steps?sequence_id=eq.{sequence_id}&select=step_n&order=step_n.desc&limit=1")
    r.raise_for_status()
    rows = r.json()
    return rows[0]["step_n"] if rows else 0


def fetch_prospect(c: httpx.Client, prospect_id: str) -> dict:
    r = c.get(f"/prospects?id=eq.{prospect_id}&select=*")
    r.raise_for_status()
    return r.json()[0]


def fetch_profile_config(c: httpx.Client, profile_slug: str) -> dict:
    r = c.get(f"/profiles?slug=eq.{profile_slug}&select=config")
    r.raise_for_status()
    return r.json()[0]["config"]


def fetch_today_log(c: httpx.Client, profile_slug: str) -> list[dict]:
    """Today's send_log rows for this profile (for rotation quota)."""
    today = dt.date.today().isoformat()
    r = c.get(f"/send_log?sent_at=gte.{today}T00:00:00&select=persona_slug,sent_at"
              f"&order=sent_at.desc&limit=500")
    r.raise_for_status()
    # Filter to this profile's personas (we don't have a profile_slug column on send_log;
    # this can be improved later. For now, all sends from same Supabase = same operator.)
    return r.json()


def get_api_key(profile_slug: str) -> str:
    priv = REPO_ROOT / "profiles" / f"{profile_slug}.private.json"
    if not priv.exists():
        sys.exit(f"missing {priv}")
    return json.loads(priv.read_text(encoding="utf-8")).get("relay", {}).get("resend_api_key", "")


# ─── Send + log ────────────────────────────────────────────────────────────

def send_via_resend(api_key: str, persona: dict, prospect: dict, subject: str, body: str) -> dict:
    domain = persona["from_addr"].split("@", 1)[1]
    msg_id = f"<{uuid.uuid4().hex}.{int(time.time())}@{domain}>"
    body_full = body + "\n\n" + persona.get("signature", "")
    html = (
        "<!doctype html><html><body style='font-family:-apple-system,Segoe UI,sans-serif;font-size:14px;line-height:1.55;color:#1f2937;max-width:600px'>"
        + "".join(f"<p>{p}</p>" for p in body_full.strip().split("\n\n"))
        + "</body></html>"
    )
    payload = {
        "from": f'{persona["from_name"]} <{persona["from_addr"]}>',
        "to":   [prospect["email"]],
        "reply_to": persona.get("reply_to", persona["from_addr"]),
        "subject":  subject,
        "text":     body_full,
        "html":     html,
        "headers": {
            "Message-ID":            msg_id,
            "List-Unsubscribe":      f"<mailto:{persona['from_addr']}?subject=unsubscribe>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
        "tags": [
            {"name": "persona", "value": persona["slug"]},
            {"name": "prospect_id", "value": str(prospect.get("id", ""))},
        ],
    }
    try:
        with httpx.Client(timeout=20) as r:
            resp = r.post(RESEND_API,
                          headers={"Authorization": f"Bearer {api_key}"},
                          json=payload)
        if resp.status_code in (200, 202):
            return {"ok": True, "resend_id": resp.json().get("id"), "message_id": msg_id}
        return {"ok": False, "error": f"{resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def log_send(c: httpx.Client, run: dict, step_n: int, persona: dict, prospect: dict,
             subject: str, outcome: dict) -> None:
    row = {
        "run_id":       run["id"],
        "step_n":       step_n,
        "persona_slug": persona["slug"],
        "from_addr":    persona["from_addr"],
        "to_addr":      prospect["email"],
        "subject":      subject,
        "resend_id":    outcome.get("resend_id"),
        "message_id":   outcome.get("message_id"),
        "delivered":    bool(outcome.get("ok")),
        "error":        outcome.get("error"),
    }
    c.post("/send_log", json=row)


def advance_run(c: httpx.Client, run: dict, step_completed: int,
                next_step_delay_days: int | None) -> None:
    if next_step_delay_days is None:
        # No more steps
        c.patch(f"/runs?id=eq.{run['id']}",
                json={"status": "completed", "current_step": step_completed})
        return
    next_at = dt.datetime.utcnow() + dt.timedelta(days=next_step_delay_days)
    # Jitter ±2h to avoid clock-aligned bursts
    next_at += dt.timedelta(minutes=random.randint(-120, 120))
    c.patch(f"/runs?id=eq.{run['id']}",
            json={"current_step": step_completed + 1,
                  "next_send_at": next_at.isoformat() + "Z"})


# ─── tick / enqueue / status ───────────────────────────────────────────────

def tick() -> None:
    url, key = load_supabase()
    with supa(url, key) as c:
        runs = fetch_due_runs(c)
        if not runs:
            print("no due runs")
            return
        # Cache per-profile config + today's send log to avoid re-fetching per run
        profile_cache: dict[str, dict] = {}
        today_log_cache: list[dict] | None = None
        for run in runs:
            # Pull the sequence (to learn the profile + step structure)
            seq_id = run["sequence_id"]
            seq_resp = c.get(f"/sequences?id=eq.{seq_id}&select=profile_slug,name").json()
            if not seq_resp:
                continue
            profile_slug = seq_resp[0]["profile_slug"]
            if profile_slug not in profile_cache:
                profile_cache[profile_slug] = fetch_profile_config(c, profile_slug)
            profile_config = profile_cache[profile_slug]

            step_n = run["current_step"]
            step = fetch_sequence_step(c, seq_id, step_n)
            if not step:
                # No step at this n → done
                c.patch(f"/runs?id=eq.{run['id']}", json={"status": "completed"})
                continue
            subject = step.get("inline_subject") or (step.get("variants") or {}).get("subject")
            body    = step.get("inline_body")    or (step.get("variants") or {}).get("body")
            if not subject or not body:
                print(f"  ! run {run['id']} step {step_n}: no subject/body")
                continue

            if today_log_cache is None:
                today_log_cache = fetch_today_log(c, profile_slug)
            persona = (next((p for p in profile_config["personas"] if p["slug"] == step.get("forced_persona")), None)
                       if step.get("forced_persona") else
                       pick_persona(profile_config, today_log_cache))
            if not persona:
                print(f"  ! run {run['id']} step {step_n}: no persona available (over quota / cooldown)")
                continue

            prospect = fetch_prospect(c, run["prospect_id"])
            api_key  = get_api_key(profile_slug)
            if not api_key:
                print(f"  ! no Resend key for {profile_slug}")
                continue

            outcome = send_via_resend(api_key, persona, prospect, subject, body)
            log_send(c, run, step_n, persona, prospect, subject, outcome)

            print(f"  [{persona['slug']:7}] step {step_n} → {prospect['email']:30}"
                  f"  {'SENT '+(outcome.get('resend_id') or '') if outcome['ok'] else 'FAIL '+outcome.get('error','')}")

            # Track in cache so next persona pick respects this send
            today_log_cache.append({"persona_slug": persona["slug"],
                                    "sent_at": dt.datetime.utcnow().isoformat() + "Z"})

            if outcome["ok"]:
                max_step = fetch_max_step(c, seq_id)
                if step_n >= max_step:
                    advance_run(c, run, step_n, None)
                else:
                    # Next step's delay
                    next_step = fetch_sequence_step(c, seq_id, step_n + 1)
                    delay = next_step.get("delay_days", 3) if next_step else 3
                    advance_run(c, run, step_n, delay)


def enqueue(sequence_slug: str, prospect_email: str) -> None:
    url, key = load_supabase()
    with supa(url, key) as c:
        # Lookup sequence
        r = c.get(f"/sequences?slug=eq.{sequence_slug}&select=id,profile_slug")
        rows = r.json()
        if not rows:
            sys.exit(f"sequence '{sequence_slug}' not found")
        seq = rows[0]
        # Ensure prospect
        r = c.post(f"/prospects?on_conflict=profile_slug,email",
                   json={"profile_slug": seq["profile_slug"], "email": prospect_email})
        prospect = r.json()[0] if r.status_code in (200, 201) else None
        if not prospect:
            r = c.get(f"/prospects?profile_slug=eq.{seq['profile_slug']}&email=eq.{prospect_email}")
            prospect = r.json()[0]
        # Create run
        r = c.post("/runs?on_conflict=sequence_id,prospect_id",
                   json={"sequence_id": seq["id"], "prospect_id": prospect["id"],
                         "status": "queued", "current_step": 1,
                         "next_send_at": dt.datetime.utcnow().isoformat() + "Z"})
        print(f"queued run for {prospect_email}: {r.json()[0]['id']}")


def status_cmd() -> None:
    url, key = load_supabase()
    with supa(url, key) as c:
        for stat in ("queued", "running", "paused_replied", "paused_bounced", "completed", "cancelled"):
            r = c.get(f"/runs?status=eq.{stat}&select=count", headers={"Prefer": "count=exact"})
            cnt = r.headers.get("content-range", "?/?").split("/")[-1]
            print(f"  runs · {stat:18} {cnt}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick")
    p_eq = sub.add_parser("enqueue"); p_eq.add_argument("sequence_slug"); p_eq.add_argument("prospect_email")
    sub.add_parser("status")
    args = ap.parse_args()
    if args.cmd == "tick":     tick()
    elif args.cmd == "enqueue": enqueue(args.sequence_slug, args.prospect_email)
    elif args.cmd == "status":  status_cmd()
    return 0


if __name__ == "__main__":
    sys.exit(main())
