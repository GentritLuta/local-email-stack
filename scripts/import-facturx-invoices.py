# -*- coding: utf-8 -*-
"""import-facturx-invoices.py — pull the AUREON invoice generator's output into
the portal's `invoices` table so clients see their invoices on the dashboard.

The generator (C:\\Aureon Invoice App) writes Factur-X (EN16931 CrossIndustryInvoice)
XML + PDF into its own output\\ folder (also commonly copied to C:\\Aureon Invoices\\).
This parses each factur-x-*.xml, extracts the
invoice ref / amounts / dates / buyer, matches it to a client by name or email,
and upserts an `invoices` row (idempotent on invoice_ref). Status defaults to
'sent'; an admin flips it to 'paid' in the portal (no Payoneer API to poll).

    py scripts/import-facturx-invoices.py            # import all
    py scripts/import-facturx-invoices.py --dir "C:\\Aureon Invoices"
"""
from __future__ import annotations
import argparse, json, sys, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"].rstrip("/"); KEY = env["SUPABASE_SERVICE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
     "User-Agent": "les-invoice-import/1.0"}

RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"
RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
NS = {"rsm": RSM, "ram": RAM, "udt": UDT}


def _find(root, path):
    el = root.find(path)
    return el.text.strip() if el is not None and el.text else None


def _findall_text(root, tag):
    return [e.text.strip() for e in root.iter(f"{{{RAM}}}{tag}") if e.text]


def parse_facturx(xml_path: Path) -> dict | None:
    try:
        root = ET.parse(xml_path).getroot()
    except Exception as e:
        print(f"  ! parse error {xml_path.name}: {e}"); return None

    def first(tag):
        for e in root.iter(f"{{{RAM}}}{tag}"):
            if e.text and e.text.strip():
                return e.text.strip()
        return None

    def txt(xpath):
        el = root.find(xpath, NS)
        return el.text.strip() if el is not None and el.text else None

    # Invoice number = ExchangedDocument/ram:ID (NOT the EN16931 guideline ID).
    ref = txt("./rsm:ExchangedDocument/ram:ID")
    grand = first("GrandTotalAmount")
    due = first("DuePayableAmount")
    currency = first("InvoiceCurrencyCode") or "EUR"
    # Issue date from ExchangedDocument (format 102 = YYYYMMDD).
    issued = None
    de = root.find("./rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString", NS)
    if de is not None and de.text and len(de.text.strip()) == 8:
        d = de.text.strip(); issued = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    # Buyer name + email from BuyerTradeParty.
    buyer = txt(".//ram:BuyerTradeParty/ram:Name")
    buyer_email = txt(".//ram:BuyerTradeParty//ram:URIID")
    # Title: first included note content, else a line description.
    title = txt("./rsm:ExchangedDocument//ram:Content") or first("Description") or "Invoice"
    if not ref or grand is None:
        return None
    return {
        "invoice_ref": ref, "title": title[:200],
        "amount_cents": int(round(float(grand) * 100)),
        "due_cents": int(round(float(due) * 100)) if due else None,
        "currency": currency, "issued_at": issued,
        "buyer": buyer, "buyer_email": buyer_email,
    }


def _q(url):
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=20).read())
    except Exception:
        return []


def match_client(buyer: str | None, buyer_email: str | None) -> tuple[str | None, str | None]:
    """Find (client_id, profile_slug) by buyer email first, then name."""
    import urllib.parse as up
    if buyer_email:
        rows = _q(f"{URL}/rest/v1/clients?email=ilike.{up.quote(buyer_email)}&select=id,profile_slug&limit=1")
        if rows:
            return rows[0]["id"], rows[0].get("profile_slug")
    if buyer:
        q = up.quote(buyer.split()[0])
        rows = _q(f"{URL}/rest/v1/clients?company=ilike.*{q}*&select=id,profile_slug&limit=1")
        if rows:
            return rows[0]["id"], rows[0].get("profile_slug")
    return None, None


def resolve_status(ref: str, inv_dir: Path) -> str | None:
    """Read the paid/unpaid status the generator carries over, if present:
      1. a sidecar `<ref>.paid` or `<ref>.status` marker file next to the XML,
      2. a shared `invoice-status.json` mapping {ref: "paid"|"sent"|"overdue"},
      3. a `paid/` subfolder containing `<ref>.*`.
    Returns the status string, or None to leave the existing/default status."""
    # 1. marker files
    if (inv_dir / f"{ref}.paid").exists():
        return "paid"
    sf = inv_dir / f"{ref}.status"
    if sf.exists():
        s = sf.read_text(encoding="utf-8", errors="replace").strip().lower()
        if s in ("paid", "sent", "overdue", "void", "draft"):
            return s
    # 2. shared status map
    sm = inv_dir / "invoice-status.json"
    if sm.exists():
        try:
            m = json.loads(sm.read_text(encoding="utf-8"))
            v = str(m.get(ref, "")).lower()
            if v in ("paid", "sent", "overdue", "void", "draft"):
                return v
        except Exception:
            pass
    # 3. paid/ subfolder
    pd = inv_dir / "paid"
    if pd.exists() and any(pd.glob(f"{ref}.*")):
        return "paid"
    return None


def upsert_invoice(inv: dict, inv_dir: Path) -> str:
    cid, slug = match_client(inv.get("buyer"), inv.get("buyer_email"))
    status = resolve_status(inv["invoice_ref"], inv_dir) or "sent"
    row = {
        "client_id": cid, "profile_slug": slug,
        "invoice_ref": inv["invoice_ref"], "title": inv["title"],
        "amount_cents": inv["amount_cents"], "due_cents": inv.get("due_cents"),
        "currency": inv["currency"], "status": status, "issued_at": inv.get("issued_at"),
        "source": "facturx",
    }
    if status == "paid":
        row["paid_at"] = (inv.get("issued_at") or "") + "T00:00:00Z" if inv.get("issued_at") else None
    req = urllib.request.Request(
        f"{URL}/rest/v1/invoices?on_conflict=invoice_ref",
        data=json.dumps(row).encode(), method="POST",
        headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"})
    try:
        urllib.request.urlopen(req, timeout=25)
        return "ok" + ("" if cid else " (unmatched client)")
    except Exception as e:
        b = getattr(e, "read", lambda: b"")()
        return f"FAIL {getattr(e,'code','?')} {b.decode()[:120] if b else e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=r"C:\Aureon Invoices")
    args = ap.parse_args()
    d = Path(args.dir)
    if not d.exists():
        print(f"invoice dir not found: {d} - nothing to import"); return 0  # dir lives on the laptop; no-op here
    xmls = sorted(d.glob("factur-x-*.xml"))
    print(f"found {len(xmls)} Factur-X invoice(s) in {d}")
    n = 0
    for x in xmls:
        inv = parse_facturx(x)
        if not inv:
            print(f"  ! skip {x.name} (no ref/amount)"); continue
        res = upsert_invoice(inv, d)
        amt = inv["amount_cents"] / 100
        st = resolve_status(inv["invoice_ref"], d) or "sent"
        print(f"  + {inv['invoice_ref']}  {amt:.2f} {inv['currency']}  [{st}]  "
              f"buyer={inv.get('buyer')}  -> {res}")
        if res.startswith("ok"):
            n += 1
    print(f"imported/updated {n} invoice(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
