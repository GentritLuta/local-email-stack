"""Prove the fulfiller's intent-parsing + metro-matching + send(dry) happy path
without touching real sends or the DB."""
import importlib.util, json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ff", REPO / "scripts" / "fulfill-referral-requests.py")
ff = importlib.util.module_from_spec(spec); spec.loader.exec_module(ff)
index = json.loads((REPO / "referral-lists" / "curated.json").read_text(encoding="utf-8"))

JAKE_BODY = ("List\r\n\r\n________________________________\r\nFrom: Anna from Aureon Global "
             "<anna@outreach.aureonglobal.de>\r\nSent: Monday\r\nSubject: still yours if you want it\r\n"
             "Reply LIST and it is yours, no strings.\r\nReply PROBATE for the probate list.\r\n")
OUR_COPY_ONLY = ("Thanks!\r\n\r\nOn Mon wrote:\r\n> Reply LIST and it is yours\r\n> Reply PROBATE too\r\n")
ok = True

def check(name, got, want):
    global ok
    flag = "OK " if got == want else "FAIL"
    if got != want: ok = False
    print(f"  [{flag}] {name}: got={got!r} want={want!r}")

print("intent parsing (quote-stripped):")
check("jake 'List' reply", ff.intent_of(JAKE_BODY), "list")
check("our copy only in quote", ff.intent_of(OUR_COPY_ONLY), None)
check("plain probate top", ff.intent_of("PROBATE\n\n----\nFrom: x"), "probate")
check("empty", ff.intent_of(""), None)

print("\nown-domain exclusion:")
check("anna@outreach.aureonglobal.de", ff.is_ours("anna@outreach.aureonglobal.de"), True)
check("jake@cbstiles.com", ff.is_ours("jake@cbstiles.com"), False)

print("\narea code:")
check("317-965-4849", ff.area_code("317-965-4849"), "317")
check("(463) 555-1212", ff.area_code("(463) 555-1212"), "463")
check("+1 614 555 0000", ff.area_code("+1 614 555 0000"), "614")

print("\nmetro resolution:")
check("ac 317 -> Indianapolis", (ff.resolve(index, None, None, "317") or {}).get("metro"), "Indianapolis")
check("Greenwood/IN -> Indianapolis", (ff.resolve(index, "Greenwood", "IN", "") or {}).get("metro"), "Indianapolis")
check("ac 614 (Columbus) -> none", ff.resolve(index, None, None, "614"), None)
check("Austin/TX -> none", ff.resolve(index, "Austin", "TX", ""), None)

print("\nsend(dry) for a matched Indianapolis agent:")
entry = ff.resolve(index, None, None, "317")
import os
env = {"RESEND_KEY": "x"}
ff.send_list(env, "jake@cbstiles.com", "Jake", entry, dry=True)

print("\nALL PASS" if ok else "\nSOME FAILED")
