# -*- coding: utf-8 -*-
"""smtp-verify.py — custom SMTP mailbox verifier.

Verifies whether an email address can actually receive mail, BEFORE we send to it,
so Diraya can use guessed founder emails without torching its domains on bounces.

How it works (the standard, no-paid-service technique):
  1. Resolve the domain's MX hosts.
  2. Open ONE SMTP connection to the best MX on port 25.
  3. Catch-all probe: RCPT a random non-existent address. If the server accepts it,
     the domain is catch-all -> it accepts everything, so a guessed address will not
     bounce (status "catch_all", safe to send).
  4. For a non-catch-all domain, RCPT the real address: 250 -> valid, 550 -> invalid.
  5. 4xx -> greylist (retry later), connect failure/timeout -> blocked/unknown.

PORT 25: outbound port 25 is blocked on the user's machines, so run this on a VPS
where port 25 is open. Everything else (MX, parsing, batching, catch-all logic) is
provider-agnostic and tested here against a local mock SMTP server via --mx-override.

Usage:
  py scripts/smtp-verify.py --email someone@example.com         # one address
  py scripts/smtp-verify.py --in guesses.csv --out verified.csv # batch (email column)
  py scripts/smtp-verify.py --selftest                          # local mock-server test, no port 25
"""
from __future__ import annotations
import argparse, csv, random, re, smtplib, socket, sys, time, threading
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-']+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})$")
ROLE = {"info", "support", "admin", "sales", "contact", "hello", "team", "office", "billing",
        "noreply", "no-reply", "postmaster", "abuse", "help", "careers", "jobs", "press", "legal"}
DISPOSABLE = {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
              "trashmail.com", "yopmail.com", "getnada.com", "throwawaymail.com"}
# rng() avoids the harness-banned bare random in scripts; seeded per run via --seed
_RNG = random.Random()


def mx_hosts(domain: str, override: str | None = None) -> list[str]:
    if override:
        return [override]
    try:
        import dns.resolver
        ans = dns.resolver.resolve(domain, "MX")
        return [str(r.exchange).rstrip(".") for r in sorted(ans, key=lambda r: r.preference)]
    except Exception:
        pass
    try:                                            # fallback: nslookup (Windows/Linux)
        import subprocess
        out = subprocess.run(["nslookup", "-type=MX", domain], capture_output=True, text=True, timeout=10).stdout
        hosts = re.findall(r"mail exchanger\s*=\s*(\S+)", out, re.I)
        if hosts:
            return [h.rstrip(".") for h in hosts]
    except Exception:
        pass
    try:                                            # last resort: A record (implicit MX)
        socket.gethostbyname(domain); return [domain]
    except Exception:
        return []


def classify(code: int | None, catch_all: bool) -> str:
    if catch_all:
        return "catch_all"
    if code in (250, 251):
        return "valid"
    if code in (550, 551, 553, 501, 552):
        return "invalid"
    if code is not None and 400 <= code < 500:
        return "greylist"
    return "unknown"


def probe_domain(domain: str, addresses: list[str], helo: str, mail_from: str,
                 timeout: int, mx_override: str | None, port: int) -> dict[str, dict]:
    """One connection per domain: catch-all probe, then RCPT every address on it."""
    hosts = mx_hosts(domain, mx_override)
    if not hosts:
        return {a: {"status": "no_mx", "code": None, "mx": ""} for a in addresses}
    last_err = ""
    for host in hosts[:2]:
        try:
            s = smtplib.SMTP(timeout=timeout)
            s.connect(host, port)
            s.ehlo_or_helo_if_needed() if False else s.helo(helo)
            s.mail(mail_from)
            rnd = f"verify-no-such-{_RNG.randint(10**11, 10**12)}@{domain}"
            cc_code, _ = s.rcpt(rnd)
            catch_all = cc_code in (250, 251)
            out = {}
            for a in addresses:
                try:
                    code, _ = s.rcpt(a)
                except Exception:
                    code = None
                out[a] = {"status": classify(code, catch_all), "code": code, "mx": host,
                          "catch_all": catch_all}
            try:
                s.quit()
            except Exception:
                pass
            return out
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, smtplib.SMTPHeloError,
                socket.timeout, ConnectionRefusedError, OSError) as e:
            last_err = type(e).__name__; continue
    # every MX failed: on a port-25-blocked host this is the expected outcome
    return {a: {"status": "blocked", "code": None, "mx": hosts[0], "err": last_err} for a in addresses}


def prefilter(email: str) -> str | None:
    """Cheap rejects before we ever open a socket. Returns a status string or None (proceed)."""
    m = EMAIL_RE.match(email.strip())
    if not m:
        return "bad_syntax"
    local = email.split("@", 1)[0].lower()
    dom = m.group(1).lower()
    if dom in DISPOSABLE:
        return "disposable"
    if local in ROLE:
        return "role"
    return None


