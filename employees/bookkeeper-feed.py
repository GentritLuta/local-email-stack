"""bookkeeper-feed.py -- turn issued invoices into a clean ledger the bookkeeper
employee reads each shift.

Scans the Aureon invoice output folder for Factur-X (EN16931) XML, extracts each
invoice (number, date, buyer, amount, currency, paid/unpaid), and writes a CSV +
a readable markdown ledger into the bookkeeper's data-inbox. This is the automatic
half of the bookkeeping: real invoice data flows in daily, so the bookkeeper keeps
the books and prepares the quarterly QS filing from actuals, not guesses.

It only READS invoices and WRITES a ledger into the data-inbox. It changes no
invoice, sends nothing, and computes only raw per-quarter gross totals (data, not
tax advice -- the bookkeeper employee does the tax reasoning).

    python bookkeeper-feed.py                 # default C:\\Aureon Invoices
    python bookkeeper-feed.py --dir "C:\\Aureon Invoices"
"""
import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import _lib as L

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# The generator (C:\Aureon Invoice App) writes its output to its own output/ folder;
# C:\Aureon Invoices holds legacy/manually-copied files. Scan both, dedup by ref.
INV_DIRS = [Path(r"C:\Aureon Invoice App\output"), Path(r"C:\Aureon Invoices")]
INV_DIR = INV_DIRS[0]  # label for messages

# Go-live cutoff. Per operator: disregard ALL invoices issued before this date (the
# Payoneer + corrected-VAT switch); the books count only NEW invoices from here on.
# Invoices dated before GO_LIVE are excluded from the ledger. Override with --since.
GO_LIVE = "2026-06-29"

# Factur-X / EN16931 CrossIndustryInvoice namespaces (same as import-facturx-invoices.py)
RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"
NS = {"rsm": RSM, "ram": RAM, "udt": UDT}


def parse_facturx(xml_path: Path) -> dict | None:
    try:
        root = ET.parse(xml_path).getroot()
    except Exception as e:
        print(f"  ! parse error {xml_path.name}: {e}")
        return None

    def first(tag):
        for e in root.iter(f"{{{RAM}}}{tag}"):
            if e.text and e.text.strip():
                return e.text.strip()
        return None

    def txt(xpath):
        el = root.find(xpath, NS)
        return el.text.strip() if el is not None and el.text else None

    ref = txt("./rsm:ExchangedDocument/ram:ID")
    grand = first("GrandTotalAmount")
    currency = first("InvoiceCurrencyCode") or "EUR"
    issued = None
    de = root.find("./rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString",
                   {"rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
                    "ram": RAM, "udt": UDT})
    if de is not None and de.text and len(de.text.strip()) == 8:
        d = de.text.strip()
        issued = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    buyer = txt(".//ram:BuyerTradeParty/ram:Name")
    if not ref or grand is None:
        return None
    return {
        "invoice_ref": ref,
        "issued_at": issued or "",
        "buyer": buyer or "",
        "amount": round(float(grand), 2),
        "currency": currency,
        "status": _status(ref, xml_path.parent),
    }


def _status(ref: str, inv_dir: Path) -> str:
    """Paid/unpaid the same way import-facturx-invoices.py resolves it."""
    if (inv_dir / f"{ref}.paid").exists():
        return "paid"
    sf = inv_dir / f"{ref}.status"
    if sf.exists():
        s = sf.read_text(encoding="utf-8", errors="replace").strip().lower()
        if s in ("paid", "sent", "overdue", "void", "draft"):
            return s
    pd = inv_dir / "paid"
    if pd.exists() and any(pd.glob(f"{ref}.*")):
        return "paid"
    return "issued"


def _quarter(issued: str) -> str:
    if not issued or len(issued) < 7:
        return "unknown"
    y, m = issued[0:4], int(issued[5:7])
    return f"{y}-Q{(m - 1) // 3 + 1}"


_LANG_SUFFIXES = ("_SQ", "_EN", "_DE", "_SR")


def _is_real_invoice(ref: str, stem: str) -> bool:
    # Skip language-duplicate files (e.g. factur-x-AG-...-003_SQ.xml = same invoice).
    if any(stem.endswith(s) for s in _LANG_SUFFIXES):
        return False
    # Real Aureon invoices are numbered AG-<CLIENT>-<YEAR>-<SEQ>; everything else
    # in the output folder (DEMO/SELFTEST/TEST-E2E) is a generator artifact.
    up = ref.upper()
    if not up.startswith("AG-"):
        return False
    return not ("DEMO" in up or "SELFTEST" in up or "TEST" in up)


