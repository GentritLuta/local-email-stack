# Moving the whole operation to the new PC (188.209.157.127)

This is the seamless transfer guide. Follow it top to bottom on the **new PC**. The old
laptop is already stopped (all 93 LES tasks disabled), so nothing sends from it. Do not
re-enable the laptop while the new PC is running, or both machines will send and your
prospects get duplicate emails (the stack has no cross-machine de-duplication).

Two parts move:
1. The **email stack** (`local-email-stack`) — the cold-email engine, the portal, the new
   AI-employee team, the bookkeeper. Fully bundled.
2. The **invoice generator** (`C:\Aureon Invoice App`) — a separate desktop app, moved last.

## Two copies to move it with
- **Bundle:** `C:\Users\bernh\les-migration.zip` (rebuilt with today's work). Self-contained:
  code + the secret `.env` files + private keys + state + all 93 task definitions +
  `bootstrap.ps1`. It carries the secrets, so move it as a file, never through GitHub.
- **GitHub:** `https://github.com/GentritLuta/aureon-stack` is current and carries zero
  secrets (every `.env` gitignored). Your safety net; `git clone` then drop secrets in.

## Step 1 — prerequisites on the new PC (one-time)
```powershell
winget install Python.Python.3.12        # then open a NEW PowerShell
winget install Git.Git                    # optional
npm i -g @anthropic-ai/claude-code        # the CLI the stack drafts with
claude                                    # sign in once, your Max plan
```
Chrome/Edge should be present (headless render). Keep the PC awake and logged in.

## Step 2 — unpack and bootstrap
```powershell
cd <extracted folder>
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```
It copies the stack to `%USERPROFILE%\local-email-stack`, installs deps, points scripts at
this PC's Claude CLI, and registers the tasks with the old paths rewritten and each task's
intended on/off state restored from `task-manifest.json` (75 active, 18 off). Fastest path:
tell Claude Code on the new PC "run the migration in this folder per MIGRATION.md."

## Step 3 — verify before it sends
```powershell
Get-ScheduledTask | Where-Object TaskName -like 'LES-*' | Group-Object State
```
Active LES tasks Ready, send window is recipient-local 08:00-17:00. Watch the first daily report.

## Step 4 — invoice generator (separate)
Copy `C:\Aureon Invoice App` to the new PC. It needs Python 3.12 + `drafthorse` + `facturx`
(`py -m pip install drafthorse facturx`) + headless Chrome. Today's Kosovo VAT fix and the
Payoneer switch are on its git branch `kosovo-vat-payoneer-fix`. Generate one test invoice
to confirm. Not yet on GitHub; ask and a private repo with its secrets gitignored can be made.

## Cutover and rollback
- Cutover: once the new PC verifies clean, it is live. Leave the laptop disabled.
- Rollback: run `re-enable-old-pc.ps1` on the laptop only. Never both at once.

## The one rule
One machine sends at a time. If ever unsure which is live, keep the laptop disabled.
