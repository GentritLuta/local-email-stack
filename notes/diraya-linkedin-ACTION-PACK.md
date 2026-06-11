# Diraya LinkedIn — START HERE (action pack)

The companion to `diraya-linkedin-playbook.md`. The playbook has the *templates +
Sales Nav filters*; this tells you *who to hit first* and *how to run it daily*.

## The list
- **`out/diraya_linkedin_hotlist.csv`** — top 200 founders, prioritized (CTOs +
  freshest 2026 batches first). Columns: name, title, company, batch, LinkedIn URL,
  `segment` (technical / founder), `dm_angle`, one-liner.
- Full pool (2,742 founders / 1,382 AI startups): `out/diraya_linkedin_targets.csv`.
- These are the SAME companies the email channel is hitting — so a founder may get
  a Diraya email *and* a LinkedIn touch. That is fine (multi-touch), but if you want
  to avoid overlap, skip anyone already in the email pool (niche `yc_ai`).

## Daily cadence (stay under LinkedIn limits)
1. Open `diraya_linkedin_hotlist.csv`, work top-down.
2. ~15–20 per day. Connect (no note) or a 1-line note. Once they accept, send the DM.
3. Match the template to the `dm_angle` column:
   - **technical** → the technical-peer DM (lead with evals / production reliability /
     the 12%→0.4% hallucination number). You are talking shop with a CTO.
   - **founder** → the founder-to-founder DM (ship a working AI feature in 8 weeks,
     fixed scope, day-14 milestone or no invoice).
4. Personalize line 1 from the `one_liner` column (what they actually build).
5. Anyone who shares an email or books a call → drop them in a CSV and run
   `py scripts/import-prospects-csv.py diraya <that.csv>` — the 7-email sequence
   takes over automatically.

## Why these first
- 124 of the top 200 are CTOs / technical co-founders — they feel the production-AI
  pain Diraya fixes, so the technical pitch lands without translation.
- 2026 batches (P26/W26) are 0–6 months old: actively building, reachable, no vendor
  lock-in yet.

That is the whole motion: hotlist → connect → matched DM → reply → import → sequence.