def build_ledger(inv_dirs: list, since: str = "") -> tuple:
    """Return (rows, excluded) where excluded is the count of real invoices skipped
    for being issued before the go-live cutoff."""
    rows, seen, excluded = [], set(), 0
    for inv_dir in inv_dirs:
        if not inv_dir.exists():
            continue
        for xml in sorted(inv_dir.glob("factur-x-*.xml")):
            if any(xml.stem.endswith(s) for s in _LANG_SUFFIXES):
                continue
            rec = parse_facturx(xml)
            if not rec or not _is_real_invoice(rec["invoice_ref"], xml.stem):
                continue
            if rec["invoice_ref"] in seen:
                continue
            seen.add(rec["invoice_ref"])
            if since and rec["issued_at"] and rec["issued_at"] < since:
                excluded += 1  # issued before go-live; disregarded per operator
                continue
            rows.append(rec)
    rows.sort(key=lambda r: (r["issued_at"], r["invoice_ref"]))
    return rows, excluded


def write_outputs(rows: list, out_dir: Path, since: str = "", excluded: int = 0) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # CSV
    csv_path = out_dir / "invoice-ledger.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["invoice_ref", "issued_at", "buyer", "amount", "currency", "status"])
        for r in rows:
            w.writerow([r["invoice_ref"], r["issued_at"], r["buyer"],
                        f"{r['amount']:.2f}", r["currency"], r["status"]])

    # Per-quarter gross totals (raw aggregation by issue date, EUR-labelled rows only)
    by_q = {}
    ytd = {}
    for r in rows:
        q = _quarter(r["issued_at"])
        by_q[q] = by_q.get(q, 0.0) + r["amount"]
        yr = r["issued_at"][:4] or "unknown"
        ytd[yr] = ytd.get(yr, 0.0) + r["amount"]

    cutoff_note = ""
    if since:
        cutoff_note = (f" GO-LIVE CUTOFF {since}: per the operator, all invoices issued "
                       f"BEFORE {since} are disregarded entirely; only invoices from that "
                       f"date forward count here ({excluded} earlier invoice(s) excluded).")
    md = ["# Invoice ledger (auto-generated for the bookkeeper)", "",
          f"Source: Factur-X invoices in {INV_DIR}. {len(rows)} invoice(s)." + cutoff_note +
          " These are issued-invoice actuals; use them to keep the books and prepare "
          "the quarterly filing. Per-quarter totals below are raw gross sums by "
          "issue date, not a tax computation.", "",
          "| Invoice | Issued | Buyer | Amount | Cur | Status |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['invoice_ref']} | {r['issued_at']} | {r['buyer']} | "
                  f"{r['amount']:.2f} | {r['currency']} | {r['status']} |")
    md += ["", "## Gross totals by calendar quarter (raw)", ""]
    for q in sorted(by_q):
        md.append(f"- {q}: {by_q[q]:.2f} EUR")
    md += ["", "## Gross totals by year (raw, watch the EUR 30,000 VAT threshold)", ""]
    for yr in sorted(ytd):
        md.append(f"- {yr}: {ytd[yr]:.2f} EUR")
    md.append("")
    (out_dir / "invoice-ledger.md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {csv_path}")
    print(f"wrote {out_dir / 'invoice-ledger.md'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=None,
                    help="override: scan only this dir instead of the defaults")
    ap.add_argument("--since", default=GO_LIVE,
                    help=f"only count invoices issued on/after this date (default {GO_LIVE})")
    ap.add_argument("--all", action="store_true",
                    help="ignore the go-live cutoff and include every invoice")
    args = ap.parse_args()
    since = "" if args.all else args.since
    inv_dirs = [Path(args.dir)] if args.dir else INV_DIRS
    if not any(d.exists() for d in inv_dirs):
        print(f"no invoice dir found among: {[str(d) for d in inv_dirs]} - nothing to process")
        return 0  # invoices live on the laptop; no dir here means no-op, not a failure
    rows, excluded = build_ledger(inv_dirs, since)
    out_dir = L.role_paths("bookkeeper")["data"]
    write_outputs(rows, out_dir, since=since, excluded=excluded)
    total = sum(r["amount"] for r in rows)
    extra = f" ({excluded} pre-{since} excluded)" if since and excluded else ""
    print(f"bookkeeper-feed: {len(rows)} invoice(s), {total:.2f} EUR gross{extra}, "
          f"-> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
