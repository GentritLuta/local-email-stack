# Diraya — Sales Navigator saved searches (build-along)

Four signal-based searches. Build each once, **save it**, and Sales Nav alerts you as
new people match — a self-refreshing high-intent feed beyond the static 200-hotlist.
Each search has its own tailored opener (the `{ai_signal}` line of DM-0).

> Requires Sales Navigator (1-month free trial works). Use **Lead** search for 1-3,
> **Account** search for #3's discovery step.

---

## BASE filter set (every search starts here)

Build this once as a Lead search, then layer ONE signal per saved search:

| Filter | Value |
|---|---|
| **Current job title** | Founder, Co-Founder, CTO, VP Engineering, Head of Engineering, Head of AI, Head of ML, Head of Product, VP Product |
| **Seniority level** | Owner / Partner, CXO, VP, Director |
| **Company headcount** | 11–50, 51–200 (seed–Series B proxy) |
| **Industry** | Software Development, Technology Information and Internet, Financial Services, Hospital & Health Care |
| **Geography** | United States (Diraya works any timezone; widen to UK/Canada later) |
| **Keywords** (profile) | AI OR ML OR LLM OR RAG OR agent OR "machine learning" |

Then add the signal layer below and **Save search** with the given name.

---

## Search 1 — "Diraya · Posted AI-pain (30d)"   ← highest intent
**Add to base:**
- **Posted on LinkedIn:** in the past 30 days
- **Keywords** tighten to: RAG OR hallucination OR "eval" OR "evals" OR agent OR "LLM in production" OR "agent reliability"

**Why:** they are *publicly* wrestling with the exact problem Diraya fixes. Right
person, right moment.

**Opener (`{ai_signal}` = their post):**
> Hi {first_name}, I run engineering at Diraya. We help seed-to-Series-B teams ship a
> production AI feature in 8 weeks with a written eval suite. Saw your post on {their
> RAG / agent / eval topic} — that is exactly the problem we live in. Connecting with
> builders here, no pitch.

---

## Search 2 — "Diraya · New tech leader (90d)"
**Add to base:**
- **Changed jobs:** in the past 90 days
- **Current job title** narrow to: CTO, VP Engineering, Head of Engineering, Head of AI

**Why:** a new technical leader is writing the roadmap and open to vendors before
internal politics harden. Classic buying window.

**Opener:**
> Hi {first_name}, I run engineering at Diraya. Saw you recently stepped into the
> {title} seat at {company} — congrats. We get seed-to-Series-B teams from a brittle AI
> demo to a feature that passes a written eval suite in production, in about 8 weeks.
> Connecting with technical leaders building AI roadmaps, no pitch.

---

## Search 3 — "Diraya · Hiring AI/ML"   (two-step)
**Step A (Account search):** filters **Company headcount** 11–200 + **Job opportunities
= Hiring on LinkedIn** + posted role keyword "AI Engineer" OR "ML Engineer" OR
"Machine Learning Engineer" OR "Agent". Save the account list.
**Step B:** open each account → filter people by the BASE titles → DM the CTO/founder.

**Why:** they are *paying* to build AI right now. Diraya is the faster alternative to a
4-month hire for a single feature.

**Opener:**
> Hi {first_name}, I run engineering at Diraya. Saw {company} is hiring on the AI side.
> When you need one feature shipped fast, we are the alternative to a 4-month hire: a
> production AI feature in 8 weeks with a written eval suite, first milestone day 14 or
> you owe nothing. Connecting either way, no pitch.

---

## Search 4 — "Diraya · Recently funded"
**Add to base:**
- **Company headcount growth:** more than 10% (Sales Nav proxy for momentum), AND/OR
- cross-reference fresh raises: the company's LinkedIn page **"Funding"** tab, or
  TechCrunch / Crunchbase "recently funded" feeds, and match the founder/CTO here.

**Why:** fresh budget + board pressure to ship AI = urgency. Hormozi's "right time."

**Opener:**
> Hi {first_name}, I run engineering at Diraya. Saw {company}'s recent raise — congrats.
> Fresh budget plus roadmap pressure is usually exactly when a production AI feature
> becomes urgent. We ship one in 8 weeks with a written eval suite. Connecting with
> builders here, no pitch.

---

## Working cadence
- One saved search = one "lane." Work Search 1 (highest intent) first each day.
- **15–20 connects/day** total across lanes, personalized note every time.
- Sales Nav re-runs saved searches + flags new matches → fresh leads weekly, no scraping.
- Reply → stop sequence, push to **calendly.com/amoura-ma-diraya/30min** or capture
  email → `py scripts/import-prospects-csv.py diraya leads.csv --niche yc_ai`.

*Companion to diraya-linkedin-playbook.md (§3 has DM-1…DM-6). Built 2026-06-04.*
