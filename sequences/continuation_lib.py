# -*- coding: utf-8 -*-
"""continuation_lib.py — generate the CONTINUATION agreement that follows the
3-month pilot.

Terms (per the operator, PLACEHOLDER — review before relying on it):
  • 10% commission on attributed revenue
  • EUR 500 / month retainer
  • 12-month term (lock-up)
  • Governed by the CLIENT's own jurisdiction (so debts are enforceable where
    the Client is incorporated)

This is a self-contained agreement (not the pilot template). It reuses the
client fields derived from onboarding answers via contract_lib.derive_contract_fields,
and the same e-sign audit panel + signature application on seal.

  generate_continuation(answers, ref) -> html   # DRAFT to present + sign

NOTE: marked with a visible "DRAFT — FOR REVIEW" banner until the operator
confirms the wording. Remove REVIEW_BANNER once approved.
"""
from __future__ import annotations
from pathlib import Path

import sys
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from contract_lib import derive_contract_fields, _esc, _nodash  # noqa: E402

# Visible placeholder banner — DELETE this line's content (set to "") once the
# operator has reviewed and approved the continuation terms.
REVIEW_BANNER = (
    '<div style="background:#fff3cd;border:1px solid #d4af37;color:#664d03;'
    'padding:10px 14px;border-radius:8px;margin:0 0 18px;font-size:12px;font-weight:600">'
    'DRAFT FOR REVIEW - continuation terms are a placeholder pending operator approval.'
    '</div>'
)

RETAINER_EUR = 500
COMMISSION_PCT = 10
TERM_MONTHS = 12


def make_continuation_ref(company: str) -> str:
    import re
    tok = re.sub(r"[^A-Za-z0-9]+", "", company or "client").upper()[:12] or "CLIENT"
    return f"AG {tok} CONT 2026 v1.0"


def generate_continuation(a: dict, ref: str) -> str:
    """Build the DRAFT continuation agreement HTML for these onboarding answers."""
    c = derive_contract_fields(a)
    entity = c["entity"]
    juris = c["jurisdiction"]
    rep = c["rep"]
    email = c["email"]
    office = c["office"]
    business = c["business"]

    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{_esc(ref)}</title>
<style>
  body {{ font-family: Inter, Arial, sans-serif; color:#111; line-height:1.55;
         max-width: 820px; margin: 0 auto; padding: 40px 48px; }}
  h1 {{ font-size: 24px; font-weight: 800; letter-spacing:-.4px; margin:0 0 4px; }}
  h2 {{ font-size: 15px; font-weight: 800; margin: 26px 0 8px; }}
  .ref {{ color:#666; font-size:12px; margin-bottom: 20px; }}
  .parties {{ display:flex; gap:24px; margin: 18px 0 8px; }}
  .cell {{ flex:1; border:1px solid #e3e3e3; border-radius:10px; padding:14px 16px; font-size:13px; }}
  .cell .role {{ color:#888; font-size:11px; text-transform:uppercase; letter-spacing:.5px; }}
  .cell .name {{ font-weight:700; font-size:15px; margin:2px 0 6px; }}
  ol {{ padding-left: 20px; }} li {{ margin: 6px 0; }}
  .terms {{ background:#faf7ef; border:1px solid #ecdcae; border-radius:10px; padding:14px 18px; margin:12px 0; font-size:14px; }}
  .terms b {{ color:#7a5c00; }}
  .sig {{ display:flex; gap:24px; margin-top:30px; }}
  .sig .box {{ flex:1; border-top:1px solid #333; padding-top:6px; font-size:12px; color:#555; }}
  .small {{ font-size:11px; color:#888; margin-top:24px; }}
</style></head>
<body>
{REVIEW_BANNER}
<h1>AUREON Global - Continuation Services Agreement</h1>
<div class="ref">Reference: {_esc(ref)}</div>

<div class="parties">
  <div class="cell">
    <div class="role">The Provider</div>
    <div class="name">Aureon Global L.L.C.</div>
    Authorised representative: Gentrit Luta<br>
    Email for notices: info@aureonglobal.de
  </div>
  <div class="cell">
    <div class="role">The Client</div>
    <div class="name">{_esc(entity)}</div>
    Registered office: {_esc(office)}<br>
    Jurisdiction of incorporation: {_esc(juris)}<br>
    Principal business: {_esc(business)}<br>
    Authorised representative: {_esc(rep)}<br>
    Email for notices: {_esc(email)}
  </div>
</div>

<h2>A. Background</h2>
<p>The Client completed an initial pilot engagement with the Provider. The parties
now wish to continue on an ongoing basis on the commercial terms set out below.</p>

<h2>B. Commercial terms</h2>
<div class="terms">
  <p><b>Retainer.</b> The Client shall pay the Provider a retainer of
  EUR {RETAINER_EUR} per calendar month, payable monthly in advance.</p>
  <p><b>Commission.</b> In addition to the retainer, the Client shall pay the
  Provider a commission of {COMMISSION_PCT}% of revenue attributable to the
  Provider's services, payable monthly in arrears.</p>
  <p><b>Term.</b> This agreement runs for a fixed term of {TERM_MONTHS} months from
  the date of signature and may not be terminated for convenience during that term.</p>
</div>

<h2>C. Payment</h2>
<ol>
  <li>The Client authorises the Provider to charge the retainer and commission via
      the payment method the Client provides on file (for example Payoneer).</li>
  <li>Invoices are due on issue. Amounts unpaid after fourteen (14) days bear
      interest at the statutory rate applicable in the Client's jurisdiction.</li>
  <li>All sums are exclusive of any applicable VAT or local tax.</li>
</ol>

<h2>D. Governing law and enforcement</h2>
<p>This agreement, and any dispute or claim arising out of or in connection with it,
is governed by the laws of <b>{_esc(juris)}</b>, being the jurisdiction of the
Client's incorporation, and the parties submit to the courts of that jurisdiction
so that any sums owing are enforceable against the Client there.</p>

<h2>E. General</h2>
<ol>
  <li>This agreement supplements the pilot agreement; where they conflict on
      ongoing services, this agreement prevails.</li>
  <li>Neither party may assign without the other's written consent.</li>
  <li>This agreement is the entire agreement between the parties on its subject matter.</li>
</ol>

<div class="sig">
  <div class="box">For the Provider: Gentrit Luta, Aureon Global L.L.C.<br>Date: signed electronically</div>
  <div class="box">For the Client: {_esc(c["sig"])}, {_esc(c["title"])}<br>Date: ____________  Place: ____________</div>
</div>

<p class="small">The Client adopts their typed name as their electronic signature on
acceptance. An audit record (timestamp, IP, and integrity hash) is attached on signing.</p>
</body></html>"""
    return _nodash(body)
