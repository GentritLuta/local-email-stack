# Andrew — Zero-Spend Seller Engine

Partner agent: **Andrew Barr**, @properties Indianapolis (andrew@atpropertiesind.com)
Territory: 15 Indy-metro zips (Anderson / Noblesville / north Indianapolis)
Mode: **$0** — no ads, no mail, no paid data. Volume comes from Andrew's own audience.

## How it runs (the loop)

1. Andrew's free home-value page is **live**: https://gentritluta.github.io/local-email-stack/home-value/andrew.html
2. A homeowner lands on it, enters their address + contact, optionally books a call. That is a **consented** opt-in.
3. `fulfill-home-value.py` emails them a branded value report + a booking link, and fires a **"HOT seller appointment"** alert to info@aureonglobal.de.
4. You (Aureon) confirm the time and **hand the booked appointment to Andrew**. He runs the listing appointment and closes.
5. Every booking is captured in `meeting-followup` so the outcome + follow-up are tracked.

Two ways to put sellers in front of that page, both free:
- **Engine A — Andrew's sphere (the real volume).** Andrew posts the page to his database + social. Warm audience, zero cost.
- **Engine B — FSBO replies (the bonus).** Reply to for-sale-by-owner listings through their own channel. They invited contact, so it is defensible.

---

## ENGINE A — Andrew's sphere kit (copy/paste)

His page link, used everywhere below: **https://gentritluta.github.io/local-email-stack/home-value/andrew.html**

### A1. Email to his database (CAN-SPAM safe — his own contacts)

> **Subject:** What's your place in {AREA} actually worth right now?
>
> Hi {First name},
>
> Quick one. The {AREA} market has moved a lot this year, and most homeowners are working off a Zestimate that is months stale.
>
> I put together a free, no-pressure home value report. You enter your address, I pull the county records and recent comparable sales, and you get a real range plus what you would net after costs. No call required to get it.
>
> Here it is: https://gentritluta.github.io/local-email-stack/home-value/andrew.html
>
> If you have ever wondered "what would we get if we sold," this answers it in two minutes.
>
> Andrew Barr · @properties Indianapolis

### A2. Social posts (rotate, swap the area)

1. "{AREA} homeowners: homes near you are closing for more than people think. I will pull your real number from county records + recent sales, free, no call needed. Drop your address here 👉 [link]"
2. "Thinking about selling in {AREA} in the next 6-12 months? Start with the number. Free home value report (real comps, not a Zestimate): [link]"
3. "I keep getting asked 'what is my house worth?' so I made it self-serve. Two minutes, free, you get a real range + your net-after-costs: [link]"

### A3. Text / DM (warm contacts only — never cold numbers)

> "Hey {First name} — random, but are you two still in the {AREA} place? Made a free home-value tool, pulls real comps. Curious what yours shows now: [link]. No agenda, just thought you'd want the number."

### A4. Per-zip angle (swap {AREA} from the list)

| Zips | Use as {AREA} |
|---|---|
| 46011 46012 46013 46016 46017 | Anderson |
| 46055 | McCordsville |
| 46060 46062 46064 | Noblesville |
| 46202 | downtown Indy / Herron-Morton |
| 46220 | Broad Ripple / SoBro |
| 46226 46236 | northeast Indy |
| 46250 | Castleton |
| 46256 | Geist |

Cadence: 2-3 sphere posts a week, rotating the area. The page does the rest.

---

## ENGINE B — FSBO reply pack (do these today)

These are live for-sale-by-owner listings in the territory. Reply **through each listing's own reply link** (the seller invited contact). No phone needed.

| Zip | Property | Listing |
|---|---|---|
| 46055 | 4620 S High School Rd area | https://indianapolis.craigslist.org/reo/d/indianapolis-modern-bed-bath-double/7938718347.html |
| 46055 | 5944 South Karen Drive | https://indianapolis.craigslist.org/reo/d/indianapolis-great-property/7937003492.html |
| 46060 | 13028 Girvan Way (Fishers) | https://indianapolis.craigslist.org/reo/d/fishers-beautiful-fishers-home-flexible/7936533156.html |

(One more result was a vacant lot, skipped.)

### B1. FSBO reply message (copy/paste into each listing's reply)

> Hi — saw you are selling on your own, respect that. Not trying to talk you out of it. I work {AREA} and have a couple of buyers actively looking in your range. If it would help, I can send you a free, no-obligation value report so you know your home is priced where the recent sales actually support it (a lot of FSBOs leave money on the table by guessing). Either way, happy to share what comparable homes near you just closed for. Want me to send it?
>
> Andrew Barr · @properties Indianapolis

Refresh weekly: re-run the sweep to catch new FSBO listings (command below).

---

## The honest part

- **Zero-spend cold sourcing is thin by design.** The whole 15-zip metro produced 4 FSBO listings. That is a daily reply task, not a pipeline. Your seller meetings will come from Engine A (Andrew's sphere), full stop.
- **The volume you are leaving on the table:** the same sweep found **150 absentee owners** with verified mailing addresses (free county data). They are direct-mail-ready the day you decide to spend on postage. That is the real lever if Engine A is not enough. No subscription, just stamps.
- **What stays off-limits:** cold-calling or cold-texting homeowners (TCPA, $500-1,500 per violation) and any paid skip-trace data used for marketing (GLBA/DPPA). We are not doing those.

## Refresh command (weekly FSBO + absentee sweep)

```
python scripts/andrew-seller-sweep.py
```
Writes `out/andrew_fsbo_leads.csv` (FSBO = reply-via-listing; absentee = mail-ready when you want it).
