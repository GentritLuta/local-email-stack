# -*- coding: utf-8 -*-
"""clarity_gate.py — the standing clarity gate for the funnel.

THE MEASURE (set by the operator, 2026-06-24): the first email of every campaign
must make a cold stranger instantly understand BOTH (1) exactly what the business
does, and (2) exactly what the email wants them to do. If either is unclear, the
first email does not go live.

How it is enforced:
  - `check(profile)` judges EVERY step-1 variant (the variant row + the inline A/B
    alternative) with the local Claude CLI, as a cold stranger who sees only the
    email, and records ONE campaign-level verdict in clarity_checks. passed = every
    variant passes. The verdict is keyed by a combined hash of all step-1 copy, so
    any edit to any variant invalidates the pass.
  - `is_clear(profile)` is the GATE the sender calls before sending step 1: True only
    if the campaign's CURRENT step-1 copy has a recorded passing verdict.
  - Kickoff (onboard-pipeline) runs `check` on the generated step 1 so a new client
    has a verdict from day one and its first email cannot go live unclear.
  - LES-clarity-gate reruns `check --all` so any copy change is re-judged + alerts.

CLI:
  py sequences/clarity_gate.py check --all            # judge every active campaign's step 1
  py sequences/clarity_gate.py check --profile aureon
  py sequences/clarity_gate.py status                 # latest verdicts
  py sequences/clarity_gate.py gate                    # would each campaign's step 1 send?
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess, sys, tempfile, shutil
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
_CLAUDE_EXE = r"D:\npm-global\node_modules\@anthropic-ai\claude-code\bin\claude.exe"
CLAUDE_CMD = os.environ.get("CLAUDE_CLI") or (_CLAUDE_EXE if os.path.exists(_CLAUDE_EXE) else r"D:\npm-global\claude.cmd")
PROJECT = "ccmqkljsjiuavpydbkva"
SQL_URL = f"https://api.supabase.com/v1/projects/{PROJECT}/database/query"


def _env(path: Path) -> dict:
    e = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1); e[k.strip()] = v.strip().strip('"').strip("'")
    return e


_SUPA = _env(REPO / "sequences" / "supabase.env")
_H = {"Authorization": f"Bearer {_SUPA.get('SUPABASE_ACCESS_TOKEN','')}",
      "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 Chrome/123"}


def _sql(q: str) -> list:
    req = urllib.request.Request(SQL_URL, data=json.dumps({"query": q}).encode(), method="POST", headers=_H)
    return json.loads(urllib.request.urlopen(req, timeout=40).read())


def _q(s: str) -> str:
    return (s or "").replace("'", "''")


def copy_hash(copies: list) -> str:
    """Combined hash of every step-1 variant (variant A + inline B), order-independent.
    Any edit to any variant changes the hash, so the recorded pass no longer counts."""
    parts = sorted(((s or "") + "\n\n" + (b or "")) for s, b in copies)
    return hashlib.sha256("\n--VARIANT--\n".join(parts).encode("utf-8")).hexdigest()[:16]


def _step1_copy(profile_slug: str) -> list:
    """Every distinct version of a campaign's FIRST email: the variant row plus the
    inline A/B alternative if one is set. Returns [(label, subject, body), ...]."""
    out = []
    for r in _sql(f"SELECT subject, body FROM variants WHERE profile_slug='{_q(profile_slug)}' AND n=1"):
        out.append(("variant", r["subject"], r["body"]))
    for r in _sql("SELECT ss.inline_subject s, ss.inline_body b FROM sequence_steps ss "
                  "JOIN sequences sq ON sq.id=ss.sequence_id "
                  f"WHERE sq.profile_slug='{_q(profile_slug)}' AND ss.step_n=1 AND ss.inline_body IS NOT NULL"):
        if (r.get("b") or "").strip():
            out.append(("inline", r["s"], r["b"]))
    return out


# ─── the judge (local Claude CLI, cold-stranger lens) ────────────────────────

_SYSTEM = (
    "You are a HARSH clarity judge for cold outreach. You are given ONLY the first email of "
    "a sequence (subject + body), judged as a cold stranger who has never heard of this "
    "business and decides in about three seconds whether to keep reading. Two independent, "
    "STRICT calls:\n\n"
    "what_you_do: do the SUBJECT plus the FIRST ONE OR TWO SENTENCES make it unmistakable what "
    "this business does or offers? If the reader must reach the third or fourth paragraph to "
    "learn what the business is, or the subject is a vague label, a single word, or just a name, "
    "what_you_do is FALSE even though the email explains it later. Buried-but-present is a FAIL.\n\n"
    "what_you_want: is there ONE clear action, obvious upfront, that the email wants the reader "
    "to take? Two competing asks, or a vague 'let me know if interested', make this FALSE.\n\n"
    "Be harsh; most cold emails fail. Default each to false unless it is genuinely obvious upfront. "
    "Merge fields like {company} or {greeting} are fine; judge the structure, not the placeholders.\n\n"
    "Calibration:\n"
    "PASS shape: subject 'a seller test for {company}'; body opens 'Straight offer, free. Give me "
    "the main zip you work. For 14 days I run seller outreach into that area and hand you every home "
    "seller lead and listing appointment it produces.' By sentence two you know what they do "
    "(generate seller leads and booked appointments for agents) and what they want (your zip). "
    "what_you_do true, what_you_want true.\n"
    "FAIL shape: subject '{company} rate' (a vague label that says nothing); body opens with a "
    "personal observation then 'Here is something useful either way. Reply with your channel link "
    "and I will send back the exact retainer...' and only reveals the business is a TradingView "
    "trading tool in the fourth paragraph. What they do is buried and the subject is empty of "
    "meaning. what_you_do false.\n\n"
    "Output ONLY a JSON object, no prose:\n"
    '{"what_you_do": bool, "what_you_want": bool, "issues": ["short strings"], '
    '"fix_hint": "one concrete sentence on what to change, or empty if it passes"}'
)


def _judge(subject: str, body: str) -> dict:
    prompt = f"SUBJECT: {subject}\n\nBODY:\n{body}"
    work = tempfile.mkdtemp(prefix="les_clarity_")
    try:
        proc = subprocess.run(
            [CLAUDE_CMD, "-p", "--system-prompt", _SYSTEM,
             "--disallowedTools", "Bash,Read,Glob,Grep,Edit,Write,WebFetch,WebSearch",
             "--setting-sources", "user"],
            input=prompt, capture_output=True, text=True, timeout=150,
            encoding="utf-8", errors="replace", cwd=work,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (proc.stdout or "").strip()
        m = re.search(r"\{[\s\S]*\}", out)
        if not m:
            return None
        d = json.loads(m.group(0))
        wd, ww = bool(d.get("what_you_do")), bool(d.get("what_you_want"))
        return {"what_you_do": wd, "what_you_want": ww, "passed": wd and ww,
                "issues": d.get("issues") or [], "fix_hint": d.get("fix_hint") or ""}
    except Exception as e:
        print(f"  ! judge failed: {e}")
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ─── record + gate (campaign-level: covers every step-1 variant) ─────────────

def check(profile_slug: str, force: bool = False) -> dict:
    """Judge every step-1 variant and upsert ONE campaign-level verdict.
    passed = every variant passes. Returns the verdict, or None if a judge call failed
    (in which case nothing is recorded as passing, so the gate holds).

    Unless force=True, copy whose exact combined hash already has a verdict is NOT
    re-judged (returns the cached verdict). This keeps the scheduled re-check cheap:
    it only spends Claude CLI calls on NEW or EDITED first emails, and keeps a given
    copy's verdict stable rather than re-rolling the judge on every tick."""
    copies = _step1_copy(profile_slug)
    if not copies:
        return None
    h = copy_hash([(s, b) for _, s, b in copies])
    if not force:
        cached = _sql("SELECT passed, what_you_do, what_you_want, issues, fix_hint FROM clarity_checks "
                      f"WHERE profile_slug='{_q(profile_slug)}' AND step_n=1 AND copy_hash='{h}'")
        if cached:
            r = cached[0]
            return {"passed": r["passed"], "what_you_do": r["what_you_do"],
                    "what_you_want": r["what_you_want"], "issues": r.get("issues") or [],
                    "fix_hint": r.get("fix_hint") or "", "variants": len(copies), "cached": True}
    per = []
    for label, subj, body in copies:
        v = _judge(subj, body)
        if v is None:
            return None
        v["label"] = label
        per.append(v)
    passed = all(p["passed"] for p in per)
    wd = all(p["what_you_do"] for p in per)
    ww = all(p["what_you_want"] for p in per)
    fails = [p for p in per if not p["passed"]]
    issues = [f"[{p['label']}] {i}" for p in fails for i in p["issues"]]
    fix_hint = next((f"[{p['label']}] {p['fix_hint']}" for p in fails if p["fix_hint"]), "")
    _sql(
        "INSERT INTO clarity_checks (profile_slug, step_n, copy_hash, passed, what_you_do, "
        "what_you_want, issues, fix_hint, checked_at) VALUES "
        f"('{_q(profile_slug)}', 1, '{h}', {str(passed).lower()}, {str(wd).lower()}, {str(ww).lower()}, "
        f"$j${json.dumps(issues)}$j$::jsonb, $f${fix_hint}$f$, now()) "
        "ON CONFLICT (profile_slug, step_n) DO UPDATE SET copy_hash=EXCLUDED.copy_hash, "
        "passed=EXCLUDED.passed, what_you_do=EXCLUDED.what_you_do, what_you_want=EXCLUDED.what_you_want, "
        "issues=EXCLUDED.issues, fix_hint=EXCLUDED.fix_hint, checked_at=now()")
    return {"passed": passed, "what_you_do": wd, "what_you_want": ww, "issues": issues,
            "fix_hint": fix_hint, "variants": len(copies)}


