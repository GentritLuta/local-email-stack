# RTX Operator - run the email operation from a local AI

This is the kit that lets a **local model on your RTX machine operate the production VPS**,
steered from your laptop. The chain is:

```
  your laptop  ->  RTX (local model + operator loop)  ->  VPS (the 97 LES tasks / the op)
   (you steer)        (does the routine work, SSHes in)      (sends the mail)
```

It replaces *me* (cloud Claude) for the **routine** running of the operation. It does not
replace me for hard problems - see "Boundaries" below. That distinction is the whole point.

## What each piece is

- `OPERATOR_CHARTER.md` - the operator's standing knowledge and rules. The "instruction set it
  cannot forget." The local model reads this every run.
- `local_model.py` - talks to Ollama on the RTX. Drop-in for the cloud `ask_claude`.
- `vps_monitor.py` - the routine sweep: SSH the VPS, check every task + sends + DB, auto-fix the
  safe known failures (wrong python path, stale one-off failures), escalate the rest, write a brief.
- `setup-rtx.ps1` - one-shot installer on the RTX (Ollama + model + SSH wiring + scheduled sweep).

## Deploy (once, on the RTX)

1. Copy this `rtx-operator/` folder to the RTX (it comes with the stack repo).
2. Copy the VPS SSH key `id_ed25519_hostinger` (and `.pub`) from the laptop's `~/.ssh` into the
   RTX's `~/.ssh`.
3. Open PowerShell in this folder and run:
   ```
   powershell -ExecutionPolicy Bypass -File .\setup-rtx.ps1 -Model qwen2.5-coder:14b
   ```
   It installs Ollama, pulls the model, tests the VPS SSH, and registers `RTX-operator-sweep`
   to run every 60 minutes. Briefs land in `~/aureon-operator-reports`.

## Model (already chosen for your box)

Your RTX is the Hong Kong machine: **RTX 4070, 12 GB VRAM, 31.7 GB RAM**. The verified pick that
already runs there is **`qwen3-coder:30b`** (MoE 30B / 3.3B active, ~19 GB, overflow offloads to
RAM and stays usable; ~25 tok/s). That is the default in this kit. Fallback that fits fully in
12 GB: `qwen2.5-coder:14b`. Ollama + this model are **already installed** by the existing
`C:\Users\bernh\rtx-control\` kit, so `setup-rtx.ps1` here mostly just wires the operator loop.
Change later with `ollama pull <model>` + the `OLLAMA_MODEL` user env var.

## This sits on top of the existing rtx-control kit

You already prepped the RTX for a local agent: `rtx-control/` installed Ollama, `qwen3-coder:30b`,
Open WebUI, and **opencode** (an open-source "Claude Code but local"). This `rtx-operator/` kit adds
the **email-operation-specific layer** on top: the charter, the autonomous VPS sweep, and the
employee-framework swap. Access to the box is Tailscale + SSH (`rtx-hk`), still blocked on enabling
SSH there (needs admin on the HK box) + the laptop's pending Tailscale reboot — see the RTX prep notes.

## Steer it from your laptop (over Tailscale)

The box is Win11 Home (no RDP) reached via Tailscale SSH as `rtx-hk`. Three ways, use any:

- **Chat:** Open WebUI is already on the RTX at `http://rtx-hk:8080`. From the laptop browser,
  paste `OPERATOR_CHARTER.md` as the system prompt and talk to it: "status", "restart LES-warmup-aureon",
  "why 0 sends". It answers on the local model.
- **Agent (opencode):** `ssh -t rtx-hk` then `opencode`. Drop `OPERATOR_CHARTER.md` in as its
  `AGENTS.md` so it operates within the rules. This is the closest to how you use me, just local.
- **On-demand sweep:** `ssh rtx-hk` then `python <path>\rtx-operator\vps_monitor.py` for a fresh
  health sweep + auto-fix + brief, or read the latest brief in `~/aureon-operator-reports`.

## Run the employee framework on the local model (optional)

Your existing `employees/` workers (bookkeeper, secretary, editor, social-writer) call cloud
`ask_claude`. To run them on the RTX's local model instead, point that one call at
`local_model.ask_local`. Concretely, in `employees/_lib.py`, make `ask_claude` fall back to the
local model when `USE_LOCAL_MODEL=1`:

```python
# top of _lib.py
import os
if os.environ.get("USE_LOCAL_MODEL") == "1":
    import sys; sys.path.insert(0, r"<path>\rtx-operator")
    from local_model import ask_local as _ask_local
# inside ask_claude(...), first line:
    if os.environ.get("USE_LOCAL_MODEL") == "1":
        return _ask_local(prompt, system=system)
```

Then the employees run free on the RTX. Keep the boss-review gate on - the local model drafts,
you approve.

## Boundaries (read this)

The local model is good at: health sweeps, restarting/repointing tasks, "why 0 sends today",
standard drafts, daily briefs, answering status questions. It handles the day-to-day.

It is NOT good enough for: open-ended debugging, database migrations, schema changes, anything
irreversible, anything that sends mail on its own. The charter makes it **escalate** those to
you instead of guessing. When you get an escalation for a hard problem, that is when you bring in
cloud Claude (this session's kind of work: the Supabase migration, the personal_hook bug hunt).

So: the RTX runs the operation day to day and flags the hard stuff; you and cloud Claude handle
the hard stuff. That is the durable, mostly-free setup.
