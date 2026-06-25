# -*- coding: utf-8 -*-
"""research-hormozi-magnet.py — AI research call producing the Hormozi Lead Magnet Formula.

Runs the local Claude CLI to synthesize Alex Hormozi's lead-magnet framework
($100M Leads, plus the Value Equation from $100M Offers) into a tight, structured
formula saved to lead-magnets/hormozi-lead-magnet-formula.md. The magnet generator
loads that file as its design brief and scoring rubric, so refreshing this formula
refreshes how every magnet is designed and graded, with no code change.

Usage: py scripts/research-hormozi-magnet.py
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "lead-magnets" / "hormozi-lead-magnet-formula.md"
_CLAUDE_EXE = r"D:\npm-global\node_modules\@anthropic-ai\claude-code\bin\claude.exe"
CLAUDE_CMD = os.environ.get("CLAUDE_CLI") or (_CLAUDE_EXE if os.path.exists(_CLAUDE_EXE) else r"D:\npm-global\claude.cmd")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SYS = (
    "You are a direct-response expert who has studied Alex Hormozi's books $100M Offers and "
    "$100M Leads in depth. Produce an accurate, practical FORMULA for the most effective lead "
    "magnet, grounded strictly in Hormozi's actual frameworks. Do NOT invent concepts he did not "
    "teach, and do NOT pad. The output is a working design brief and grading rubric for an engine "
    "that auto-builds client lead magnets, so it must be tight, concrete, and directly usable. "
    "Plain prose, no em-dashes, no marketing cliches."
)

PROMPT = (
    "Write 'The Hormozi Lead Magnet Formula' as structured markdown with exactly these sections:\n\n"
    "## 1. What a great lead magnet is\n"
    "Hormozi's definition (a complete solution to a narrow problem) and why narrow-and-complete "
    "beats broad-and-partial.\n\n"
    "## 2. The Value Equation\n"
    "State it: Value = (Dream Outcome x Perceived Likelihood of Achievement) / (Time Delay x Effort "
    "and Sacrifice). Then one concrete line per lever on how to maximise or minimise it IN A LEAD MAGNET.\n\n"
    "## 3. The three types\n"
    "Reveal a problem; free sample/trial; one step of a multi-step process. When to use each, with an example.\n\n"
    "## 4. How to build one\n"
    "Hormozi's build steps, in order, as an actionable checklist.\n\n"
    "## 5. The bridge to the paid offer\n"
    "How the magnet must reveal or create the NEXT problem that the client's paid (ideally recurring) "
    "offer solves, so consuming it increases desire for the core offer.\n\n"
    "## 6. Naming\n"
    "Hormozi's rule for naming/headlining a lead magnet (specific, benefit-led, the result named). "
    "Give 2 example title patterns.\n\n"
    "## 7. Scoring rubric\n"
    "A table of 7 to 8 weighted criteria to grade ANY lead magnet from 0 to 10 each (e.g. narrow-and-complete, "
    "dream outcome, perceived likelihood/proof, speed to value, low effort, worth-paying-for, bridge to offer, "
    "name). For each: the criterion, its weight, and one line on what a 10 looks like. End with the pass bar "
    "(what total score means 'ready to ship').\n\n"
    "Be specific and faithful to Hormozi. No fluff."
)


def main() -> int:
    work = tempfile.mkdtemp(prefix="les_hormozi_")
    try:
        proc = subprocess.run(
            [CLAUDE_CMD, "-p", "--system-prompt", SYS,
             "--disallowedTools", "Bash,Read,Glob,Grep,Edit,Write,WebFetch,WebSearch",
             "--setting-sources", "user"],
            input=PROMPT, capture_output=True, text=True, timeout=420,
            encoding="utf-8", errors="replace", cwd=work,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out = (proc.stdout or "").strip()
    out = out.replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ").replace("–", "-")
    if len(out) < 500:
        print("research call returned too little:", out[:300], (proc.stderr or "")[:300])
        return 1
    OUT.write_text(out, encoding="utf-8")
    print(f"saved {OUT.relative_to(REPO)} ({len(out)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
