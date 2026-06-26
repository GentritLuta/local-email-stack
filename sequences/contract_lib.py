# -*- coding: utf-8 -*-
"""contract_lib.py — generate + seal a client pilot agreement from onboarding
answers. Generalizes scripts/_gen-contracts.py (which hardcoded 4 clients) into
a reusable function driven by onboarding_submissions.raw_answers.

  generate_contract(answers, ref) -> html   # the DRAFT agreement to present + sign
  apply_signature(html, name, title, place, date_str, esign_panel_html) -> html
  esign_audit_panel(...) -> html            # the legal click-to-sign audit block

Provider side (Aureon Global L.L.C. / Gentrit Luta) and all body clauses are
inherited verbatim from the Diraya base template. Only client-specific strings
swap. Guardrails preserved: no base-template leaks, no em dashes.
"""
from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path

# Holding-structure (Client-owns-domain) clause variant — shared single source of
# truth, also used by scripts/_gen-mark-eting-contract.py.
try:
    from holding_structure import apply as _apply_holding_structure
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from holding_structure import apply as _apply_holding_structure

REPO = Path(__file__).resolve().parent.parent
BASE = REPO / "docs" / "aureon-pilot-agreement-diraya-print.html"
SOCIAL_BASE = REPO / "docs" / "aureon-pilot-agreement-social-base.html"
BOTH_BASE = REPO / "docs" / "aureon-pilot-agreement-both-base.html"
INPUTS_JSON = REPO / "contracts" / "client-contract-inputs.json"

# ─── The Diraya base strings we swap out (mirror _gen-contracts.py) ──────────
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


def _nodash(s: str) -> str:
    return (s or "").replace(" — ", " - ").replace("—", "-").replace(" – ", " - ").replace("–", "-")


def _esc(s: str) -> str:
    return _html.escape((s or "").strip())


def _short_business(offer: str | None) -> str:
    """A concise 'principal business' descriptor from the onboarding 'offer'
    field, which is usually a multi-sentence sales pitch. Take the first
    sentence, and if it is still long, the first clause before a comma. This
    keeps the contract's company block to the business TYPE, not the marketing
    copy (e.g. 'SEO and online visibility', not the whole funnel description)."""
    o = (offer or "").strip().rstrip(".")
    if not o:
        return "its services"
    p = o.find(". ")
    sent = o[:p].strip() if p != -1 else o
    if len(sent.split()) > 14:
        cpos = sent.find(",")
        if cpos != -1:
            sent = sent[:cpos].strip()
    return sent or "its services"


# ─── Per-client placeholder fill ────────────────────────────────────────────
# Label-anchored, idempotent fill for the fields the onboarding form does not
# capture (registration number / registered office / schedule contact email +
# reply endpoint). Single source of truth: scripts/fill-contract-placeholders.py
# imports these so the legal fill logic never diverges.
_FILL_MARKER = (
    r'(?:'
    r'<span class="placeholder">&nbsp;</span>(?:\s*<em>\([^<]*\)</em>)?'   # styled blank, optional (note)
    r'|\(to be provided by Client\)'                                        # plain
    r'|[^<\n]*?to be confirmed by Client\)'                                 # partial text ending in this note
    r')'
)
_FILL_LABELS = {
    "registered_office": r'(Registered office:\s*)',
    "registration_number": r'((?:Company registration number(?:\s*\(KvK\))?|Employer Identification Number \(EIN\)):\s*)',
    "notices_email": r'(Email for notices:\s*)',
    "authorised_contact_email": r'(\bEmail:\s*)',
    "reply_endpoint": r'(Endpoint:\s*)',
}


def fill_client_inputs(html_str: str, rec: dict) -> tuple[str, list[str]]:
    """Fill the label-anchored placeholders from a client-contract-inputs record.
    Idempotent: only fills a field that still shows a placeholder marker, and only
    when the record carries a non-empty value. Returns (html, filled_field_names)."""
    filled: list[str] = []
    for field, label_re in _FILL_LABELS.items():
        val = (rec.get(field) or "").strip()
        if not val:
            continue
        pat = re.compile(label_re + _FILL_MARKER)
        new_html, n = pat.subn(lambda m: m.group(1) + _html.escape(val, quote=False), html_str, count=1)
        if n:
            html_str = new_html
            filled.append(field)
    return html_str, filled


