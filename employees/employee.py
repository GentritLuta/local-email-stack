"""Run an AI employee for one shift.

    python employee.py run <role> [--task "optional explicit assignment"] [--dry]
    python employee.py roles            # list available roles

The employee reads its charter + its memory, decides what to do (or does the
task you handed it), researches/writes inside its own sandbox, and drops a
finished work product into state/<role>/pending/ for your review. It cannot
ship anything itself — that is review.py's job, after you approve.
"""
import argparse
import json
import re
import sys

import _lib as L

META_START = "<<<EMPLOYEE_META"
META_END = "EMPLOYEE_META>>>"

_SYSTEM = (
    "You are an autonomous employee working a daily shift for your operator "
    "(Gentrit, info@aureonglobal.de). You were given a ROLE CHARTER and your own "
    "MEMORY from previous shifts. Use your judgment: you do not need step-by-step "
    "instructions. Do real work using your tools (web research, reading and writing "
    "files in this folder). Plain human prose, no em dashes, no filler. "
    "HARD RULE: you never contact third parties, never send email, never publish, "
    "never run send scripts. You only produce work and PROPOSE actions; your "
    "operator approves before anything ships. "
    "End your reply with a metadata block, exactly:\n"
    f"{META_START}\n"
    '{"title": "<= 70 char title of today\'s work product", '
    '"summary": "2-3 sentence operator-facing summary of what you did and found", '
    '"push_actions": [{"type": "note|email|publish|task", "desc": "one line", '
    '"to": "(email actions only) recipient address", "subject": "(email only)", '
    '"body": "(email only) the full message you propose to send"}], '
    '"memory_update": "short note to carry into your next shift"}\n'
    f"{META_END}\n"
    "Everything BEFORE that block is the finished work product, in clean markdown. "
    "CRITICAL: only your FINAL message is saved. It MUST contain the COMPLETE work "
    "product in full, even if you already described findings while researching. Never "
    "write 'see above', 'as described', or 'complete above' - restate the entire work "
    "product in this final message, then the metadata block. "
    "When you propose an email, fill to/subject/body completely so your operator can "
    "approve and send it in one click. You still never send it yourself."
)


def _build_prompt(role: str, charter: str, mem: dict, task: str | None) -> str:
    recent = mem.get("runs", [])[-5:]
    data_dir = L.role_paths(role)["data"]
    orders = L.load_standing_orders(role).strip()
    routine = L.load_routine(role).strip()
    parts = [
        "# YOUR ROLE CHARTER\n", charter, "\n",
        "# STANDING ORDERS (permanent, from your operator - follow EVERY one, "
        "every shift; these exist because of past corrections, never repeat a "
        "mistake they cover)\n" + (orders or "(none yet)") + "\n",
        "# YOUR DAILY ROUTINE (the recurring work you run each shift, in order)\n"
        + (routine or "(no routine set yet)") + "\n",
        "# YOUR MEMORY (carry-over from previous shifts)\n",
        "Standing context: " + (mem.get("standing_context") or "(none yet)"),
        "\nRecent shifts:\n" + (json.dumps(recent, ensure_ascii=False, indent=2)
                                if recent else "(this is your first shift)"),
        f"\n\n# YOUR DATA DROP FOLDER\n{data_dir}\n"
        "At the start of each shift, list and READ any files the operator has placed "
        "here (statements, invoices, documents, exports) with your Read/Glob tools, and "
        "use them. If it is empty, note what you still need.",
        f"\n\n# TODAY\nDate: {L.today()}.",
    ]
    if task:
        parts.append(f"\nYour operator handed you this explicit assignment:\n{task}")
    else:
        parts.append("\nNo explicit assignment today. Decide what is most valuable "
                     "to do under your charter, given your memory, and do it.")
    parts.append("\n\nDo the work now, then produce your work product and the "
                 "metadata block.")
    return "\n".join(parts)


