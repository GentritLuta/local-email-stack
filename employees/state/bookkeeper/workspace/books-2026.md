# Aureon Global Sh.P.K. — Books 2026 (bookkeeper running record)

Last updated: 2026-06-30. Source of income figures: Factur-X invoice ledger in the
data-inbox. **As of 2026-06-30 the populated source is `invoice-ledger.md` (3 invoices);
`invoice-ledger.csv` is now empty (header row only) — see anomaly A6.** Generated from
C:\Aureon Invoice App\output. All figures trace to a source. "Unknown" means no source seen yet.

Shift note 2026-06-30: no new data in the inbox; invoice figures unchanged from 2026-06-29
(EUR 1,500 invoiced, Q2 2026, single buyer). Q2 filing now 15 days out (due 15 Jul 2026),
still blocked on the same three items. New this shift: the CSV export regressed to empty.

## Anomalies log
- A6 (2026-06-30): `invoice-ledger.csv` holds only its header row while `invoice-ledger.md`
  lists all 3 invoices. The CSV export is not populating. Any downstream reader pointed at
  the CSV would see zero income. Books now read from the `.md`. Flag the export to the operator.

## Income (issued invoices)

| Invoice | Issued | Buyer | Amount EUR | Status | Cash received? |
|---|---|---|---|---|---|
| AG-ATAL-2026-001 | 2026-05-19 | Atal Ashna | 500.00 | issued | unconfirmed (no bank stmt) |
| AG-ATAL-2026-002 | 2026-05-19 | Atal Ashna | 500.00 | issued | unconfirmed (no bank stmt) |
| AG-ATAL-2026-003 | 2026-05-26 | Atal Ashna | 500.00 | issued | unconfirmed (no bank stmt) |

- **Q1 2026 (Jan-Mar) invoiced income: EUR 0.00**
- **Q2 2026 (Apr-Jun) invoiced income: EUR 1,500.00**
- **YTD 2026 invoiced income: EUR 1,500.00**

## Expenses
Unknown — no expense/supplier invoices or bank statements provided. Needed only if the
10% profit (QL/CD) regime applies; not needed for presumptive QS.

## Balances / cash
Unknown — no bank statement seen. Cannot confirm how much of the EUR 1,500 was received.

## Receivables
Up to EUR 1,500 potentially outstanding (all three invoices marked `issued`, none `paid`).
Confirm against bank statement.

## Thresholds
- VAT/TVSH registration threshold EUR 30,000 (calendar year): **5.0% used** (1,500 / 30,000). Not approaching.

## Open data needed
1. ARBK extract + fiscal number + registered NACE code (resolves 3% vs 9%, and incorporation date for the Q1 question).
2. ATK EDI / e-deklarimi access or filing-history export (what, if anything, was filed for Q1).
3. Bank statements since incorporation (confirm receipts; resolve cash-vs-invoiced basis).
4. Expense/supplier invoices (only if QL/CD regime).
5. Any rent/interest/royalty/non-resident contract (WR withholding trigger).
