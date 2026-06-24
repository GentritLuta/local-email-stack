# -*- coding: utf-8 -*-
"""holding_structure.py — the "Group A" holding-structure variant of the pilot
agreement, as ONE source of truth.

When the CLIENT owns the sending domain (the portal model: the client brings a
domain + grants delegated DNS access), the agreement must say the Client owns the
domain / subdomains / DNS / sending reputation and the Provider holds only a
limited, revocable licence + delegated access. That is the substance of the
redline Mark-eting B.V. requested, and it is the accurate contract for every
portal client who brings their own domain.

This module holds the clause transformations (operating on the Diraya base
template text) parameterised by the client's root domain + a "services" phrase,
so both `scripts/_gen-mark-eting-contract.py` (file artifact) and
`sequences/contract_lib.py` (live portal e-sign) apply IDENTICAL clauses.

    from holding_structure import apply
    html, missing = apply(base_html, root_domain="acme.com")
    if missing:  # any anchor failed to match -> do NOT ship a half-transform
        ...fall back to the standard template...
"""
from __future__ import annotations

# 8.6 (Client-owned) + inserted 8.6A (suspend right) + 8.6B (delegated access).
# Domain-agnostic (references "the domain"), so no parameters.
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


def build_replacements(root_domain: str, services_phrase: str):
    """Return the list of (label, old, new) clause replacements. `old` is byte-exact
    Diraya base text (constant); `new` is the holding-structure wording parameterised
    by the client's root domain + the phrase describing what is being promoted."""
    root = root_domain or "the Client's domain"
    svc = services_phrase or "the Client's services"
    return [
        ("A1 1.1.12",
         '<li><span class="num">1.1.12</span> <em class="term">Outbound Subdomain</em> means each '
         'sending subdomain provisioned, owned, and controlled by the Provider for the purpose of '
         'the Pilot Services pursuant to Schedule 1, including subdomains of the Provider\'s Diraya '
         'pilot domains such as cleardiraya.com, dirayaget.com, diraya.biz, diraya-agency.shop, and '
         'diraya-marketing.shop.</li>',
         '<li><span class="num">1.1.12</span> <em class="term">Outbound Subdomain</em> means each '
         'sending subdomain used for the purpose of the Pilot Services pursuant to Schedule 1, being '
         f'a subdomain of a domain owned and controlled by the Client (including {root}), '
         'which the Client makes available to the Provider for the limited purpose of, and for the '
         'duration of, the Pilot Services.</li>'),
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
         f"warrants that it has authority to authorise the sending of communications promoting {svc} "
         'under the Outbound Subdomains for the purposes contemplated by this Agreement.</li>'),
        ("A4 8.3",
         '<li><span class="num">8.3</span> The Outbound Subdomains, and the sending reputation '
         'accumulated on them, are provisioned, owned, and controlled by the Provider and remain with '
         'the Provider on expiry or termination of this Agreement. The Provider may retire, retain, or '
         'repurpose the Outbound Subdomains after the Term. The Client acquires no right, title, or '
         'interest in the Outbound Subdomains or their accumulated reputation.</li>',
         '<li><span class="num">8.3</span> The Outbound Subdomains, the domain of which they form '
         'part, and the sending reputation accumulated on them are owned and controlled by the Client '
         'and remain with the Client on expiry or termination of this Agreement. The Provider acquires '
         "no right, title, or interest in the Outbound Subdomains, the underlying domain, or their "
         "accumulated reputation, and the Provider's rights are limited to use of the Outbound "
         'Subdomains for the Pilot Services during the Term. On expiry or termination, the Provider '
         'shall cease all use of the Outbound Subdomains and, in accordance with clause 14.4, remove '
         'the DNS records and revoke the sending credentials it published or issued.</li>'),
        ("A5/A6/A7 8.6",
         '<li><span class="num">8.6</span> The Outbound Subdomains are at all times provisioned, '
         'owned, and controlled by the Provider. Nothing in this Agreement transfers, assigns, '
         'licences, or grants any interest in or right over the Outbound Subdomains, or the domains of '
         'which they form part, to the Client, save the benefit of the Pilot Services performed by the '
         'Provider during the Term.</li>',
         NEW_86),
        ("A3 6.1(a)",
         '(a) provision and warm the Outbound Subdomains under the domain of the Client in accordance '
         'with Schedule 1;',
         '(a) provision, warm, configure, and operate the Outbound Subdomains under the Client\'s '
         'domain in accordance with Schedule 1, using the delegated access granted by the Client;'),
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
        ("A9 Sched 1.3",
         '<li>Up to ten (10) Outbound Subdomains provisioned and controlled by the Provider under the '
         "Provider's Diraya pilot domains (cleardiraya.com, dirayaget.com, diraya.biz, "
         'diraya-agency.shop, and diraya-marketing.shop).</li>',
         f'<li>Up to ten (10) Outbound Subdomains under the Client\'s domain ({root}), '
         'provisioned and operated by the Provider for the Pilot Services during the Term. The domain '
         "and subdomains are owned and controlled by the Client; the Provider's use is limited to the "
         'Term.</li>'),
        ("A10 Sched 1.4",
         '<p>For each Outbound Subdomain, the records below shall be published by the Provider under '
         "the Provider's Diraya pilot domains. The Provider may publish additional records technically "
         'necessary for deliverability.</p>',
         '<p>For each Outbound Subdomain, the records below shall be published under the Client\'s '
         'domain by the Provider, using the delegated access granted by the Client pursuant to clause '
         '8.6B. The Provider may specify and publish additional records technically necessary for '
         'deliverability. All such records, and the delegated access, may be removed or revoked by the '
         'Client on expiry or termination, or at any time pursuant to clause 8.6B.</p>'),
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
        # 5.1(b) consistency: without this, "the Provider ... owning, controlling ... those
        # subdomains" directly contradicts the Client-ownership clauses above.
        ("5.1(b) consistency",
         'the Provider being solely responsible for provisioning, owning, controlling, and '
         'authenticating those subdomains and for publishing the DNS records set out in Schedule 1',
         'the Provider being responsible for provisioning, configuring, and authenticating those '
         'subdomains and for publishing the DNS records set out in Schedule 1 using the delegated '
         'access granted by the Client'),
    ]


def apply(html: str, root_domain: str, services_phrase: str = "the Client's services"):
    """Apply the holding-structure clauses to the Diraya base `html`. Returns
    (new_html, missing) where `missing` lists any anchor that did NOT match exactly
    once. If `missing` is non-empty the caller should NOT ship the result (a partial
    transform would be a self-contradictory contract) — fall back to the standard."""
    missing = []
    out = html
    for label, old, new in build_replacements(root_domain, services_phrase):
        if out.count(old) != 1:
            missing.append(label)
            continue
        out = out.replace(old, new)
    return out, missing
