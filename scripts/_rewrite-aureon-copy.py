"""One-shot: rewrite aureon-default/variants.json into a give-first Hormozi
sequence. Preserves schema (n, delay_days, angle, subject, body) + cadence.
Char rules: NO apostrophes, em/en dashes, smart quotes, ellipses, contractions,
word-internal hyphens. Merges: {greeting} {company} + optional {geo_clause}
{team_phrase} {proof_line}.
"""
import json, re, sys
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "sequences" / "aureon-default" / "variants.json"
d = json.loads(P.read_text(encoding="utf-8"))

VARIANTS = [
    {
        "n": 1, "delay_days": 0, "angle": "give_first_attorney_list",
        "subject": "a list for {company}",
        "body": """Hey {greeting},

No pitch in this email.

I can pull a list of 40 to 50 divorce and estate attorneys{geo_clause} who routinely send home sellers to agents. They are the highest converting referral source in real estate and almost no agent works them.

Want it for {company}? Reply with the word LIST and I send it inside 24 hours. No call, no catch.

If you already work that channel, tell me and I will pull a different one for you.""",
    },
    {
        "n": 2, "delay_days": 2, "angle": "give_repeat_soft_bridge",
        "subject": "still yours if you want it",
        "body": """Hey {greeting},

Quick follow up. That attorney list for {company} still stands. Reply LIST and it is yours, no strings.

Why I have these lists ready: we run seller outbound for a small group of brokerages, and a list like this is one small piece of it. More on that another day.

For now, want the list?""",
    },
    {
        "n": 3, "delay_days": 2, "angle": "pain_shared_leads_mechanism",
        "subject": "the problem with bought leads",
        "body": """Hey {greeting},

Here is the trap most agents{geo_clause} are stuck in. You buy leads from Zillow or Realtor that 5 or 6 other agents buy at the same second. You race to call first, you cut your fee to win, and you end up chasing buyers instead of taking listings.

We built The Listing Engine to flip that. It runs done for you seller outbound so {team_phrase} gets listing appointments that belong to you alone. {proof_line}

Worth 15 minutes to see how it works?""",
    },
    {
        "n": 4, "delay_days": 3, "angle": "offer_beta_reason_why",
        "subject": "60 days at zero cost for {company}",
        "body": """Hey {greeting},

Here is the straight offer.

We are taking 12 brokerages into a 60 day beta. You get full setup, all the seller outbound done for you, live appointment alerts, and a weekly numbers report. You keep 100 percent of every commission and every lead we source.

Why it is free: we want 12 clean case studies before we set the price. That is the whole catch. One honest review at the end. {proof_line}

One closed listing at average US prices pays you about 9k, for 15 minutes on a setup call. Open to it this week?""",
    },
    {
        "n": 5, "delay_days": 4, "angle": "forced_yes_or_no",
        "subject": "{company}, a clear yes or no",
        "body": """Hey {greeting},

If we ran The Listing Engine on {company} for 60 days at zero cost, you kept every commission, and you could walk away any day with every lead we sourced, would you try it?

A clear yes or a clear no both help me.""",
    },
    {
        "n": 6, "delay_days": 7, "angle": "pure_value_second_give",
        "subject": "one more thing you can use",
        "body": """Hey {greeting},

Beta or no beta, here is something you can use today.

Reply with the word PROBATE and I will pull a list of probate and estate attorneys{geo_clause} who handle home sales for families. They refer the listing to one trusted agent, and most are not worked yet. Free, no call.

Want it?""",
    },
    {
        "n": 7, "delay_days": 10, "angle": "breakup",
        "subject": "closing your file",
        "body": """Hey {greeting},

I am closing your file at Aureon today. The beta has 12 slots and they fill this week.

If the timing is off for {company}, I understand. If the offer is off, tell me what would land and I will listen. Either way, the attorney list is still yours. Just reply LIST.""",
    },
]

# Forbidden-char guard (the strict voice rules)
FORBIDDEN = {
    "apostrophe": "'", "smart_apos": "’", "em_dash": "—",
    "en_dash": "–", "ellipsis": "…", "smart_quote_l": "“",
    "smart_quote_r": "”",
}
bad = []
WORD_HYPHEN = re.compile(r"[A-Za-z]-[A-Za-z]")
for v in VARIANTS:
    blob = v["subject"] + "\n" + v["body"]
    for nm, ch in FORBIDDEN.items():
        if ch in blob:
            bad.append(f"v{v['n']} contains {nm}")
    # word-internal hyphen (allow none)
    if WORD_HYPHEN.search(blob):
        bad.append(f"v{v['n']} has a word-internal hyphen: {WORD_HYPHEN.search(blob).group(0)}")
    # contractions quick check
    for c in (" dont ", " wont ", " cant ", " youre ", " weve ", " ill ", " im ", " its "):
        if c in (" " + blob.lower().replace("\n", " ") + " "):
            bad.append(f"v{v['n']} possible contraction {c.strip()}")

if bad:
    print("CHAR-RULE VIOLATIONS:")
    for b in bad:
        print("  -", b)
    sys.exit(1)

d["variants"] = VARIANTS
d["required_merges"] = ["company"]
d["name"] = ("Aureon Global - 7-email give-first Hormozi sequence "
             "(The Listing Engine beta, lead-magnet led)")
d["voice_notes"] = (
    "GIVE-FIRST Hormozi $100M Leads structure. E1+E2 lead with a free attorney "
    "referral list (reply LIST). E3 names the pain (shared bought leads) + the "
    "mechanism The Listing Engine. E4 the free 60-day beta offer with reason-why. "
    "E5 binary yes/no. E6 second give (reply PROBATE). E7 breakup, give still open. "
    "PROOF: {proof_line} is an optional merge, empty by default. When you have a "
    "real beta result, set it in sequence-runner.synthesize_optional_merges (e.g. "
    "'Our first beta brokerage booked 14 listing appointments in 30 days.'). The "
    "give itself is the live proof of competence. Strict char rules: NO "
    "apostrophes, em-dashes, en-dashes, smart quotes, ellipses, contractions, "
    "word-internal hyphens. Required merges {greeting} {company}; optional "
    "{geo_clause} {team_phrase} {proof_line}. Lead-magnet fulfilment: "
    "scripts/pull-referral-list.py <city> --type divorce|estate|probate."
)

P.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print("OK wrote", P)
print("variants:", len(d["variants"]), "| char rules: clean")
