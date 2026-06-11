# Reply-rate analysis + Hormozi proposal — 2026-06-08

## The numbers (all-time, send_log + replies tables)
- 1703 emails sent, 1670 delivered (98%), 30 bounced (1.8%). Deliverability is healthy.
- Genuine human replies classified `reply`: **9** = ~0.5% reply rate. Target (per EnerG model) is 2.5-5%.
- replies table: 480 "unrelated", 92 bounce, 59 self_alert, 9 reply. The "unrelated" bucket is
  mostly genuine noise (daily reports, Instagram, Dropbox, the user's own onboarding mails) BUT a
  few real prospect replies are misclassified there (apexlitigationfin, axiafunder = Diraya replies).

## The signal that matters (aureon, the only profile with real reply data)
Reply count by step-1 subject line ACTUALLY SENT:
- **"Are you open?"** — sent **301x**, got **1 reply** (a "not interested"). ~0.3%. This is the
  default step-1 and it is burning the list.
- **"a seller test for {company}"** — sent **6x**, got **6 replies**. Brokers reply with their zip
  code (46033, 47448...). One converted to "can we set up a call Tuesday?" Near-100% on a tiny sample.
- "still yours if you want it" — 85 sent, 1 reply. "the problem with bought leads" — 30 sent, 0.
- German copy ("Sind Sie offen?", "38 Wohnungen") is leaking onto aureon domains (f2/Regimo). Worth
  a separate look — cross-brand contamination.

## What this means
The deployed aureon copy (20 variants in DB) is ALREADY strongly Hormozi: free 60-day beta, "keep
100%", risk reversal, clear yes/no, value-stacked lead magnets (LIST/PROBATE). Making it "more
Hormozi" is not the lever. The lever is the **mechanic of the ask**:
- "Are you open?" asks for a yes to a pitch -> ignored.
- "a seller test for {company}" asks for ONE tiny number (your zip) -> replies. It is a question only
  they can answer, about their own business, costing 2 seconds. That is the Hormozi "lower the ask"
  principle in action, and the data proves it.

## PROPOSAL (pending approval — no live copy changed yet)
1. **Kill "Are you open?" as aureon step 1.** Replace with the proven "a seller test for {company}"
   zip-code hook as the new step-1 subject + body. Highest-leverage single change.
2. **Rebuild the sequence around the zip-reply mechanic:** step 1 asks for the zip ("which zip should
   I run the seller test in?"), step 2+ deliver against it. Keep the strong Hormozi offer for later steps.
3. **Fix reply classification:** 480 "unrelated" is hiding real replies. Tighten the classifier so
   prospect replies (esp. Diraya litigation-funding) get caught + auto-drafted, not buried. This alone
   recovers replies you are already getting but not actioning.
4. **Stop German leakage onto aureon domains** (separate bug to confirm).
5. Apply the same "low-friction one-number ask" pattern to EnerG (ask for current kWh) and AlgoAlpha
   (ask for channel link, which it already does in "Are you open?" - but test a creator-specific hook).

## Recommended order of impact
#1 (swap step-1 subject) > #3 (recover buried replies) > #2 (full sequence rebuild) > #4 > #5.

---

## DONE 2026-06-08
1. **Step-1 subject swapped to winner.** A/B (scripts/ab-results.py) verdict: "a seller test for
   {company}" = 5.4% reply / 64% open vs "Are you open?"/legacy 0.3% and side-B 0.5%. Set BOTH A/B
   sides (variant subject + sequence_steps.inline_subject) to the winner, in DB AND in
   sequences/aureon-default/variants.json. ~10x reply-rate lever on aureon step 1.
3. **Reply classification fix (imap-poll.py).** Added a symmetric UPGRADE in the main loop: a
   message with no In-Reply-To/References that classify() dropped to "unrelated" is upgraded to
   "reply" IF the sender is a known prospect AND not EXCLUDE_FROM (laso.finance legal case + own
   infra) AND not NOISE_SUBJ. Catches prospect replies that broke threading. Applies to FUTURE mail
   only; the existing 480 "unrelated" rows are not retroactively rescanned (optional one-off cleanup).
   RESCAN RESULT (scripts/_rescan-unrelated-replies.py, dry-run 2026-06-08): of 485 'unrelated' rows,
   only 1 is from a known prospect and it is an out-of-office auto-responder, NOT a real reply. So
   the 480 are genuine noise, not buried prospect replies. Did NOT apply (upgrading an OOO would
   wrongly pause that run). No historical reply backlog to recover.

## German-leakage finding (flagged, NOT fixed — needs a decision)
"Sind Sie offen?" / Swiss German copy (f2-malergipser, jordi-liegenschaften prospects) sends from
**aureon's domains** (lukas@news.aureonglobal.de). Root cause: f2-malergipser has ZERO from_domains
of its own and its personas are hardcoded to @news/send.aureonglobal.de. It is DORMANT now
(active=false, last such send 2026-05-28), so not actively leaking. But reactivating f2 as-is would
pollute aureon's US-real-estate domain reputation with German content. FIX = provision f2-malergipser
its own sending domains (same flow as AlgoAlpha) and repoint personas. Separate provisioning task.
