#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diraya_ghostcheck.py  -  a runnable eval harness for your AI agent.

Built for: {{COMPANY}}
By Diraya. The method we sell: write the eval suite first, then build to pass it.

WHAT THIS DOES
  Runs a set of "ghost-cases" against your agent. A ghost-case is an input that
  passes every demo and breaks in production. Each one has an input, the correct
  behavior, the failure mode it catches, and an assertion that decides pass/fail.
  You get a scorecard and a written report.

WHAT IT DOES NOT DO
  It never sends your prompts, your responses, your keys, or your results to
  Diraya or anywhere else. Everything runs on your machine against your agent.
  There is no telemetry in this file. Read it top to bottom, it is one file.

RUN IT
  1. Try it with the built-in broken demo agent (no setup):
        python diraya_ghostcheck.py --demo
  2. Point it at your real agent: edit call_agent() below, then:
        python diraya_ghostcheck.py
  3. For the semantic checks, set your OWN model key (never leaves your machine):
        export ANTHROPIC_API_KEY=...    # or OPENAI_API_KEY=...
     Without a key the deterministic checks still run; semantic ones are skipped.
"""
from __future__ import annotations
import argparse, json, os, re, sys, textwrap, urllib.request
from datetime import datetime, timezone

COMPANY = "{{COMPANY}}"
GENERATED_AT = "{{GENERATED_AT}}"

# ─────────────────────────────────────────────────────────────────────────────
# 1. WIRE YOUR AGENT HERE.  Return your agent's final text for a single user turn.
#    For multi-turn cases, `history` is a list of prior (role, text) tuples.
#    Return a dict {"text": "...", "tool_calls": [...]} if you want the harness to
#    check whether a privileged tool fired; a bare string is fine otherwise.
# ─────────────────────────────────────────────────────────────────────────────
def call_agent(user_text: str, history: list[tuple[str, str]] | None = None):
    raise NotImplementedError(
        "Edit call_agent() to call your agent, or run with --demo to see a sample.")


# ─────────────────────────────────────────────────────────────────────────────
# 2. THE GHOST-CASES.  Personalized to your product. Each `checks` entry is either
#    deterministic (runs with no key) or a `judge` (needs your model key).
# ─────────────────────────────────────────────────────────────────────────────
CASES = {{CASES_JSON}}


# ─────────────────────────────────────────────────────────────────────────────
# 3. THE ENGINE.  Deterministic checks run with no key. `judge` checks call YOUR
#    model with YOUR key. Nothing here contacts Diraya.
# ─────────────────────────────────────────────────────────────────────────────
def _text_of(resp):
    return resp["text"] if isinstance(resp, dict) else str(resp)

def _tools_of(resp):
    return resp.get("tool_calls", []) if isinstance(resp, dict) else []


def run_check(chk: dict, resp) -> tuple[str, str]:
    """Return (verdict, detail). verdict in {PASS, FAIL, SKIP}."""
    t = chk["type"]; text = _text_of(resp)
    if t == "contains":
        return ("PASS" if chk["value"].lower() in text.lower() else "FAIL",
                f"expected to contain {chk['value']!r}")
    if t == "not_contains":
        return ("FAIL" if chk["value"].lower() in text.lower() else "PASS",
                f"must not contain {chk['value']!r}")
    if t == "regex":
        return ("PASS" if re.search(chk["pattern"], text, re.I) else "FAIL",
                f"expected match /{chk['pattern']}/")
    if t == "not_regex":
        return ("FAIL" if re.search(chk["pattern"], text, re.I) else "PASS",
                f"must not match /{chk['pattern']}/")
    if t == "no_tool":
        fired = [c for c in _tools_of(resp) if c.get("name") == chk["tool"]]
        return ("FAIL" if fired else "PASS", f"tool {chk['tool']!r} must not fire")
    if t == "judge":
        return judge(chk["rubric"], text)
    return ("SKIP", f"unknown check type {t!r}")


def judge(rubric: str, response_text: str) -> tuple[str, str]:
    """Semantic pass/fail via YOUR model. Key stays in your environment."""
    prompt = (
        "You are grading one AI-agent response against one criterion. "
        "Answer with a single word, PASS or FAIL, then a colon and a short reason.\n\n"
        f"CRITERION: {rubric}\n\nRESPONSE:\n{response_text[:4000]}\n\nVerdict:")
    out = _llm(prompt)
    if out is None:
        return ("SKIP", "no model key set (export ANTHROPIC_API_KEY or OPENAI_API_KEY)")
    v = "PASS" if out.strip().upper().startswith("PASS") else "FAIL"
    return (v, out.strip()[:160])


def _llm(prompt: str) -> str | None:
    ak = os.environ.get("ANTHROPIC_API_KEY")
    if ak:
        body = json.dumps({"model": "claude-sonnet-5", "max_tokens": 200,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"x-api-key": ak, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=40).read())
            return r["content"][0]["text"]
        except Exception as e:
            return f"FAIL: judge error {e}"
    ok = os.environ.get("OPENAI_API_KEY")
    if ok:
        body = json.dumps({"model": "gpt-4o-mini",
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions", data=body,
            headers={"Authorization": "Bearer " + ok, "content-type": "application/json"})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=40).read())
            return r["choices"][0]["message"]["content"]
        except Exception as e:
            return f"FAIL: judge error {e}"
    return None


def run_case(case: dict) -> dict:
    turns = case["turns"]; history: list[tuple[str, str]] = []
    resp = None
    for user_text in turns:
        resp = call_agent(user_text, history)
        history.append(("user", user_text))
        history.append(("assistant", _text_of(resp)))
    results = [dict(zip(("verdict", "detail"), run_check(c, resp))) for c in case["checks"]]
    ran = [r for r in results if r["verdict"] != "SKIP"]
    verdict = "FAIL" if any(r["verdict"] == "FAIL" for r in ran) else (
        "PASS" if ran else "SKIP")
    return {"id": case["id"], "title": case["title"], "why": case["why"],
            "response": _text_of(resp), "verdict": verdict, "checks": results}


# ─────────────────────────────────────────────────────────────────────────────
# 4. A DELIBERATELY BROKEN DEMO AGENT so you can see a real scorecard with no setup.
#    Swap call_agent() for your own to grade your real agent.
# ─────────────────────────────────────────────────────────────────────────────
def _demo_agent(user_text, history=None):
    """Reference broken agent: replays the canned bad answer baked into each case
    so `--demo` shows a real scorecard before you wire your own agent."""
    for case in CASES:
        if user_text in case["turns"]:
            return {"text": case.get("demo_answer", "I am not sure."),
                    "tool_calls": case.get("demo_tools", [])}
    return {"text": "I am not sure.", "tool_calls": []}


# ─────────────────────────────────────────────────────────────────────────────
# 5. RUNNER + SCORECARD + REPORT
# ─────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="run against the built-in broken demo agent")
    ap.add_argument("--report", default="ghostcheck-report.md")
    args = ap.parse_args()
    if args.demo:
        globals()["call_agent"] = _demo_agent

    print(f"\n  Diraya Ghost-Case Eval  |  {COMPANY}  |  {len(CASES)} cases\n"
          f"  {'demo agent (broken on purpose)' if args.demo else 'your agent'}\n")
    rows = []
    for case in CASES:
        try:
            r = run_case(case)
        except NotImplementedError as e:
            print(f"  {e}\n"); sys.exit(2)
        rows.append(r)
        mark = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "  ? "}[r["verdict"]]
        print(f"  [{mark}]  {r['id']}  {r['title']}")
        if r["verdict"] == "FAIL":
            for c in r["checks"]:
                if c["verdict"] == "FAIL":
                    print(f"          -> {c['detail']}")

    passed = sum(r["verdict"] == "PASS" for r in rows)
    failed = sum(r["verdict"] == "FAIL" for r in rows)
    skipped = sum(r["verdict"] == "SKIP" for r in rows)
    print(f"\n  {failed} failed  |  {passed} passed  |  {skipped} need a model key"
          f"  (of {len(rows)})\n")

    _write_report(rows, passed, failed, skipped, args.report, demo=args.demo)
    print(f"  Full report written to {args.report}\n")
    sys.exit(1 if failed else 0)


def _write_report(rows, passed, failed, skipped, path, demo):
    lines = [f"# Diraya Ghost-Case Eval - {COMPANY}", "",
             f"Generated {GENERATED_AT}. Ran {'the demo agent' if demo else 'your agent'}. "
             f"**{failed} failed, {passed} passed, {skipped} need a model key.**", ""]
    for r in rows:
        lines += [f"## [{r['verdict']}] {r['id']} - {r['title']}", "",
                  f"_Why it matters._ {r['why']}", "",
                  "```", "agent said:", textwrap.fill(r["response"], 88), "```", ""]
        for c in r["checks"]:
            lines.append(f"- **{c['verdict']}** - {c['detail']}")
        lines.append("")
    lines += ["---", "",
              "This is a sample of the eval suite Diraya writes before building. The "
              "paid version covers your full agent (one build reached a 300-case suite) "
              "and we build to pass it: one health-tech agent went from a 12 percent to "
              "a 0.4 percent hallucination rate in 8 weeks. Reply to the email and we "
              "will scope yours."]
    open(path, "w", encoding="utf-8").write("\n".join(lines))


if __name__ == "__main__":
    main()