def _client_inputs_for(company: str) -> dict | None:
    """Find the contracts/client-contract-inputs.json record for this Client,
    matched on each entry's 'company' field (exact, case-insensitive)."""
    company = (company or "").strip().lower()
    if not company or not INPUTS_JSON.exists():
        return None
    try:
        data = json.loads(INPUTS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None
    for slug, rec in data.items():
        if slug.startswith("_") or not isinstance(rec, dict):
            continue
        if (rec.get("company") or "").strip().lower() == company:
            return rec
    return None


def derive_contract_fields(a: dict) -> dict:
    """Map onboarding raw_answers -> the client-cell + recital + signature fields.
    Everything the agreement needs about the Client comes from the form."""
    company = (a.get("company") or "Client").strip()
    website = (a.get("website") or "").strip()
    email = (a.get("contact_email") or a.get("reply_to") or "").strip()
    icp = (a.get("icp") or "").strip().rstrip(".")
    rep = (a.get("rep") or a.get("signer_name") or "").strip()
    title = (a.get("rep_title") or a.get("signer_title") or "Founder").strip()
    # Representation chain. When the signatory acts for the Client THROUGH one or more
    # intermediate entities (e.g. a holding company that is the statutory director, which
    # in turn acts through its own managing director), the full chain must appear in BOTH
    # the parties cell and the execution block, never collapsed to name+title. Captured
    # from the onboarding `rep_chain` answer, e.g.:
    #   "represented by its sole director, ME Holding B.V., in turn represented by its managing director"
    # Empty for the common single-tier case (a natural person signs directly).
    rep_chain = (a.get("rep_chain") or a.get("representation") or "").strip().rstrip(",").strip()
    office = (a.get("office") or "(to be provided by Client)").strip()
    jurisdiction = (a.get("jurisdiction") or "(to be provided by Client)").strip()
    reg = (a.get("registration") or "Company registration number: (to be provided by Client)").strip()
    place = (a.get("place") or jurisdiction).strip()
    domains = (a.get("sending_root") or "").strip()

    business = _short_business(a.get("offer"))
    recital = (f"The Client operates {company}, a provider of {business}"
               + (f" to {icp}" if icp else "")
               + ", and is presently developing its client base"
               + (f" among {icp}" if icp else "") + ".")
    persona = f'"[First name] from {company}"'
    if rep and rep_chain:
        cell_rep = f"{rep_chain}, {rep}"   # full chain: "represented by its sole director ..., Mark Eizema"
    elif rep:
        cell_rep = f"{rep}, {title}"
    else:
        cell_rep = "(to be provided by Client)"
    return dict(
        entity=company, entity_type="a company", office=office, reg=reg,
        jurisdiction=jurisdiction, business=business, rep=cell_rep,
        email=email, recital=_nodash(recital), persona=persona,
        sig=rep or "(to be provided by Client)", title=title, place=place, rep_chain=rep_chain,
        domains=domains or "(client sending domains)", website=website,
    )


def _build_cell(c: dict) -> str:
    return (f'''The Client</div>
        <div class="name">{_esc(c["entity"])}</div>
        {c["entity_type"]}<br>
        Registered office: {_esc(c["office"])}<br>
        {_esc(c["reg"])}<br>
        Jurisdiction of incorporation: {_esc(c["jurisdiction"])}<br>
        Principal business: {_esc(c["business"])}<br>
        Authorised representative: {_esc(c["rep"])}<br>
        Email for notices: {_esc(c["email"])}''')


def generate_contract(a: dict, ref: str) -> str:
    """Build the DRAFT agreement HTML for these onboarding answers."""
    # Route to the agreement matching the service: social-only -> social base;
    # both -> combined email + social base; email (or unset) -> email base.
    _st = a.get("service_type")
    if _st == "social" and SOCIAL_BASE.exists():
        base_path = SOCIAL_BASE
    elif _st == "both" and BOTH_BASE.exists():
        base_path = BOTH_BASE
    else:
        base_path = BASE
    if not base_path.exists():
        raise FileNotFoundError(f"base contract template missing: {base_path}")
    c = derive_contract_fields(a)
    s = base_path.read_text(encoding="utf-8")

    # 0. Holding-structure variant: when the Client brings/owns the sending domain
    # (the portal model — client provides a domain + delegated DNS access), the
    # agreement must reflect Client ownership of the domain, subdomains, DNS, and
    # sending reputation, with the Provider holding only a limited, revocable
    # licence + delegated access. Applied BEFORE the client swaps (its anchors are
    # the Diraya base text). Opt out per client with answers["provider_owns_domain"]=true
    # (the rare case where Aureon provisions the domain on its own infrastructure).
    root = (a.get("sending_root") or "").strip()
    if root and not a.get("provider_owns_domain"):
        svc = (f"{c['entity']}'s services"
               if c.get("entity") and c["entity"] != "Client" else "the Client's services")
        s2, missing = _apply_holding_structure(s, root_domain=root, services_phrase=svc)
        if missing:
            print(f"  ! holding-structure anchors not matched {missing}; using standard template")
        else:
            s = s2

    # 1. Parties client cell (wholesale).
    s = s.replace(DIRAYA_CELL, _build_cell(c))
    # 2. Recital B.
    s = s.replace(DIRAYA_RECITAL, c["recital"])
    # 3. Persona form.
    s = s.replace('"[First name] from Diraya"', c["persona"])
    # 4. Reference (title page + footer), all occurrences.
    s = s.replace("AG DIRAYA 2026 01 v1.0", ref)
    # 5. Client signature block entity + (representation chain) + name + title.
    # When the Client signs THROUGH an intermediate entity, reproduce the full chain
    # in the execution block so the signatory's capacity (q.q.) is unambiguous, instead
    # of collapsing it to a bare name + title. Single-tier clients render unchanged.
    sig_entity = f'<div class="sig-entity">{_esc(c["entity"])}</div>'
    if c.get("rep_chain"):
        sig_entity += ('\n        <div class="sig-rep" style="font-size:9.5pt;margin:1pt 0 5pt;line-height:1.4">'
                       f'{_esc(c["rep_chain"])}:</div>')
    s = s.replace('<div class="sig-entity">Diraya Inc.</div>', sig_entity)
    s = s.replace('<span class="sig-line filled">Mohammed El Amine Amoura</span>',
                  f'<span class="sig-line filled">{_esc(c["sig"])}</span>')
    s = s.replace(
        '<div class="sig-field"><span class="label">Title</span><span class="sig-line filled">Founder</span></div>\n          <div class="sig-field"><span class="label">Date</span><span class="sig-line">&nbsp;</span></div>\n          <div class="sig-field"><span class="label">Signature</span><span class="sig-line">&nbsp;</span></div>\n          <div class="sig-field"><span class="label">Place of signature</span><span class="sig-line">&nbsp;</span></div>',
        f'<div class="sig-field"><span class="label">Title</span><span class="sig-line filled">{_esc(c["title"])}</span></div>\n'
        f'          <div class="sig-field"><span class="label">Date</span><span class="sig-line">&nbsp;</span></div>\n'
        f'          <div class="sig-field"><span class="label">Signature</span><span class="sig-line">&nbsp;</span></div>\n'
        f'          <div class="sig-field"><span class="label">Place of signature</span><span class="sig-line">&nbsp;</span></div>',
        1)
    # 5b. Diraya sending domains (clause 1.1.12 + Schedule 1) -> client's.
    s = s.replace(DIRAYA_DOMAINS_INLINE, _esc(c["domains"]))
    # 6. Residual Diraya tokens -> this client.
    for tok, repl in [("Diraya Inc.", c["entity"]), ("Diraya", c["entity"]),
                      ("Mohammed El Amine Amoura", c["sig"]), ("Mohammed", c["sig"]),
                      ("amoura.ma@diraya.ca", c["email"]), ("diraya.ca", c["entity"])]:
        s = s.replace(tok, _esc(repl))
    # 7. Governing law, forum, and Business Day follow the CLIENT's own jurisdiction
    #    (firm policy: contract jurisdiction is always where the Client's company is
    #    situated). Taken from the onboarding "jurisdiction" answer. The LCIA London
    #    arbitration is replaced with the exclusive jurisdiction of the Client's courts,
    #    and the arbitration-only sub-clauses (20.4 costs, 20.5 proceedings
    #    confidentiality, 20.6 New York Convention) are dropped.
    import re as _re
    juris = (a.get("jurisdiction") or "").strip() or "the Republic of Kosovo"
    je = _esc(juris)
    s = s.replace("the laws of <strong>England and Wales</strong>", f"the laws of <strong>{je}</strong>")
    s = s.replace("a day other than a Saturday, Sunday, or public holiday in England and Wales",
                  f"a day other than a Saturday, Sunday, or public holiday in {je}")
    s = s.replace("clause 8 (Data, Intellectual Property, Domain, and Reputation)", "clause 8")
    # No arbitration anywhere now, so drop the stray "any arbitration" in the
    # service-of-process limb of the notices clause.
    s = s.replace("any legal action or, where applicable, any arbitration or other method of dispute resolution",
                  "any legal action or other method of dispute resolution")
    s = _re.sub(
        r'<li><span class="num">20\.2</span>.*?</li>',
        ('<li><span class="num">20.2</span> <em class="term">Jurisdiction.</em> The courts of '
         f'<strong>{je}</strong> shall have exclusive jurisdiction to settle any dispute or claim '
         '(including non contractual disputes or claims) arising out of or in connection with this '
         'Agreement, its subject matter, or its formation, and each party irrevocably submits to the '
         'exclusive jurisdiction of those courts.</li>'),
        s, count=1, flags=_re.S)
    s = s.replace(
        "without thereby waiving the obligation to arbitrate any underlying dispute, and without "
        "prejudice to the powers of the arbitrator under the LCIA Rules.",
        "without prejudice to any other remedy available to it.")
    for _n in ("20.4", "20.5", "20.6"):
        s = _re.sub(r'\s*<li><span class="num">' + _n + r'</span>.*?</li>', '', s, count=1, flags=_re.S)
    # 6b. Fill per-client placeholder inputs (registration number / registered
    # office / schedule contact email + reply endpoint) from
    # contracts/client-contract-inputs.json, matched by company name. This makes a
    # fresh regeneration COMPLETE on its own; before, these were hand-patched and
    # silently lost whenever the client re-submitted. Idempotent + a no-op when no
    # matching record exists, so it never regresses an unmatched client.
    _rec = _client_inputs_for(a.get("company", ""))
    if _rec:
        s, _ = fill_client_inputs(s, _rec)
    # 7. No em/en dashes anywhere.
    s = _nodash(s)
    return s


def verify_clean(html: str) -> list[str]:
    """Return a list of leak/dash problems (empty == clean)."""
    problems = []
    for t in ["Diraya", "Mohammed", "amoura", "Sales Methodology Hub",
              "Founder Academy", "Ashraf", "Tilbury"]:
        if t.lower() in html.lower():
            problems.append(f"base_leak:{t}")
    if "—" in html or "–" in html:
        problems.append("em_dash")
    return problems


def esign_audit_panel(*, signer_name: str, signer_email: str, signed_at: str,
                      signer_ip: str, user_agent: str, sha256: str, ref: str) -> str:
    """The legal click-to-sign evidence block appended to the sealed contract."""
    rows = [
        ("Signed by", f"{_esc(signer_name)} ({_esc(signer_email)})"),
        ("Agreement reference", _esc(ref)),
        ("Consent", "The signer checked: I have read this agreement and agree to be legally bound by it."),
        ("Signed at (UTC)", _esc(signed_at)),
        ("Signer IP address", _esc(signer_ip)),
        ("Signer device", _esc(user_agent)),
        ("Document integrity (SHA-256)", _esc(sha256)),
    ]
    trs = "\n".join(
        f'<tr><td style="padding:4pt 12pt 4pt 0;font-weight:700;white-space:nowrap;vertical-align:top">{k}</td>'
        f'<td style="padding:4pt 0;word-break:break-all">{v}</td></tr>'
        for k, v in rows)
    return _nodash(f'''
<div style="page-break-before:always"></div>
<div style="margin-top:24pt;border:1.5pt solid #111;padding:18pt 20pt;font-size:10pt;line-height:1.5">
  <div style="font-size:12pt;font-weight:700;letter-spacing:.5pt;text-transform:uppercase;margin-bottom:10pt">
    Electronic signature certificate</div>
  <p style="margin:0 0 12pt 0">This agreement was executed electronically. The Client adopted the typed
  signature below as their electronic signature, intending it to have the same legal effect as a
  handwritten signature. The following audit record was captured at the time of signing.</p>
  <table style="border-collapse:collapse;width:100%">{trs}</table>
  <p style="margin:12pt 0 0 0;font-size:8.5pt;color:#444">Aureon Global L.L.C. retains this certificate as
  evidence of execution. Any modification to the agreement text invalidates the SHA-256 integrity hash above.</p>
</div>''')


def apply_signature(html: str, *, signer_name: str, signer_title: str, place: str,
                    date_str: str, audit_panel_html: str) -> str:
    """Fill the Client signature block (Date + Signature) and append the audit panel.
    The Name/Title were already set at draft time from the form."""
    # Fill the Client Date + Signature lines (the two blank sig-line cells in the
    # Client column). The Client column is the SECOND occurrence of the blank
    # Date/Signature pair; the Provider column is the first and stays blank
    # (Aureon counter-signs out of band).
    blank_date = '<div class="sig-field"><span class="label">Date</span><span class="sig-line">&nbsp;</span></div>'
    blank_sig = '<div class="sig-field"><span class="label">Signature</span><span class="sig-line">&nbsp;</span></div>'
    blank_place = '<div class="sig-field"><span class="label">Place of signature</span><span class="sig-line">&nbsp;</span></div>'
    filled_date = f'<div class="sig-field"><span class="label">Date</span><span class="sig-line filled">{_esc(date_str)}</span></div>'
    filled_sig = f'<div class="sig-field"><span class="label">Signature</span><span class="sig-line filled">/s/ {_esc(signer_name)} (e-signed)</span></div>'
    filled_place = f'<div class="sig-field"><span class="label">Place of signature</span><span class="sig-line filled">{_esc(place)}</span></div>'

    # Replace ONLY the client-side (2nd) Date/Signature, and the blank Place.
    # The client Date is the 2nd blank_date; Signature the 2nd blank_sig.
    def replace_second(hay: str, needle: str, repl: str) -> str:
        first = hay.find(needle)
        if first == -1:
            return hay
        second = hay.find(needle, first + len(needle))
        if second == -1:
            return hay
        return hay[:second] + repl + hay[second + len(needle):]

    html = replace_second(html, blank_date, filled_date)
    html = replace_second(html, blank_sig, filled_sig)
    html = html.replace(blank_place, filled_place, 1)  # only the client place is blank
    # Append the audit certificate at the end of the document body.
    if "</body>" in html:
        html = html.replace("</body>", audit_panel_html + "\n</body>", 1)
    else:
        html = html + audit_panel_html
    return _nodash(html)


def apply_counter_signature(html: str, *, signer_name: str, date_str: str) -> str:
    """Fill the PROVIDER signature block (Aureon Global) AFTER the client has signed.
    By that point the client's Date/Signature (the 2nd pair) are already filled, so the
    only remaining blank Date/Signature pair is the Provider's (the 1st column). The
    Provider Name/Title/Place are set at draft time, so we only stamp Date + Signature.
    This is what makes the agreement fully executed by both parties."""
    blank_date = '<div class="sig-field"><span class="label">Date</span><span class="sig-line">&nbsp;</span></div>'
    blank_sig = '<div class="sig-field"><span class="label">Signature</span><span class="sig-line">&nbsp;</span></div>'
    filled_date = f'<div class="sig-field"><span class="label">Date</span><span class="sig-line filled">{_esc(date_str)}</span></div>'
    filled_sig = f'<div class="sig-field"><span class="label">Signature</span><span class="sig-line filled">/s/ {_esc(signer_name)} (e-signed)</span></div>'
    html = html.replace(blank_date, filled_date, 1)  # first remaining blank = Provider
    html = html.replace(blank_sig, filled_sig, 1)
    return _nodash(html)


_CONSENT_TEXT = "I have read this agreement and agree to be legally bound by it."


def completion_certificate(*, contract_ref: str, contract_id: str, sha256: str, prepared_at: str,
                           client_name: str, client_email: str, client_title: str,
                           client_signed_at: str, client_ip: str, client_ua: str,
                           provider_name: str, provider_title: str, provider_signed_at: str,
                           consent_text: str = _CONSENT_TEXT) -> str:
    """The court-defensible Certificate of Completion appended to a fully-executed
    agreement, modelled on DocuSign/Dropbox Sign. Records BOTH signers (intent, consent,
    attribution, timestamps, IP/device), the document integrity hash, the signing-event
    timeline, and the ESIGN/UETA/eIDAS legal basis. A copy is delivered to every party."""
    def _r(k, v):
        return (f'<tr><td style="padding:3pt 14pt 3pt 0;color:#475569;white-space:nowrap;vertical-align:top">{_esc(k)}</td>'
                f'<td style="padding:3pt 0;word-break:break-word">{_esc(v)}</td></tr>')

    def _signer(role, name, email, title, signed, ip, ua):
        rows = _r("Name", name)
        if email:
            rows += _r("Email", email)
        rows += _r("Signing capacity", title)
        rows += _r("Intent + consent", f'Adopted a typed electronic signature with intent to be bound, and accepted the statement: "{consent_text}"')
        rows += _r("Signed at (UTC)", signed)
        if ip:
            rows += _r("IP address", ip)
        if ua:
            rows += _r("Device / user agent", ua)
        return (f'<div style="margin:0 0 12pt"><div style="font-weight:700;font-size:10.5pt;margin-bottom:3pt">{_esc(role)}</div>'
                f'<table style="border-collapse:collapse;font-size:9pt;width:100%">{rows}</table></div>')

    events = "".join(f'<li>{_esc(t)}</li>' for t in (
        f"Agreement prepared (UTC): {prepared_at}",
        f"Client signed (UTC): {client_signed_at}",
        f"Provider counter-signed (UTC): {provider_signed_at}",
        f"Fully executed by both parties (UTC): {provider_signed_at}",
    ))
    head = (_r("Agreement", contract_ref) + _r("Envelope ID", contract_id)
            + _r("Document SHA-256", sha256))
    return _nodash(f'''
<div style="page-break-before:always"></div>
<div style="margin-top:20pt;border:1.5pt solid #111;padding:18pt 20pt;font-size:10pt;line-height:1.5">
  <div style="font-size:13pt;font-weight:700;text-transform:uppercase;letter-spacing:.5pt;margin-bottom:10pt">Certificate of Completion</div>
  <p style="margin:0 0 12pt">This certificate evidences the electronic execution of the agreement below by both parties. A copy of the fully executed agreement and this certificate has been delivered to every party by email and is retained by Aureon Global L.L.C.</p>
  <table style="border-collapse:collapse;font-size:9pt;margin:0 0 14pt">{head}</table>
  {_signer("Client signer", client_name, client_email, client_title, client_signed_at, client_ip, client_ua)}
  {_signer("Provider signer", provider_name, "", provider_title, provider_signed_at, "", "")}
  <div style="font-weight:700;margin:6pt 0 3pt">Signing events</div>
  <ul style="margin:0 0 14pt;padding-left:18pt;font-size:9pt">{events}</ul>
  <p style="font-size:8.5pt;color:#444;margin:0 0 6pt"><strong>Integrity.</strong> The SHA-256 hash above is computed over the exact agreement text the parties agreed to. Any later alteration to that text changes the hash, so tampering is detectable.</p>
  <p style="font-size:8.5pt;color:#444;margin:0 0 6pt"><strong>Legal basis.</strong> This agreement was executed electronically. Each party expressed intent to be bound and consented to transact electronically, and each signature is attributable to its signer by the record above. The agreement is enforceable under the United States ESIGN Act (15 U.S.C. ch. 96) and the Uniform Electronic Transactions Act (UETA), and under EU Regulation 910/2014 (eIDAS) Article 25(1), by which an electronic signature is not denied legal effect or admissibility as evidence solely because it is electronic. This is a business-to-business agreement; the consumer disclosure regime does not apply.</p>
  <p style="font-size:8.5pt;color:#444;margin:0"><strong>Retention.</strong> Each party has received and may retain a copy of the fully executed agreement and this certificate.</p>
</div>''')


def make_ref(company: str) -> str:
    """AG ACME 2026 01 v1.0 — uppercase, alnum-only company token."""
    tok = re.sub(r"[^A-Za-z0-9]+", "", company).upper()[:12] or "CLIENT"
    return f"AG {tok} 2026 01 v1.0"
