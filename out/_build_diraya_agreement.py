# -*- coding: utf-8 -*-
from pathlib import Path
f = Path("docs/aureon-pilot-agreement-diraya-print.html")
s = f.read_text(encoding="utf-8")
repl = [
 ('between Aureon Global L.L.C. and The Founder Academy Limited (trading as Sales Methodology Hub)',
  'between Aureon Global L.L.C. and Diraya Inc.'),
 ('Reference: AG SMH 2026 01 v4.5 | Execution copy',
  'Reference: AG DIRAYA 2026 01 v1.0 | Execution copy'),
 ('''<div class="name">The Founder Academy Limited</div>
        a private company limited by shares<br>
        trading as Sales Methodology Hub<br>
        Registered office: 56 Stephenson Avenue, Tilbury, England, RM18 8XD<br>
        Company registration number: 16709675<br>
        Incorporation date: 10 September 2025<br>
        Jurisdiction of incorporation: England and Wales, United Kingdom<br>
        SIC codes: 62020 (IT consultancy), 70229 (Management consultancy)<br>
        Authorised representative: Ashraf Hussain, Director<br>
        Email for notices: <span class="placeholder">&nbsp;</span> <em>(to be provided by Client)</em>''',
  '''<div class="name">Diraya Inc.</div>
        a corporation<br>
        Registered office: <span class="placeholder">&nbsp;</span> <em>(to be provided by Client)</em><br>
        Company registration number: <span class="placeholder">&nbsp;</span> <em>(to be provided by Client)</em><br>
        Jurisdiction of incorporation: Canada<br>
        Principal business: artificial intelligence engineering services<br>
        Authorised representative: Mohammed El Amine Amoura, Founder<br>
        Email for notices: amoura.ma@diraya.ca'''),
 ('The Client operates Sales Methodology Hub, a sales intelligence platform covering twenty five plus sales methodologies, and is presently recruiting a founding clients cohort for that platform.',
  'The Client operates Diraya, a provider of artificial intelligence engineering services to technology companies, and is presently developing its client base among early stage technology companies.'),
 ('a persona of the form "[First name] from Sales Methodology Hub"',
  'a persona of the form "[First name] from Diraya"'),
 ('in promoting the Sales Methodology Hub platform, balanced',
  "in promoting Diraya's services, balanced"),
 ('qualifying prospective customers for the Sales Methodology Hub platform.',
  "qualifying prospective customers for Diraya's services."),
 ('business to business marketing of the Sales Methodology Hub platform to contacts',
  "business to business marketing of Diraya's services to contacts"),
 ('<p>Name: Ashraf Hussain<br>', '<p>Name: Mohammed El Amine Amoura<br>'),
 ('''<div class="sig-entity">The Founder Academy Limited</div>
          <div class="sig-field"><span class="label">Name</span><span class="sig-line filled">Ashraf Hussain</span></div>
          <div class="sig-field"><span class="label">Title</span><span class="sig-line filled">Director</span></div>
          <div class="sig-field"><span class="label">Date</span><span class="sig-line">&nbsp;</span></div>
          <div class="sig-field"><span class="label">Signature</span><span class="sig-line">&nbsp;</span></div>
          <div class="sig-field"><span class="label">Place of signature</span><span class="sig-line filled">Tilbury, England, United Kingdom</span></div>''',
  '''<div class="sig-entity">Diraya Inc.</div>
          <div class="sig-field"><span class="label">Name</span><span class="sig-line filled">Mohammed El Amine Amoura</span></div>
          <div class="sig-field"><span class="label">Title</span><span class="sig-line filled">Founder</span></div>
          <div class="sig-field"><span class="label">Date</span><span class="sig-line">&nbsp;</span></div>
          <div class="sig-field"><span class="label">Signature</span><span class="sig-line">&nbsp;</span></div>
          <div class="sig-field"><span class="label">Place of signature</span><span class="sig-line">&nbsp;</span></div>'''),
 ('Provisional Pilot Services Agreement | Reference AG SMH 2026 01 v4.5',
  'Provisional Pilot Services Agreement | Reference AG DIRAYA 2026 01 v1.0'),
]
missing = [o[:45] for o, n in repl if o not in s]
if missing:
    print("NOT FOUND:", missing); raise SystemExit(1)
for o, n in repl:
    s = s.replace(o, n)
# safety: no stray SMH/Founder Academy references left
leftover = [w for w in ("Founder Academy", "Sales Methodology Hub", "Ashraf Hussain", "AG SMH", "Tilbury") if w in s]
f.write_text(s, encoding="utf-8")
print("all 11 swaps applied OK | leftover client refs:", leftover or "none")