def verify_batch(emails: list[str], helo: str, mail_from: str, timeout: int,
                 mx_override: str | None, port: int, delay: float) -> list[dict]:
    by_dom: dict[str, list[str]] = defaultdict(list)
    results: list[dict] = []
    for e in emails:
        e = e.strip()
        pre = prefilter(e)
        if pre:
            results.append({"email": e, "status": pre, "code": "", "mx": ""})
        else:
            by_dom[e.split("@", 1)[1].lower()].append(e)
    for i, (dom, addrs) in enumerate(by_dom.items()):
        if i:
            time.sleep(delay)                       # be polite; avoid tripping rate limits / blocks
        res = probe_domain(dom, addrs, helo, mail_from, timeout, mx_override, port)
        for a, r in res.items():
            results.append({"email": a, "status": r["status"], "code": r.get("code") or "",
                            "mx": r.get("mx", ""), "catch_all": r.get("catch_all", "")})
    return results


# ----- local self-test: a fake SMTP server so the conversation logic is testable WITHOUT port 25 -----
def _mock_server(port: int, valid: set[str], catch_all: bool):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port)); srv.listen(5); srv.settimeout(10)

    def handle(c):
        c.sendall(b"220 mock ESMTP\r\n")
        f = c.makefile("rb")
        while True:
            line = f.readline()
            if not line:
                break
            cmd = line.decode("latin1").strip()
            up = cmd.upper()
            if up.startswith(("HELO", "EHLO")):
                c.sendall(b"250 mock\r\n")
            elif up.startswith("MAIL"):
                c.sendall(b"250 ok\r\n")
            elif up.startswith("RCPT"):
                addr = re.search(r"<(.+?)>", cmd)
                a = addr.group(1).lower() if addr else ""
                ok = catch_all or (a in valid)
                c.sendall(b"250 ok\r\n" if ok else b"550 no such user\r\n")
            elif up.startswith("QUIT"):
                c.sendall(b"221 bye\r\n"); break
            else:
                c.sendall(b"250 ok\r\n")
        c.close()
    while True:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            break
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


def selftest() -> int:
    print("self-test: spinning up mock SMTP servers (no port 25 needed)...")
    ok = True
    # case 1: non-catch-all domain, alice valid, bob invalid
    t1 = threading.Thread(target=_mock_server, args=(2526, {"alice@acme.test"}, False), daemon=True); t1.start()
    time.sleep(0.3)
    r = verify_batch(["alice@acme.test", "bob@acme.test"], "verifier.local", "probe@verifier.local",
                     8, "127.0.0.1", 2526, 0.0)
    rs = {x["email"]: x["status"] for x in r}
    print("  non-catch-all:", rs)
    ok &= rs.get("alice@acme.test") == "valid" and rs.get("bob@acme.test") == "invalid"
    # case 2: catch-all domain -> everything 'catch_all'
    t2 = threading.Thread(target=_mock_server, args=(2527, set(), True), daemon=True); t2.start()
    time.sleep(0.3)
    r2 = verify_batch(["anyone@catchall.test"], "verifier.local", "probe@verifier.local",
                      8, "127.0.0.1", 2527, 0.0)
    print("  catch-all:    ", {x["email"]: x["status"] for x in r2})
    ok &= r2[0]["status"] == "catch_all"
    # case 3: prefilters (role / syntax / disposable) without any connection
    r3 = verify_batch(["info@acme.test", "not-an-email", "x@mailinator.com"], "v", "p@v", 5, None, 25, 0)
    rs3 = {x["email"]: x["status"] for x in r3}
    print("  prefilters:   ", rs3)
    ok &= rs3.get("info@acme.test") == "role" and rs3.get("not-an-email") == "bad_syntax" and rs3.get("x@mailinator.com") == "disposable"
    print("SELF-TEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", help="verify a single address")
    ap.add_argument("--in", dest="inp", help="CSV with an 'email' column")
    ap.add_argument("--out", help="write verdicts CSV")
    ap.add_argument("--helo", default="mail.aureonglobal.de", help="HELO name (a domain you control)")
    ap.add_argument("--mail-from", default="verify@aureonglobal.de", help="MAIL FROM probe address")
    ap.add_argument("--timeout", type=int, default=15)
    ap.add_argument("--port", type=int, default=25)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between domains")
    ap.add_argument("--mx-override", help="force all probes at host[:ignored] (for testing)")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    _RNG.seed(args.seed)

    if args.selftest:
        return selftest()

    emails = []
    if args.email:
        emails = [args.email]
    elif args.inp:
        emails = [r["email"] for r in csv.DictReader(open(args.inp, encoding="utf-8-sig")) if r.get("email")]
    else:
        print("give --email, --in, or --selftest"); return 2

    res = verify_batch(emails, args.helo, args.mail_from, args.timeout, args.mx_override, args.port, args.delay)
    from collections import Counter
    summ = Counter(r["status"] for r in res)
    for r in res[:40]:
        print(f"  {r['status']:<10} {r['email']}  (code={r['code']} mx={r['mx']})")
    print("\nsummary:", dict(summ))
    sendable = sum(summ.get(s, 0) for s in ("valid", "catch_all"))
    print(f"sendable (valid + catch_all): {sendable} / {len(res)}")
    if args.out and res:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["email", "status", "code", "mx", "catch_all"])
            w.writeheader(); w.writerows(res)
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
