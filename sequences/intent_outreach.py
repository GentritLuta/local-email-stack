"""intent_outreach.py — turn routed seller-intent leads into ready-to-send outreach.

Reads the scan artifacts from intent_signals.py and produces actionable, copy-ready
outreach per channel, using the local Claude CLI (free, Max plan) with humane,
distress-sensitive templates as a fallback so it always produces usable copy:

  direct_mail leads (property addresses)  -> a mail-merge CSV: one humane letter per
                                             address (lead with a free home-value offer,
                                             never reference how the owner was found).
  social leads (reply_or_dm / funnel)     -> a markdown file: each public post URL with
                                             a drafted, helpful, non-salesy reply.

Homeowners are never cold-emailed. Letters go by mail; replies are posted/DM'd by the
agent. The drafts are the agent's to send.

USAGE
  py sequences/intent_outreach.py make --profile <agent> --metro "Austin, TX" \
       --agent-name "Jane Doe" --phone "512-555-0100" --funnel-url "https://..."
  py sequences/intent_outreach.py selftest      # offline, no CLI
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "out" / "intent"

SOCIAL_CHANNELS = {"reply_or_dm", "optin_funnel", "agent_follow_up"}


# ─── Claude CLI (free, Max plan) — mirrors reply-autodraft.py sandbox recipe ──

def _resolve_claude() -> Optional[str]:
    """Find claude.exe (the .cmd shim fails with WinError 2 under subprocess)."""
    cand = os.environ.get("CLAUDE_CLI")
    if cand and Path(cand).exists() and cand.lower().endswith(".exe"):
        return cand
    for p in (r"D:\npm-global\node_modules\@anthropic-ai\claude-code\bin\claude.exe",
              os.path.expandvars(r"%APPDATA%\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe"),
              r"D:\npm-global\claude.exe"):
        if Path(p).exists():
            return p
    return shutil.which("claude.exe")


def _scrub_dashes(text: str) -> str:
    t = text.replace(" — ", ". ").replace(" – ", ". ").replace("—", ", ").replace("–", ", ")
    return re.sub(r"\.\s*\.", ".", t).strip()


def _claude(system: str, prompt: str, timeout: int = 150) -> Optional[str]:
    exe = _resolve_claude()
    if not exe:
        return None
    workdir = tempfile.mkdtemp(prefix="les_intent_draft_")
    try:
        proc = subprocess.run(
            [exe, "-p", "--system-prompt", system,
             "--disallowedTools", "Bash,Read,Glob,Grep,Edit,Write,WebFetch,WebSearch",
             "--setting-sources", "user"],
            input=prompt, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", cwd=workdir,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        print(f"  ! claude CLI error: {str(e)[:120]}")
        return None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if proc.returncode != 0:
        print(f"  ! claude CLI exit {proc.returncode}: {(proc.stderr or '')[:160]}")
        return None
    text = re.sub(r"^Warning: no stdin data received.*?\n", "",
                  (proc.stdout or "").strip(), flags=re.I).strip()
    return _scrub_dashes(text) if text else None


# ─── templates (fallback + the basis the CLI polishes) ───────────────────────

def directmail_letter(address: str, metro: str, agent_name: str,
                      phone: str, funnel_url: str) -> str:
    return (
        f"Dear Homeowner,\n\n"
        f"My name is {agent_name}, a local real estate agent here in {metro}. I am writing "
        f"to homeowners in the neighborhood with a simple, no-pressure offer.\n\n"
        f"If you have ever wondered what your home at {address} could be worth in today's "
        f"market, I would be glad to put together a free, no-obligation estimate for you. "
        f"There is no cost and no commitment. Just clear information, so you can decide what "
        f"is right for you on your own timeline.\n\n"
        f"You can get your free home value estimate at {funnel_url}, or reply to this letter "
        f"or call me directly at {phone}.\n\n"
        f"Whatever you decide, I wish you and your family all the best.\n\n"
        f"Warm regards,\n{agent_name}\n{phone}")


def social_reply(title: str, metro: str, agent_name: str, funnel_url: str) -> str:
    return (
        f"Hi, I am {agent_name}, a local agent here in {metro}. Happy to help, no pressure "
        f"at all. If it is useful, you can get a free home value estimate here: {funnel_url}. "
        f"Feel free to DM me with any questions, glad to point you in the right direction.")


_MAIL_SYSTEM = (
    "You are a warm, plain-spoken assistant writing a short direct-mail letter for a local "
    "real estate agent to a homeowner. HARD RULES: never use an em-dash or en-dash, use a "
    "period or comma. Never mention foreclosure, divorce, probate, debt, distress, or how "
    "the homeowner was found. Lead with a free, no-pressure home value estimate. Be humane "
    "and respectful, never salesy or predatory. No emojis, no corporate filler. Output only "
    "the letter body.")

_SOCIAL_SYSTEM = (
    "You are helping a local real estate agent reply to a PUBLIC post where someone asked for "
    "help selling or for an agent. Write a short, genuinely helpful, non-salesy reply that "
    "responds to what they said and offers a free, no-pressure home value estimate. HARD "
    "RULES: never use an em-dash or en-dash. No hype, no emojis. Sound like a real helpful "
    "human, not an ad. Under 70 words. Output only the reply.")


# ─── load leads ──────────────────────────────────────────────────────────────

def _load_leads(profile_slug: str) -> list[dict]:
    rows: list[dict] = []
    for p in sorted(OUT_DIR.glob(f"{profile_slug}__*.signals.json")):
        try:
            rows.extend((json.loads(p.read_text(encoding="utf-8")).get("rows") or []))
        except Exception:
            continue
    return rows


# ─── build outreach ──────────────────────────────────────────────────────────

def make(profile_slug: str, metro: str, agent_name: str, phone: str,
         funnel_url: str, limit: int = 15, use_cli: bool = True) -> dict:
    rows = _load_leads(profile_slug)
    if not rows:
        print(f"  no leads in out/intent/{profile_slug}__*.signals.json (run intent_signals first)")
        return {"profile": profile_slug, "directmail": 0, "social": 0}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    dm = [r for r in rows if r.get("channel") == "direct_mail" and r.get("lead_label")]
    social = [r for r in rows if r.get("channel") in SOCIAL_CHANNELS][:limit]

    # Direct mail: one polished letter template (CLI once), mail-merged per address.
    letter_tpl = None
    if use_cli and dm:
        base = directmail_letter("{ADDRESS}", metro, agent_name, phone, funnel_url)
        letter_tpl = _claude(_MAIL_SYSTEM,
            f"Polish this letter. Keep the placeholder {{ADDRESS}} exactly as is so it can be "
            f"mail-merged. Keep it under 130 words.\n\n{base}")
        if letter_tpl and "{ADDRESS}" not in letter_tpl:
            letter_tpl = None  # CLI dropped the merge field; fall back to template
    dm_path = OUT_DIR / f"{profile_slug}_directmail.csv"
    dm_count = 0
    if dm:
        seen = set()
        with dm_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["mailing_address", "metro", "signal", "score", "source_url", "letter"])
            for r in sorted(dm, key=lambda x: float(x.get("score") or 0), reverse=True):
                addr = (r.get("lead_label") or "").strip()
                if not addr or addr.lower() in seen:
                    continue
                seen.add(addr.lower())
                letter = (letter_tpl.replace("{ADDRESS}", addr) if letter_tpl
                          else directmail_letter(addr, metro, agent_name, phone, funnel_url))
                w.writerow([addr, r.get("metro", ""), r.get("signal_id", ""),
                            r.get("score", ""), (r.get("evidence_url", "") or "").split("#")[0],
                            letter])
                dm_count += 1

    # Social: a per-post drafted reply.
    social_path = OUT_DIR / f"{profile_slug}_social_outreach.md"
    social_count = 0
    if social:
        lines = [f"# Social seller-outreach drafts — {profile_slug} ({metro})", ""]
        for r in sorted(social, key=lambda x: float(x.get("score") or 0), reverse=True):
            title = (r.get("lead_label") or "post").strip()
            url = r.get("evidence_url", "")
            draft = None
            if use_cli:
                draft = _claude(_SOCIAL_SYSTEM,
                    f"The public post: \"{title}\". Metro: {metro}. Agent: {agent_name}. "
                    f"Free home value estimate link: {funnel_url}. Write the reply.")
            draft = draft or social_reply(title, metro, agent_name, funnel_url)
            lines += [f"## {title}", f"- Post: {url}", f"- Channel: {r.get('channel','')}  "
                      f"Score: {r.get('score','')}", "", "Reply:", "", draft, "", "---", ""]
            social_count += 1
        social_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n--- outreach for {profile_slug} ---")
    if dm_count:
        print(f"  {dm_count:4d}  out/intent/{profile_slug}_directmail.csv  (mail-merge: address + letter)")
    if social_count:
        print(f"  {social_count:4d}  out/intent/{profile_slug}_social_outreach.md  (post URL + drafted reply)")
    if not dm_count and not social_count:
        print("  (no direct-mail or social leads to draft)")
    return {"profile": profile_slug, "directmail": dm_count, "social": social_count,
            "cli": bool(_resolve_claude())}


def _selftest() -> int:
    import tempfile as _tf
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  {'OK ' if cond else 'FAIL'} {label}")
        ok = ok and cond

    letter = directmail_letter("123 Main St", "Austin, TX", "Jane Doe", "512-555-0100",
                               "https://hv.example/austin")
    check("letter has address", "123 Main St" in letter)
    check("letter has funnel", "hv.example" in letter)
    check("letter never mentions distress",
          not re.search(r"foreclos|divorce|probate|debt|distress", letter, re.I))
    check("letter has no em-dash", "—" not in letter and "–" not in letter)
    reply = social_reply("recommend a realtor", "Austin, TX", "Jane Doe", "https://hv.example")
    check("reply mentions funnel", "hv.example" in reply)
    check("claude resolver returns str or None", isinstance(_resolve_claude(), (str, type(None))))
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("make", help="build outreach drafts for an agent's leads")
    p.add_argument("--profile", required=True)
    p.add_argument("--metro", required=True)
    p.add_argument("--agent-name", default="your local agent")
    p.add_argument("--phone", default="")
    p.add_argument("--funnel-url", default="https://your-home-value-funnel")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--no-cli", action="store_true", help="use templates only, skip Claude CLI")
    sub.add_parser("selftest")

    args = ap.parse_args()
    if args.cmd == "selftest":
        return _selftest()
    if args.cmd == "make":
        make(args.profile, args.metro, args.agent_name, args.phone, args.funnel_url,
             limit=args.limit, use_cli=not args.no_cli)
        return 0


if __name__ == "__main__":
    sys.exit(main())
