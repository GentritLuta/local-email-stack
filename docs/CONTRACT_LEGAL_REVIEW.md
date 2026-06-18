# Contract legal review — social + both pilot agreements

**Status: NEEDS LEGAL REVIEW before the first real client signs a social-media
or combined agreement.** The email-only agreement is unaffected.

## What is trusted vs. what is new

- `docs/aureon-pilot-agreement-diraya-print.html` — the **email base**. This is
  the established pilot agreement that real clients have already signed. Trusted.
- `docs/aureon-pilot-agreement-social-base.html` — **AI-drafted** (built by
  `out/_build_social_contract.py`). The email-specific clauses were rewritten for
  social-media management.
- `docs/aureon-pilot-agreement-both-base.html` — **AI-drafted** (built by
  `out/_build_both_contract.py`). The email base with social provisions injected.

`sequences/contract_lib.py` routes onboarding submissions to one of these three
bases by `service_type` (email / social / both). So a client who picks "social"
or "both" in the portal will be sent an agreement whose social clauses have not
yet been reviewed by a lawyer.

## Clauses a lawyer should review (social-base and both-base)

These are the provisions that were written or adapted by AI, not lifted from the
already-signed email agreement. Each carries real legal exposure:

1. **Ownership of content / IP assignment** — social clause 8 (Content, IP,
   Account Access); both clauses 8.11–8.13. Assigns content IP to the client
   conditional on payment. Check the assignment wording, moral rights, and
   especially **third-party assets** (stock footage, music, licensed fonts) that
   may not be the Provider's to assign.

2. **Platform policy / advertising disclosure** — social clause 15 (Platform
   Policies); both clause 15.4. Disclaims platform algorithm/policy changes and
   requires disclosure of paid or incentivised endorsements. Confirm this meets
   the applicable advertising-disclosure rules (FTC in the US, UWG in Germany).

3. **Account access and credentials** — social clause 8 / Schedule 1.7; both
   8.12. States access is via native business tools (Meta Business Suite, TikTok
   Business Center) with no password/recovery handover. Confirm this matches how
   access is actually taken, and the liability split if a platform **suspends or
   bans** an account.

4. **Liability and indemnity for platform actions** — account suspension, content
   takedown, follower/audience loss. Confirm the limitation-of-liability and
   indemnity carve-outs cover these social-specific outcomes.

5. **Data processing (GDPR)** — Schedule 2 data categories now include social
   audience data, comments, and DMs. Confirm the processing basis and categories
   are correct for that data.

6. **Service deliverables / SLA** — social clause 4 (and 4.7 in both), Schedule 1.7.
   Content calendar, posting cadence, weekday community management, enquiry
   routing. Make sure the commitments are achievable and not over-promised.

## How to regenerate after edits

The two bases are produced by re-runnable scripts, so a lawyer's changes can be
folded back cleanly:

- `py out/_build_social_contract.py`
- `py out/_build_both_contract.py`

Both read the email base and rewrite the service-specific clauses. If the lawyer
edits the generated HTML directly instead, keep the `contract_lib.py` swap anchors
intact (DIRAYA_CELL, recital B, persona, ref, signature block) or generation will
break.

Related: `[[saas-service-type-onboarding]]` memory.
