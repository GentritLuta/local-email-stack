# Reply and Conversion: Correlation Analysis and the Path to 5x

A data analysis of every email the operation has sent, what actually moves reply and conversion, what Alex Hormozi teaches about it, and a concrete plan to 5x reply rate and reach 0.5% conversion. Prepared 2026-06-14.

## Headline

The leak is not deliverability and not opens. It is open-to-reply. More than half of delivered emails are opened (57.3%), but only 0.55% reply. The single highest-leverage fix is already proven on our own biggest brand: a give-first opener took aureon from 0.3% to 5.4% reply. The plan is to make the give the email across every brand, tighten the list, add one true personalization signal, and measure with proper A/B tests. Volume, deliverability, and step depth are not the levers.

## 1. The data

Scope: 2,972 sends mapped to a brand, 2,896 delivered, 16 total replies, across six brands.

### The funnel (operation-wide)

![Funnel](file:///C:/Users/bernh/local-email-stack/out/research/funnel.png)

Delivery (97.4%) and open rate (57.3%) are healthy and in line with good cold-email operations. The collapse is at the reply step: of everyone who opens, only about 1% replies. That is the entire problem in one number.

### Reply rate by brand (95% Wilson confidence intervals)

![Reply by brand](file:///C:/Users/bernh/local-email-stack/out/research/reply_by_brand.png)

| Brand | Delivered | Replies | Reply rate | 95% CI | Open | Click |
|---|---|---|---|---|---|---|
| algoalpha | 241 | 6 | 2.49% | 1.15 to 5.32 | 58.9% | 2.1% |
| aureon | 2,251 | 10 | 0.44% | 0.24 to 0.82 | 54.5% | 5.9% |
| diraya | 297 | 0 | 0.00% | 0 to 1.28 | 82.2% | 3.4% |
| energ | 70 | 0 | 0.00% | 0 to 5.2 | 48.6% | 38.6% |
| dorian | 36 | 0 | 0.00% | 0 to 9.64 | 33.3% | 2.1% |

Three tells. algoalpha leads at 2.5% with a friendly tone and a concrete paid give (a retainer plus 30% commission). diraya opens at 82% and still gets zero replies, the give was buried under credentials. energ gets a 38.6% click rate and zero replies because the click went to the website instead of asking for a reply (now fixed).

### Reply rate by sequence step

![Reply by step](file:///C:/Users/bernh/local-email-stack/out/research/reply_by_step.png)

Step 1 replies at 0.91%, step 2 at 0.40%, steps 3 to 5 at roughly 0%. This looks like later steps do not work, but it is confounded: the later steps have barely fired (the campaigns are young), so this is not evidence to abandon follow-up. It is evidence we are leaving follow-up replies on the table.

### Correlation analysis: linear and non-linear (and why it is not the evidence to lean on)

We ran both linear (Pearson) and non-linear (Spearman rank, mutual information, random-forest importance) correlations.

Per-send point-biserial correlations (n=2,972): `opened` (r=0.056, p=0.002), `subject length` (r=0.056, p=0.003), and `step` (r=-0.047, p=0.008) are statistically significant. But significance here is an artifact of the large n. The effect sizes are trivially small: an r of 0.05 explains about 0.3% of the variance. With only 16 positive events, a binary reply outcome simply does not carry enough signal for per-send correlations to be practically meaningful.

Per-variant-cell correlations (n=14 brand-step cells): nothing reaches significance. Subject length shows the strongest hint (Pearson 0.50, p=0.07, borderline), and the random forest ranks subject and body length highest, but on 14 cells this is weak. The honest conclusion: the observational correlations are underpowered and should not be treated as causal.

![Spearman correlation](file:///C:/Users/bernh/local-email-stack/out/research/corr_spearman.png)

### What IS trustworthy

1. The controlled A/B on aureon. A give-first step 1 ("free 14-day seller test, you keep every lead, no card, stop any day") got 5.4% reply and 64% open versus 0.3% reply on the old "are you open?" opener. This is a real experiment with a held variable, far more reliable than any of the correlations above, and it shows a 10-18x lift from one change.
2. The funnel. The leak is open-to-reply, full stop.
3. The per-brand spread. The brand that gives first and warmly (algoalpha) leads; the brands that bury the give (diraya) or route clicks away (energ) sit at zero.

## 2. What Hormozi actually wrote

From "$100M Leads" (Core Four, lead magnets, outreach math) and "$100M Offers" (the Value Equation, guarantees). Paraphrased.

### The Value Equation

Value = (Dream Outcome x Perceived Likelihood) / (Time Delay x Effort and Sacrifice).

It is a division, so value spikes when the denominator shrinks toward zero, not only when the numerator grows. This is the best diagnostic for our open-to-reply leak: the recipient opened, but the implied deal failed the equation, so they closed it.

- Dream outcome: name the specific result in their words (more booked listings, lower energy bills), not your service category.
- Perceived likelihood: the weakest term for a stranger. Raise it with one concrete proof point or, best, by making the give itself the proof (a free test they verify with their own eyes).
- Time delay: deliver value inside the email or within hours, not "let's hop on a call." "14-day test, keep every lead" collapses delay, value starts now.
- Effort and sacrifice: the reply ask must be one tiny action. "No card, stop any day" removes the sacrifice term.

Our open-to-reply leak is a denominator problem: the ask costs too much time and effort for a vague, low-likelihood dream.

### The lead magnet (the "give")

A give converts when it is (1) valuable enough that a reasonable person would have paid for it, (2) a complete solution to one narrow problem (narrow-and-complete beats broad-and-shallow), and (3) fast to consume so the value lands immediately. The strongest gives prove competence rather than describe it: a done-for-you audit, a free trial where they keep the output, a teardown of their current page. Strategy: "give until they ask" (roughly a 3.5:1 give-to-ask ratio), which flips the power dynamic from "I want something" to "I am handing you something." This matches our own A/B evidence exactly.

### The cold-outreach multipliers

Success = people contacted x times each is contacted (follow-up) x strength of the offer. You cannot fix a 0.55% reply rate with volume alone when two of three multipliers are weak. We already have the volume. The job is the offer (proven 10-18x) and the follow-up (steps 3 to 5 that barely fire).

### Personalization and list

Personalize for psychological relevance, not cosmetic merge tags. One true, specific observation about the prospect beats "{first_name}". And the list is king: a clean, tightly-segmented niche list beats a large dirty one.

## 3. Where we sit versus benchmarks

Web-verified, 2024 to 2026:

- Reply rate: typical B2B cold email is 3 to 6% (Belkins 2025, 16.5M emails, 5.8% average; Apollo and Instantly cite ~3.4%). We are at 0.55% blended, well below typical.
- Conversion: booked-call rate per email sent averages 0.1 to 0.8%; "good" is above 0.4% (Apollo, Martal ~0.33%). Our ~0.03% is far below.
- Is 0.5% conversion realistic? Yes, it sits right at the "good operator" threshold. But it is conditional on first getting reply rate into the 3 to 8% band. You cannot book what does not reply.

## 4. The plan: 5x reply and 0.5% conversion

### Funnel math

Of delivered: open 57.3% -> reply 0.55%. So openers-who-reply = 0.55 / 57.3 = about 1%. To hit 2.75% blended reply at the same open rate, we need 2.75 / 57.3 = 4.8% of openers to reply. That is the whole job: take openers-who-reply from ~1% to ~4.8%. The aureon A/B already cleared this bar (5.4% reply on 64% open = 8.4% of openers replied). The target is not just achievable, we have already done better on the biggest brand.

### Levers, prioritized

| Pri | Lever | Expected reply lift | The change in our stack |
|---|---|---|---|
| P0 | Surface the give in line 1 of step 1 for every brand. The give must BE the email, read in 5 seconds, not sit under a paragraph of credentials. | 3-10x on brands burying the give (diraya 0 to ~3%, energ 0 to ~2.5%) | Edit step-1 body in each `*-default/variants.json`, push via supabase_sync. Mirror the aureon winner. |
| P1 | Tighten ICP to 1-2 contacts per company, lean SMB, enforced at scrape time. | ~1.5-2x, and better positive-reply quality | `lead_scrape.py` dedup-by-company cap. |
| P1 | Wire one TRUE personalization signal into line 1 (not {first_name}). | ~1.3-2x, stacks with the offer fix | A `{hook}` field captured at scrape time, required merge. |
| P2 | Make steps 3-5 actually fire, each a NEW give or angle. | ~1.2-1.5x from follow-up replies we leave on the table | Confirm cadence fires; rewrite later steps as fresh gives. |
| P2 | Clean dorian's 25% bounce before any reply tuning. | Prerequisite to measuring dorian at all | `reverify-unknowns.py` over the dorian set. |

The give-first lever does most of the 5x on its own. Everything else stacks on top.

### From reply to 0.5% conversion

Reply rate produces positives; the conversion target is won or lost in the reply-to-booking handoff, all in existing tooling:

1. Speed. Answer the first reply fast. `reply-autodraft.py` already drafts and (for clear positives) can auto-send the booking link. The risk is the human-approval step adding hours; auto-send clear positives.
2. One clean give-first ask with the calendar link plus a restated risk-reversal (the qualifying questions are already added).
3. Qualify lightly to protect show-rate.
4. Reminders between booking and call to cut no-shows (the meeting-followup tool).

### How to measure honestly (this matters)

16 replies is not enough to conclude anything. Going forward: run ONE change at a time as a proper per-variant A/B through the existing harness (`sequence-runner.py` already splits inline vs linked variants by prospect id), and do not call a winner until each arm has enough delivered to separate the rates (a 0.5% vs 2.5% difference needs on the order of 500 to 1,000 delivered per arm for confidence). Watch: delivered, open, reply, positive-reply, calls booked, show rate.

## 5. The honest caveats

- The correlation analysis is underpowered. Treat it as hypothesis generation, not proof. The trustworthy evidence is the aureon A/B, the funnel, and the per-brand spread.
- The 5x blended figure leans heavily on aureon (about 78% of volume). Most of the projected gain assumes aureon's post-winner rate holds at scale. Confirm with live per-brand A/Bs rather than assuming the blend.
- 0.5% conversion is realistic (the "good operator" band) but conditional on first lifting reply into the 3 to 8% range, and the timeline is weeks of testing, not a switch.
