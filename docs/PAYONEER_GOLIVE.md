# Payoneer go-live — 3 steps when your API access is approved

Everything is wired and waiting. Until you do this, nothing charges (safe no-op).

## 1. Paste your credentials
Edit `sequences/payoneer.env` and fill the 3 blanks:

```
PAYONEER_PROGRAM_ID=...
PAYONEER_CLIENT_ID=...
PAYONEER_CLIENT_SECRET=...
```

Keep `PAYONEER_BASE=https://api.sandbox.payoneer.com` while testing.

## 2. Dry-run test (charges nothing)
```
py scripts/payoneer-charge.py
```
With `PAYONEER_LIVE=false` it logs what it *would* charge for every open invoice
of a client with an authorized billing profile. Confirm the amounts/clients look
right.

## 3. Go live
- Switch `PAYONEER_BASE=https://api.payoneer.com`
- Set `PAYONEER_LIVE=true`
- Enable the scheduled task (runs every 6h, already registered, currently OFF):
  ```
  powershell -Command "Enable-ScheduledTask -TaskName 'LES-payoneer-charge'"
  ```

## What runs
- A new invoice (from the generator -> `LES-invoice-import`) lands as `sent`.
- `LES-payoneer-charge` finds it + the client's signed billing authorization and
  charges via Payoneer for the outstanding amount.
- On capture: invoice flips to `paid`, `payoneer_ref` + `payoneer_status` recorded,
  client sees it on their dashboard.

## Kosovo reminder
Payoneer is the only working rail for a Kosovo entity (no Stripe/Mollie/SEPA-DD).
Card numbers are never stored. The `billing_profiles.card_*` columns exist only
for a future PCI-compliant tokenized processor, not raw cards.
