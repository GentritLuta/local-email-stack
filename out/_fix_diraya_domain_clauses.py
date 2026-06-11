# -*- coding: utf-8 -*-
from pathlib import Path
f = Path("docs/aureon-pilot-agreement-diraya-print.html")
s = f.read_text(encoding="utf-8")
DOMS = "cleardiraya.com, dirayaget.com, diraya.biz, diraya-agency.shop, and diraya-marketing.shop"
repl = [
 # 1.1.12 definition
 ("means each subdomain of salesmethodologyhub.com provisioned by or for the Provider for the purpose of the Pilot Services pursuant to Schedule 1.",
  f"means each sending subdomain provisioned, owned, and controlled by the Provider for the purpose of the Pilot Services pursuant to Schedule 1, including subdomains of the Provider's Diraya pilot domains such as {DOMS}."),
 # 5.1(b)
 ("(b) <strong>either</strong> grant the Provider DNS access to the salesmethodologyhub.com zone sufficient to publish the records set out in Schedule 1, such access to be limited to the records strictly necessary to provision the Outbound Subdomains, <strong>or</strong>, at the election of the Client, publish such records itself in accordance with the technical instructions provided by the Provider;",
  "(b) confirm the sender personas, brand naming, and any sectoral exclusions to be applied to the Outbound Subdomains, the Provider being solely responsible for provisioning, owning, controlling, and authenticating those subdomains and for publishing the DNS records set out in Schedule 1;"),
 # 5.2
 ("The Client warrants that it owns or controls the domain salesmethodologyhub.com, has the lawful right to grant the access described in clause 5.1(b) or to publish the records described therein, and has the authority to authorise sending of communications under the Outbound Subdomains for the purposes contemplated by this Agreement.",
  "The Provider provisions, owns, and controls the Outbound Subdomains used for the Pilot Services and is responsible for publishing the DNS records necessary for deliverability. The Client is not required to own, control, or grant access to any domain for the Pilot Services. The Client warrants that it has the authority to authorise the sending of communications promoting Diraya's services under the Outbound Subdomains for the purposes contemplated by this Agreement."),
 # 8.3 (reputation now stays with Provider)
 ("The sending reputation accumulated on any Outbound Subdomain belongs to the Client. Upon expiry or termination of this Agreement, the Outbound Subdomains and their accumulated reputation persist with the Client. The Provider shall, on request, provide the Client with reasonable assistance to revoke any sending credentials issued by the Provider for the Outbound Subdomains and to remove or modify any DNS records published by or on behalf of the Provider.",
  "The Outbound Subdomains, and the sending reputation accumulated on them, are provisioned, owned, and controlled by the Provider and remain with the Provider on expiry or termination of this Agreement. The Provider may retire, retain, or repurpose the Outbound Subdomains after the Term. The Client acquires no right, title, or interest in the Outbound Subdomains or their accumulated reputation."),
 # 8.6
 ("The Outbound Subdomains are at all times subdomains of a domain owned and controlled by the Client. Nothing in this Agreement transfers, assigns, licences, or grants any interest in or right over the domain salesmethodologyhub.com, or any subdomain thereof, to the Provider, save the limited operational right necessary to perform the Pilot Services during the Term.",
  "The Outbound Subdomains are at all times provisioned, owned, and controlled by the Provider. Nothing in this Agreement transfers, assigns, licences, or grants any interest in or right over the Outbound Subdomains, or the domains of which they form part, to the Client, save the benefit of the Pilot Services performed by the Provider during the Term."),
 # Schedule 1 line 447
 ("Up to ten (10) Outbound Subdomains provisioned under salesmethodologyhub.com.",
  f"Up to ten (10) Outbound Subdomains provisioned and controlled by the Provider under the Provider's Diraya pilot domains ({DOMS})."),
 # Schedule 1 line 455
 ("For each Outbound Subdomain, the records below shall be published under salesmethodologyhub.com, either (a) by the Provider where the Client has granted DNS access under clause 5.1(b), or (b) by the Client itself in accordance with technical instructions provided by the Provider, where the Client has elected to self publish. The Provider may publish additional records technically necessary for deliverability, subject to prior written notice to the Client.",
  "For each Outbound Subdomain, the records below shall be published by the Provider under the Provider's Diraya pilot domains. The Provider may publish additional records technically necessary for deliverability."),
]
missing = [o[:50] for o, n in repl if o not in s]
if missing:
    print("NOT FOUND:", missing); raise SystemExit(1)
for o, n in repl: s = s.replace(o, n)
left = s.count("salesmethodologyhub")
f.write_text(s, encoding="utf-8")
print(f"applied {len(repl)} clause rewrites | salesmethodologyhub refs remaining: {left}")