def _parse_meta(out: str):
    """Split raw stdout into (body, meta_dict)."""
    idx = out.find(META_START)
    if idx == -1:
        return out.strip(), {"title": "Untitled work product",
                             "summary": "(model did not emit a metadata block)",
                             "push_actions": [], "memory_update": ""}
    body = out[:idx].strip()
    tail = out[idx + len(META_START):]
    tail = tail.split(META_END)[0]
    m = re.search(r"\{[\s\S]*\}", tail)
    meta = {}
    if m:
        try:
            meta = json.loads(m.group(0))
        except Exception:
            meta = {}
    meta.setdefault("title", "Untitled work product")
    meta.setdefault("summary", "")
    meta.setdefault("push_actions", [])
    meta.setdefault("memory_update", "")
    return body, meta


_VERIFY_SYSTEM = (
    "You are the same employee, silently reviewing your OWN draft hard before it reaches "
    "your operator. Check it against your role charter and your standing orders, and fix "
    "every shortfall: anything missing, any unsupported claim, anything that violates a "
    "standing order, weak quality, wrong format, or a mistake a standing order says to "
    "never make again.\n"
    "OUTPUT CONTRACT (critical): your message body must be ONLY the clean, final work "
    "product, exactly what the operator should receive. NO review commentary, NO 'I "
    "reviewed', NO 'I fixed X', NO list of changes or shortfalls, NO mention that a review "
    "happened. The body is the finished deliverable alone. If you want to record what you "
    "changed, put it in the metadata 'memory_update' field, never in the body. Then the "
    "metadata block exactly:\n"
    f"{META_START}\n"
    '{"title": "...", "summary": "...", "push_actions": [{"type": "...", "desc": "...", '
    '"to": "", "subject": "", "body": ""}], "memory_update": "..."}\n'
    f"{META_END}\n"
    "If the draft already fully meets the charter and orders, return it unchanged (still "
    "clean, no commentary)."
)


def _self_verify(role, charter, body, meta, sandbox, rounds=2):
    """Self-critique loop: the employee improves its own draft until it converges
    or the round cap is hit. Bounded so cost stays sane; the operator's review
    loop is the ultimate 'until it works'."""
    orders = L.load_standing_orders(role).strip()
    for i in range(rounds):
        prompt = (f"# YOUR ROLE CHARTER\n{charter}\n\n"
                  f"# YOUR STANDING ORDERS\n{orders or '(none)'}\n\n"
                  f"# YOUR DRAFT WORK PRODUCT\n{body}\n\n"
                  "Review and improve this draft per your instruction, then return the "
                  "full work product and metadata block.")
        out = L.ask_claude(_VERIFY_SYSTEM, prompt, cwd=sandbox)
        nb, nm = _parse_meta(out)
        if len(nb) < 200:
            break  # bad review output; keep the current draft
        converged = abs(len(nb) - len(body)) < 40 and nb[:200] == body[:200]
        body, meta = nb, nm
        print(f"        self-review round {i + 1} done"
              + (" (converged)" if converged else ""))
        if converged:
            break
    return body, meta


def _do_shift(role: str, task: str | None, dry: bool, verify: bool = True):
    """Work one assignment (or self-directed) and queue one work product."""
    charter = L.load_charter(role)
    mem = L.load_memory(role)
    paths = L.role_paths(role)
    sandbox = paths["base"] / "workspace"
    sandbox.mkdir(parents=True, exist_ok=True)

    print(f"[{role}] starting shift ({L.today()}) - {task or 'self-directed'}")
    prompt = _build_prompt(role, charter, mem, task)
    out = L.ask_claude(_SYSTEM, prompt, cwd=sandbox)
    body, meta = _parse_meta(out)

    # Self-heal: if the final message dropped the work product (model narrated it
    # mid-research and only summarized at the end), demand the full text once more.
    if len(body) < 300:
        print(f"[{role}] body too short ({len(body)} chars); requesting full restate...")
        retry_prompt = (prompt + "\n\nYOUR LAST REPLY DID NOT CONTAIN THE WORK PRODUCT. "
                        "Output the COMPLETE work product now, in full, as this message, "
                        "then the metadata block. Do not refer to anything 'above'.")
        out = L.ask_claude(_SYSTEM, retry_prompt, cwd=sandbox)
        body2, meta2 = _parse_meta(out)
        if len(body2) > len(body):
            body, meta = body2, meta2

    if verify:
        body, meta = _self_verify(role, charter, body, meta, sandbox)

    stamp = L.now_stamp()
    item = {
        "role": role,
        "created": stamp,
        "date": L.today(),
        "task": task or "(self-directed)",
        "title": meta["title"],
        "summary": meta["summary"],
        "push_actions": meta["push_actions"],
        "memory_update": meta["memory_update"],
        "version": 1,
        "body": body,
        "revision_log": [],
    }
    dest = paths["pending"] / f"{stamp}.json"
    dest.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[{role}] produced: {meta['title']}")
    print(f"        queued for review -> {dest}")
    return dest