def is_clear(profile_slug: str) -> bool:
    """THE GATE. True only if the campaign's CURRENT step-1 copy (all variants) has a
    recorded passing verdict. Any copy edit changes the combined hash -> gate holds."""
    copies = _step1_copy(profile_slug)
    if not copies:
        return False
    h = copy_hash([(s, b) for _, s, b in copies])
    rows = _sql(f"SELECT passed FROM clarity_checks WHERE profile_slug='{_q(profile_slug)}' "
                f"AND step_n=1 AND copy_hash='{h}'")
    return bool(rows and rows[0].get("passed"))


def _active_profiles() -> list:
    rows = _sql("SELECT DISTINCT v.profile_slug FROM variants v JOIN profiles p ON p.slug=v.profile_slug "
                "WHERE v.n=1 AND (p.config->>'active')='true' ORDER BY v.profile_slug")
    return [r["profile_slug"] for r in rows]


def gate_status() -> dict:
    """{profile_slug: is_clear} for every active campaign. The sender reads this once per tick."""
    return {p: is_clear(p) for p in _active_profiles()}


def _alert_email(failing: list) -> None:
    """Email info@ when the set of clarity-failing active campaigns CHANGES. Dedupes via a
    small state file so a persistent hold is not re-mailed on every scheduled tick."""
    state_f = REPO / "out" / ".clarity_alert_state.json"
    slugs = sorted(f["profile_slug"] for f in failing)
    try:
        prev = json.loads(state_f.read_text(encoding="utf-8")) if state_f.exists() else []
    except Exception:
        prev = []
    if slugs == prev:
        return
    state_f.parent.mkdir(exist_ok=True)
    state_f.write_text(json.dumps(slugs), encoding="utf-8")
    if slugs:
        lines = ["The clarity gate is HOLDING the first email on these campaigns. A cold reader "
                 "cannot instantly tell what you do or what you want, so step 1 will not send:", ""]
        for f in failing:
            lines.append(f"  - {f['profile_slug']}: {f.get('fix_hint') or 'run clarity_gate.py status for details'}")
        lines += ["", "Fix the copy, then it re-checks automatically (or force it now: "
                  "py sequences/clarity_gate.py check --profile <slug> --force).",
                  "", "All other campaigns are clear and sending normally."]
        subject = f"[clarity gate] {len(slugs)} campaign(s) holding step 1"
    else:
        lines = ["All campaign first emails pass the clarity gate again. Step 1 is sending normally."]
        subject = "[clarity gate] all campaigns clear again"
    sender = REPO / "sequences" / "hostinger-smtp-send.py"
    try:
        subprocess.run([sys.executable, str(sender), "--to", "info@aureonglobal.de",
                        "--subject", subject, "--body", "\n".join(lines)],
                       capture_output=True, text=True, timeout=60)
        print(f"  alert emailed to info@ ({len(slugs)} holding)")
    except Exception as e:
        print(f"  ! alert email failed: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--all", action="store_true"); c.add_argument("--profile")
    c.add_argument("--force", action="store_true", help="re-judge even if the copy hash already has a verdict")
    c.add_argument("--alert", action="store_true", help="email info@ if the failing-campaign set changed")
    sub.add_parser("status")
    g = sub.add_parser("gate"); g.add_argument("--profile")
    a = ap.parse_args()

    if a.cmd == "check":
        profs = _active_profiles() if a.all else ([a.profile] if a.profile else [])
        if not profs:
            print("nothing to check (use --all or --profile X)"); return 1
        fails = 0
        for p in profs:
            v = check(p, force=a.force)
            if v is None:
                print(f"  {p:14} JUDGE UNAVAILABLE -> not recorded as passing (gate will hold)"); fails += 1; continue
            tag = "PASS" if v["passed"] else "FAIL"
            print(f"  [{tag}] {p:14} {v['variants']} variant(s)  do={v['what_you_do']} want={v['what_you_want']}")
            if not v["passed"]:
                fails += 1
                for i in v["issues"]:
                    print(f"        - {i}")
                if v["fix_hint"]:
                    print(f"        fix: {v['fix_hint']}")
        print(f"\n{len(profs)} campaign(s) checked, {fails} need attention")
        if a.alert:
            failing = _sql("SELECT cc.profile_slug, cc.fix_hint FROM clarity_checks cc "
                           "JOIN profiles p ON p.slug=cc.profile_slug "
                           "WHERE cc.step_n=1 AND cc.passed=false AND (p.config->>'active')='true' "
                           "ORDER BY cc.profile_slug")
            _alert_email(failing)
        return 1 if fails else 0

    if a.cmd == "status":
        for r in _sql("SELECT profile_slug, passed, what_you_do, what_you_want, fix_hint, checked_at "
                      "FROM clarity_checks WHERE step_n=1 ORDER BY profile_slug"):
            tag = "PASS" if r["passed"] else "FAIL"
            line = (f"  [{tag}] {r['profile_slug']:14} do={r['what_you_do']} want={r['what_you_want']} "
                    f"({str(r['checked_at'])[:16]})")
            if not r["passed"] and r["fix_hint"]:
                line += f"  fix: {r['fix_hint']}"
            print(line)
        return 0

    if a.cmd == "gate":
        if a.profile:
            ok = is_clear(a.profile)
            print(f"{a.profile}: step 1 would {'SEND (clarity passed)' if ok else 'HOLD (clarity not passed for current copy)'}")
        else:
            for p, ok in gate_status().items():
                print(f"  {p:14} {'SEND' if ok else 'HOLD'}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
