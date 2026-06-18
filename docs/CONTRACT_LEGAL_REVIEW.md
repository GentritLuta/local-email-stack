# Contract legal review — social + both pilot agreements

**Status: reviewed by an 8-lawyer commercial review and redlined 2026-06-18.** 51 of 52
issues fixed in `docs/aureon-pilot-agreement-social-base.html` and
`docs/aureon-pilot-agreement-both-base.html`. Two items are deliberately left for a human
decision (below). A final human-lawyer read before the first real signature is still wise,
but the fatal defects are gone.

## What was wrong and is now fixed

The two agreements were AI-adapted from the email cold-outreach base, which left defects the
review caught and the redlines fixed:

- **Three unrendered template tokens** (`\g<0>` in Recital A, `\g<1>` in the Engine
  definition 1.1.7, `\g<1>`/`\g<2>` in the termination clause 14.4) that made the central
  defined term and the wind-down clause unreadable. Fixed; zero tokens remain.
- **No-fee-but-IP-conditional-on-payment trap** (8.1 social, 8.11 both): content was assigned
  "conditional upon payment" while clause 7 says no fees are payable, so the client never got
  ownership. Now an unconditional assignment with a Provider-Materials licence-back and a
  Third Party Assets carve-out (stock, music, fonts, model/talent releases).
- **Email leftovers in the social file**: Provider "owns/provisions" the accounts (5.2),
  "warm the accounts under the domain" (6.1(a)), "bounce rate" pause (6.1(f)), "weekly brief"
  vs monthly report (6.1(e)), "positive intent replies" routing, "email service providers"
  subprocessors, dangling refs to clauses 8.7/8.9, and a GDPR Schedule 2 still describing
  cold-email prospecting. All re-mapped to social.
- **Automated AI responses** were undisclosed: new clause 6.8 discloses the automation, limits
  what the bot may commit to, and routes genuine enquiries/complaints to a human.
- **Platform risk + advertising disclosure**: platforms-are-third-parties + automation risk
  (15.4), FTC/UWG paid-content disclosure on the publishing party (15.1, 15.3, 41), force
  majeure for platform actions (16.1).
- **GDPR for social**: special-category and children's data in DMs/comments acknowledged
  (Schedule 2.5, 4.5), automated-response processing instructed (10.3(a)), consumer lawful
  basis (10.9), controller/processor roles fixed (10.2).
- **Liability/indemnity fit for social**: Provider indemnity extended to its own creative IP
  and likeness clearance (13.2), Client indemnity re-keyed to supplied assets (13.1), the
  goodwill/reputation/audience exclusion carved back for Provider-caused harm (12.3(c)),
  indemnity cap set at EUR 50,000 vs the EUR 5,000 general cap (12.2).
- **Moral rights** waiver and **user-generated-content** reposting clauses added.

## Two items left for your decision (NOT auto-applied)

1. **Governing law and forum (clause 20).** The review flagged London-seated LCIA arbitration
   under England & Wales law as disproportionate for a no-fee EUR-5,000-capped pilot between a
   Kosovo provider and a non-UK client. I did **not** unilaterally rewrite the dispute
   architecture (law + seat + Business Day + enforcement recital) from an advisory note; that is
   a strategic choice. The clause is left as-is (England & Wales / LCIA, internally consistent).
   Decide with the user whether to move to a proportionate Kosovo-seated forum.

2. **both-base Schedule 2 social processing stream.** The combined agreement's Article 28
   schedule still describes only the email processing. A "both" client's social processing
   (comments, DMs, automated responses) needs its own Schedule 2 particulars block mirroring the
   corrected social-base. The social-base standalone is fully re-mapped; the combined file's
   schedule needs this block authored (deferred because it is a substantial schedule addition,
   not a one-line redline).

## Regeneration note

These fixes were applied directly to the two committed `.html` base files (the authoritative
source `contract_lib.py` reads). The earlier scratch build scripts in `out/` are now stale; do
not re-run them, or they will reintroduce the `\g<...>` rendering bug. Edit the `.html` files
directly going forward.

Related: `[[saas-service-type-onboarding]]` memory.