# ─── task inbox (hand an employee specific assignments) ─────────────────────

_MAX_INBOX_PER_SHIFT = 8


def _inbox_path(role: str):
    return L.role_paths(role)["base"] / "inbox.txt"


def _pending_tasks(role: str):
    p = _inbox_path(role)
    if not p.exists():
        return []
    out = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        s = line.strip()
        if not s or s.startswith("#") or s.lower().startswith("done "):
            continue
        out.append((i, s))
    return out


def _mark_done(role: str, idxs):
    p = _inbox_path(role)
    lines = p.read_text(encoding="utf-8").splitlines()
    for i in idxs:
        lines[i] = f"done {L.now_stamp()}  {lines[i].strip()}"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assign(role: str, task: str) -> int:
    L.load_charter(role)  # validates role exists
    p = _inbox_path(role)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(task.strip() + "\n")
    print(f"queued for {role}: {task.strip()}")
    print(f"(runs on {role}'s next shift, or now with: python employee.py run {role})")
    return 0


def run(role: str, task: str | None, dry: bool, verify: bool = True) -> int:
    L.load_charter(role)  # validate early
    if task:
        _do_shift(role, task, dry, verify)
        return 0
    pend = _pending_tasks(role)
    if pend:
        batch = pend[:_MAX_INBOX_PER_SHIFT]
        for _, t in batch:
            _do_shift(role, t, dry, verify)
        _mark_done(role, [i for i, _ in batch])
        extra = len(pend) - len(batch)
        print(f"[{role}] processed {len(batch)} inbox task(s)." +
              (f" {extra} left for next shift." if extra else ""))
    else:
        _do_shift(role, None, dry, verify)
    return 0


def set_send(role: str, on: bool) -> int:
    L.load_charter(role)
    cfg = L.set_role_config(role, can_send=on)
    state = "ENABLED" if on else "disabled"
    print(f"[{role}] third-party auto-send {state}. config: {cfg}")
    if on:
        print("  On approval, fully-specified email actions (to/subject/body) will "
              "be sent. Everything still passes your review first.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("role")
    r.add_argument("--task", default=None)
    r.add_argument("--dry", action="store_true")
    r.add_argument("--no-verify", action="store_true",
                   help="skip the self-review pass (faster, lower quality)")
    sub.add_parser("roles")
    a = sub.add_parser("assign")
    a.add_argument("role")
    a.add_argument("task")
    o = sub.add_parser("order", help="append a permanent standing order")
    o.add_argument("role")
    o.add_argument("text")
    rt = sub.add_parser("routine", help="append a recurring routine item")
    rt.add_argument("role")
    rt.add_argument("text")
    es = sub.add_parser("enable-send")
    es.add_argument("role")
    ds = sub.add_parser("disable-send")
    ds.add_argument("role")
    args = ap.parse_args()

    if args.cmd == "roles":
        print("Available roles:")
        for name in L.list_roles():
            cfg = L.load_role_config(name)
            tag = "  [can send to 3rd parties]" if cfg.get("can_send") else ""
            print(f"  - {name}{tag}")
        return 0
    if args.cmd == "run":
        return run(args.role, args.task, args.dry, verify=not args.no_verify)
    if args.cmd == "assign":
        return assign(args.role, args.task)
    if args.cmd == "order":
        L.load_charter(args.role)
        L.append_standing_order(args.role, args.text)
        print(f"[{args.role}] standing order added (permanent): {args.text}")
        return 0
    if args.cmd == "routine":
        L.load_charter(args.role)
        L.append_routine(args.role, args.text)
        print(f"[{args.role}] routine item added: {args.text}")
        return 0
    if args.cmd == "enable-send":
        return set_send(args.role, True)
    if args.cmd == "disable-send":
        return set_send(args.role, False)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
