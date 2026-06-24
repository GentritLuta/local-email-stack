# -*- coding: utf-8 -*-
"""Generate the Mark-eting B.V. pilot agreement from the Diraya base.

Two passes:
  PASS 1  Group A redline (holding structure / domain ownership). getmark-eting.com
          is the Client's property; the Provider holds only a limited, revocable
          licence plus delegated DNS access. Body clauses 1.1.12, 5.1(b), 5.2, 6.1(a),
          8.3, 8.6 (+ new 8.6A/8.6B), 14.4(c), Schedule 1.3, 1.4, 1.6(c).
          (Groups B liability-cap and C AI-training warranty are intentionally NOT
          applied; left as Aureon's standard, per the Provider's instruction.)
  PASS 2  The same deterministic client swap used for the other clients
          (parties cell, recital, persona, reference, signature, domain, residual
          tokens, em-dash strip).

Touches only the mark-eting file. No other client's contract is read or written.
Every Group A edit asserts it fired; a full verify runs before the file is written.
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
BASE = REPO / "docs" / "aureon-pilot-agreement-diraya-print.html"
OUT = REPO / "docs" / "aureon-pilot-agreement-mark-eting-print.html"

# ---- Mark-eting client record -------------------------------------------------
C = dict(
    ref="AG MARKETINGBV 2026 01 v1.0",   # matches the portal DB row (make_ref("Mark-eting B.V."))
    entity="Mark-eting B.V.",
    entity_type="a besloten vennootschap (private limited company)",
    office="Heerenveen, Netherlands (full registered address to be confirmed by Client)",
    reg="Company registration number (KvK): (to be provided by Client)",
    jurisdiction="Netherlands",
    business="search engine optimisation and online visibility services for service businesses",
    rep="Mark Eizema, Director",
    email="mark@mark-eting.co",
    persona='"[First name] from Mark-eting"',
    recital=("The Client operates Mark-eting, a provider of search engine optimisation "
             "and online visibility services managed end to end for service businesses, "
             "and is presently developing its client base among such businesses."),
    sig="Mark Eizema", title="Director", place="Heerenveen, Netherlands",
    domains="getmark-eting.com",
)

# ---- Exact base constants (verbatim from the Diraya base) ----------------------
DIRAYA_CELL = '''The Client</div>
        <div class="name">Diraya Inc.</div>
        a corporation<br>
        Registered office: <span class="placeholder">&nbsp;</span> <em>(to be provided by Client)</em><br>
        Company registration number: <span class="placeholder">&nbsp;</span> <em>(to be provided by Client)</em><br>
        Jurisdiction of incorporation: Canada<br>
        Principal business: artificial intelligence engineering services<br>
        Authorised representative: Mohammed El Amine Amoura, Founder<br>
        Email for notices: amoura.ma@diraya.ca'''

DIRAYA_RECITAL = ('The Client operates Diraya, a provider of artificial intelligence '
                  'engineering services to technology companies, and is presently developing '
                  'its client base among early stage technology companies.')

DIRAYA_DOMAINS_INLINE = ("cleardiraya.com, dirayaget.com, diraya.biz, diraya-agency.shop, "
                         "and diraya-marketing.shop")

# ---- PASS 1: Group A redline (operates on the Diraya base, pre-swap) -----------
# Each entry: (label, old, new). `old` is byte-exact base text. The new text is the
# redline "Replace with" wording, written with the Client's own domain.
NEW_86 = (
    '<li><span class="num">8.6</span> The Outbound Subdomains, and the domain of which '
    'they form part, are at all times owned and controlled by the Client. Nothing in this '
    'Agreement transfers, assigns, or grants any interest in or right over the Outbound '
    'Subdomains, or the domain of which they form part, to the Provider, save a limited, '
    'revocable licence to use the Outbound Subdomains for the performance of the Pilot '
    'Services during the Term.</li>\n'
    '      <li><span class="num">8.6A</span> The Client may, at any time and in its sole '
    'discretion, suspend or require the Provider to suspend sending from any or all Outbound '
    'Subdomains where the Client reasonably considers that continued sending may harm the '
    'deliverability or reputation of its domain. The Provider shall comply with any such '
    'request within four (4) hours.</li>\n'
    '      <li><span class="num">8.6B</span> <em class="term">Delegated domain access.</em> '
    "The Client has granted the Provider access credentials to the Client's domain registrar "
    'and/or DNS management environment solely to enable the Provider to publish, configure, '
    'and maintain the DNS records necessary for the Pilot Services. The Provider shall: '
    '(a) use such access only for that purpose; (b) not modify nameserver delegation, '
    'registrant or contact details, domain lock status, or transfer settings, and not '
    'initiate or authorise any transfer of the domain; (c) not create, modify, or delete any '
    'record unrelated to the Pilot Services; (d) keep the credentials confidential and '
    'restrict them to personnel who require them; and (e) on expiry or termination, cease all '
    'use of the access and confirm in writing that it holds no copy of the credentials. The '
    'grant of such access does not transfer, and shall not be construed as transferring, any '
    'ownership of or interest in the domain, which remains the sole property of the Client at '
    'all times. The Client may revoke or rescope the access at any time, including by changing '
    'the credentials, without such revocation constituting a breach of this Agreement.</li>'
)

GROUP_A = [
    # A1 - Definition 1.1.12
    ("A1 1.1.12",
     '<li><span class="num">1.1.12</span> <em class="term">Outbound Subdomain</em> means each '
     'sending subdomain provisioned, owned, and controlled by the Provider for the purpose of '
     'the Pilot Services pursuant to Schedule 1, including subdomains of the Provider\'s Diraya '
     'pilot domains such as cleardiraya.com, dirayaget.com, diraya.biz, diraya-agency.shop, and '
     'diraya-marketing.shop.</li>',
     '<li><span class="num">1.1.12</span> <em class="term">Outbound Subdomain</em> means each '
     'sending subdomain used for the purpose of the Pilot Services pursuant to Schedule 1, being '
     'a subdomain of a domain owned and controlled by the Client (including getmark-eting.com), '
     'which the Client makes available to the Provider for the limited purpose of, and for the '
     'duration of, the Pilot Services.</li>'),
    # A2 - Clause 5.2 (note: writes Mark-eting B.V.'s services directly)
    ("A2 5.2",
     '<li><span class="num">5.2</span> The Provider provisions, owns, and controls the Outbound '
     'Subdomains used for the Pilot Services and is responsible for publishing the DNS records '
     'necessary for deliverability. The Client is not required to own, control, or grant access '
     "to any domain for the Pilot Services. The Client warrants that it has the authority to "
     "authorise the sending of communications promoting Diraya's services under the Outbound "
     'Subdomains for the purposes contemplated by this Agreement.</li>',
     '<li><span class="num">5.2</span> The Outbound Subdomains are subdomains of a domain owned '
     'and controlled by the Client. The Client retains ownership and ultimate control of that '
     'domain, the Outbound Subdomains, and all DNS records and sending reputation associated with '
     'them. For the duration of the Term, the Client grants the Provider a limited, non-exclusive, '
     'revocable right to provision, configure, authenticate, and send from the Outbound '
     'Subdomains, and to publish the DNS records required for deliverability using the access '
     'granted by the Client, for the sole purpose of performing the Pilot Services. The Client '
     "warrants that it has authority to authorise the sending of communications promoting "
     "Mark-eting B.V.'s services under the Outbound Subdomains for the purposes contemplated by "
     'this Agreement.</li>'),
    # A4 - Clause 8.3
    ("A4 8.3",
     '<li><span class="num">8.3</span> The Outbound Subdomains, and the sending reputation '
     'accumulated on them, are provisioned, owned, and controlled by the Provider and remain with '
     'the Provider on expiry or termination of this Agreement. The Provider may retire, retain, or '
     'repurpose the Outbound Subdomains after the Term. The Client acquires no right, title, or '
     'interest in the Outbound Subdomains or their accumulated reputation.</li>',
     '<li><span class="num">8.3</span> The Outbound Subdomains, the domain of which they form '
     'part, and the sending reputation accumulated on them are owned and controlled by the Client '
     'and remain with the Client on expiry or termination of this Agreement. The Provider acquires '
     'no right, title, or interest in the Outbound Subdomains, the underlying domain, or their '
     "accumulated reputation, and the Provider's rights are limited to use of the Outbound "
     'Subdomains for the Pilot Services during the Term. On expiry or termination, the Provider '
     'shall cease all use of the Outbound Subdomains and, in accordance with clause 14.4, remove '
     'the DNS records and revoke the sending credentials it published or issued.</li>'),
    # A5 + A6 + A7 - Clause 8.6 and inserted 8.6A / 8.6B
    ("A5/A6/A7 8.6",
     '<li><span class="num">8.6</span> The Outbound Subdomains are at all times provisioned, '
     'owned, and controlled by the Provider. Nothing in this Agreement transfers, assigns, '
     'licences, or grants any interest in or right over the Outbound Subdomains, or the domains of '
     'which they form part, to the Client, save the benefit of the Pilot Services performed by the '
     'Provider during the Term.</li>',
     NEW_86),
    # A3 - Clause 6.1(a) (substring within the 6.1 list item)
    ("A3 6.1(a)",
     '(a) provision and warm the Outbound Subdomains under the domain of the Client in accordance '
     'with Schedule 1;',
     '(a) provision, warm, configure, and operate the Outbound Subdomains under the Client\'s '
     'domain in accordance with Schedule 1, using the delegated access granted by the Client;'),
    # A8 - Clause 14.4(c) (substring)
    ("A8 14.4(c)",
     '(c) on Client request, the Provider shall provide reasonable assistance to remove DKIM keys, '
     'modify or remove DNS records published by or on behalf of the Provider, and revoke any '
     'sending credentials issued by the Provider for the Outbound Subdomains;',
     '(c) the Provider shall, whether or not requested, cease all use of the Outbound Subdomains '
     'and, within seven (7) calendar days, remove all DKIM keys and any other DNS records it '
     'published or caused to be published, revoke all sending credentials it issued for the '
     'Outbound Subdomains, and confirm the same to the Client in writing, so that full and '
     'unencumbered control of the Outbound Subdomains and the underlying domain remains with the '
     'Client;'),
    # A9 - Schedule 1.3 bullet
    ("A9 Sched 1.3",
     '<li>Up to ten (10) Outbound Subdomains provisioned and controlled by the Provider under the '
     "Provider's Diraya pilot domains (cleardiraya.com, dirayaget.com, diraya.biz, "
     'diraya-agency.shop, and diraya-marketing.shop).</li>',
     '<li>Up to ten (10) Outbound Subdomains under the Client\'s domain (getmark-eting.com), '
     'provisioned and operated by the Provider for the Pilot Services during the Term. The domain '
     "and subdomains are owned and controlled by the Client; the Provider's use is limited to the "
     'Term.</li>'),
    # A10 - Schedule 1.4 intro
    ("A10 Sched 1.4",
     '<p>For each Outbound Subdomain, the records below shall be published by the Provider under '
     "the Provider's Diraya pilot domains. The Provider may publish additional records technically "
     'necessary for deliverability.</p>',
     '<p>For each Outbound Subdomain, the records below shall be published under the Client\'s '
     'domain by the Provider, using the delegated access granted by the Client pursuant to clause '
     '8.6B. The Provider may specify and publish additional records technically necessary for '
     'deliverability. All such records, and the delegated access, may be removed or revoked by the '
     'Client on expiry or termination, or at any time pursuant to clause 8.6B.</p>'),
    # A11 - Schedule 1.6(c) (substring)
    ("A11 Sched 1.6(c)",
     '(c) on Client request, deliver instructions for DKIM key removal, confirm in writing that '
     'all Provider issued sending credentials for the Outbound Subdomains have been revoked, and '
     'provide technical instructions for the removal of any DNS records published by or on behalf '
     'of the Provider that the Client wishes to remove.',
     '(c) cease all use of the Outbound Subdomains and, within seven (7) calendar days, remove (or '
     'where its access does not permit, deliver clear instructions enabling the Client to remove) '
     'all DNS records and DKIM keys it published or caused to be published, and confirm in writing '
     'that all sending credentials it issued for the Outbound Subdomains have been revoked, so '
     'that full control of the Outbound Subdomains and the underlying domain remains with the '
     'Client.'),
    # 5.1(b) consistency fix (redline omitted it; leaving "owning, controlling" here would
    # directly contradict A2/A5/A8). Disclosed in the run report.
    ("5.1(b) consistency",
     'the Provider being solely responsible for provisioning, owning, controlling, and '
     'authenticating those subdomains and for publishing the DNS records set out in Schedule 1',
     'the Provider being responsible for provisioning, configuring, and authenticating those '
     'subdomains and for publishing the DNS records set out in Schedule 1 using the delegated '
     'access granted by the Client'),
]

# Single source of truth: the holding-structure clauses are canonically defined in
# sequences/holding_structure.py (which the live portal contract_lib.py uses). Source
# GROUP_A from there so the file artifact and the portal can never diverge. The literal
# above is kept readable but enforced identical to the shared module.
import sys as _hs_sys
_hs_sys.path.insert(0, str(REPO / "sequences"))
from holding_structure import build_replacements as _hs_reps  # noqa: E402
assert GROUP_A == _hs_reps("getmark-eting.com", "Mark-eting B.V.'s services"), \
    "GROUP_A drifted from sequences/holding_structure.py — edit the shared module, not this copy"
GROUP_A = _hs_reps("getmark-eting.com", "Mark-eting B.V.'s services")


def build_cell(c: dict) -> str:
    return (f'''The Client</div>
        <div class="name">{c["entity"]}</div>
        {c["entity_type"]}<br>
        Registered office: {c["office"]}<br>
        {c["reg"]}<br>
        Jurisdiction of incorporation: {c["jurisdiction"]}<br>
        Principal business: {c["business"]}<br>
        Authorised representative: {c["rep"]}<br>
        Email for notices: {c["email"]}''')


def main() -> int:
    s = BASE.read_text(encoding="utf-8")
    errors = []

    # PASS 1 - Group A
    for label, old, new in GROUP_A:
        n = s.count(old)
        if n != 1:
            errors.append(f"Group A [{label}] matched {n} times (expected 1)")
            continue
        s = s.replace(old, new)
    if errors:
        for e in errors:
            print(f"  FAIL {e}")
        raise SystemExit("Aborted: Group A anchors did not match exactly. No file written.")

    # PASS 2 - client swap (same logic as scripts/_gen-contracts.py)
    assert DIRAYA_CELL in s, "Diraya parties cell not found"
    s = s.replace(DIRAYA_CELL, build_cell(C))
    assert DIRAYA_RECITAL in s, "Diraya recital not found"
    s = s.replace(DIRAYA_RECITAL, C["recital"])
    s = s.replace('"[First name] from Diraya"', C["persona"])
    s = s.replace("AG DIRAYA 2026 01 v1.0", C["ref"])
    s = s.replace('<div class="sig-entity">Diraya Inc.</div>',
                  f'<div class="sig-entity">{C["entity"]}</div>')
    s = s.replace('<span class="sig-line filled">Mohammed El Amine Amoura</span>',
                  f'<span class="sig-line filled">{C["sig"]}</span>')
    s = s.replace('<span class="label">Title</span><span class="sig-line filled">Founder</span>',
                  f'<span class="label">Title</span><span class="sig-line filled">{C["title"]}</span>')
    s = s.replace('<div class="sig-field"><span class="label">Place of signature</span><span class="sig-line">&nbsp;</span></div>',
                  f'<div class="sig-field"><span class="label">Place of signature</span><span class="sig-line filled">{C["place"]}</span></div>', 1)
    s = s.replace(DIRAYA_DOMAINS_INLINE, C["domains"])
    for tok, repl in [("Diraya Inc.", C["entity"]), ("Diraya", C["entity"]),
                      ("Mohammed El Amine Amoura", C["sig"]), ("Mohammed", C["sig"]),
                      ("amoura.ma@diraya.ca", C["email"]), ("diraya.ca", C["entity"]),
                      ("Name: Mohammed El Amine Amoura", f"Name: {C['sig']}")]:
        s = s.replace(tok, repl)
    s = s.replace(" — ", " - ").replace("—", "-").replace(" – ", " - ").replace("–", "-")

    # VERIFY
    checks = {
        "base leak: Diraya": "diraya" in s.lower(),
        "base leak: Mohammed/amoura": ("mohammed" in s.lower() or "amoura" in s.lower()),
        "Provider-owned subdomain phrase remains": "owned, and controlled by the Provider" in s,
        "Provider's pilot domains phrase remains": "Provider's Mark-eting B.V." in s or "Provider's Diraya" in s,
        "domain missing": "getmark-eting.com" not in s,
        "8.6A missing": '<span class="num">8.6A</span>' not in s,
        "8.6B missing": '<span class="num">8.6B</span>' not in s,
        "em dash present": ("—" in s or "–" in s),
    }
    failed = [k for k, bad in checks.items() if bad]
    status = "OK" if not failed else "FAIL"
    OUT.write_text(s, encoding="utf-8")
    print(f"  [{status}] mark-eting  groupA={len(GROUP_A)} applied  written={OUT.name}")
    if failed:
        for f in failed:
            print(f"    - {f}")
        return 1
    print("    getmark-eting.com present, Client-owned clauses in, 8.6A/8.6B inserted, "
          "no Diraya/em-dash leaks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
