---
id: SOP-FIN-003
title: Vendor invoice reconciliation
triggers: [reconcile, reconciliation, invoices, invoice, vendor, ledger, march]
---
# SOP-FIN-003 - Reconcile vendor invoices against the AP ledger

**Inputs:** the vendor invoice sheet (.xlsx) given with the request. **Ledger:** table `ledger` in the `expense` database.

1. **Read the invoice sheet** with `files.read_sheet`. Columns: invoice_no, vendor, amount_inr, invoice_date.
2. **Read the ledger** with `sql.query` on db `expense`: `SELECT invoice_no, vendor, amount_inr FROM ledger`.
3. **Compare by invoice_no.** Classify each invoice number that appears in either source:
   - `matched` - in both, amounts equal
   - `amount_mismatch` - in both, amounts differ
   - `missing_in_ledger` - on the invoice sheet, not in the ledger
   - `extra_in_ledger` - in the ledger, not on the invoice sheet
4. **Write the report** with `files.write_sheet` to `company_env/data/out/reconciliation_march.xlsx`, one row per invoice number, columns:
   `invoice_no, status, invoice_amount, ledger_amount, difference` (blank where not applicable; difference = ledger - invoice).
5. **Open one ticket** in ticketing (category "Finance follow-up", requester "Finance Operator") titled "March invoice reconciliation discrepancies"
   whose details list every non-matched invoice_no with its status. Do this only if at least one discrepancy exists.
6. Do not edit the ledger or the invoices. Reconciliation is read-only on systems of record.
