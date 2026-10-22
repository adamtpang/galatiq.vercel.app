# Run log: all 20 sample invoices

Two committed runs of `python main.py --batch data/invoices`, each on a fresh database, Oct 22 2026:

- **Offline** (`--offline`, deterministic VP and critic rules): `runs/demo/offline/`
- **Live** (`--mode live`, grok-4.7 via the xAI API for the cross-check, risk review, VP, critic and memo): `runs/demo/live/`

Each folder has `trace.jsonl` (every agent step), `summary.json` and `report.md`. Hard rules (any blocking flag) reject 12 of 20 before any Grok opinion, so both runs agree on those by construction (live, Grok still cross-checks and writes their memo); a hard hold rule holds 1012.pdf (renamed vendor) before the VP. Regenerate this file with `python scripts/make_run_log.py`.

## Side by side

| File | Total USD | Risk off / live | Offline decision | Live decision | Paid off / live |
|---|---|---|---|---|---|
| invoice_1001.txt | $5,000.00 | 0 / 10 | APPROVED (vp) | APPROVED (vp) | paid $5,000.00 / paid $5,000.00 |
| invoice_1002.txt | $15,000.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1003.txt | $100,000.00 | 60 / 60 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1004.json | $1,890.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1004_revised.json | $5,940.00 | 0 / 38 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $5,940.00 / not_paid |
| invoice_1005.json | $15,225.00 | 50 / 50 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1006.csv | $2,750.00 | 0 / 20 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $2,750.00 / not_paid |
| invoice_1007.csv | $15,525.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1008.txt | $9,900.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1009.json | $-250.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1010.txt | $7,185.00 | 10 / 22 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $7,185.00 / not_paid |
| invoice_1011.pdf | $3,000.00 | 0 / 5 | APPROVED (vp) | APPROVED (vp) | paid $3,000.00 / paid $3,000.00 |
| invoice_1011.txt | $3,000.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1012.pdf | $9,975.00 | 45 / 70 | PENDING_HUMAN (hard_hold) | PENDING_HUMAN (hard_hold) | not_paid / not_paid |
| invoice_1012.txt | $9,975.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.json | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.pdf | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1014.xml | $4,455.00 | 0 / 18 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $4,455.00 / not_paid |
| invoice_1015.csv | $6,500.00 | 0 / 8 | APPROVED (vp) | APPROVED (vp) | paid $6,500.00 / paid $6,500.00 |
| invoice_1016.json | $3,233.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |

Offline: 7 paid ($34,830.00), 12 rejected, 1 held for a human.

Live: 3 paid ($14,500.00), 12 rejected, 5 held for a human.

## Where live and offline disagree

Both runs use the same policy, including the address watch list and the hard hold rules for prompt injection, renamed or lookalike vendors, changed bank details, Grok and parser disagreeing, Grok-rebuilt invoices and unreadable layouts (decisions 8 to 14 in `docs/DECISIONS.md`). In live mode Grok also reads every invoice next to the parser (trace step `grok_cross_check`; all 20 agreed in this run) and writes the memo for every decision, and the risk agent calls three read-only tools (`lookup_vendor`, `query_inventory`, `vendor_history`) before it scores; the calls are in the trace as `tool_call` events. Every difference goes the cautious way: Grok sent an invoice to a human where the offline rules paid it. Neither run paid anything the other refused.

- **invoice_1004_revised.json**: offline pays revision R1 ($5,940.00); its address is the one on file for Precision Parts, so the watch list does not fire (decision 13). The live VP held it (risk 38): the earlier INV-1004 was rejected and R1 cites a PO amendment with no PO number.
- **invoice_1006.csv**: the live VP held it (risk 20) as the vendor's first recorded invoice with no address in the vendor master, and asked for the remit-to address and bank details to be confirmed. Offline pays.
- **invoice_1010.txt**: the live VP held it (risk 22) until a buyer confirms the $300 WidgetA rush rate (20% over the $250 catalog price). Offline approves with that check as a payment condition.
- **invoice_1014.xml**: the live VP held it (risk 18) as the vendor's first payment, billed in EUR with line prices that do not match the USD catalog. Offline pays it in USD at the mock rate.

Live results are not perfectly repeatable. A second live run of the same code (the cache measurement, `evals/results/cache_repeatability.md`) paid 1006, which this demo run held; see the README for the eval run.

Same outcome, by a different path:

- **invoice_1012.pdf**: PENDING_HUMAN in both runs, decided by the vendor-rename hard hold (decision 9) before the VP and critic. Live, the risk agent still ran its tools and raised the risk to 70, but no VP or critic call was made.

Risk scores differ on most clean invoices because the live risk agent can add points on top of the rule score (it can never lower it). None of those increases crossed a threshold except where noted above.

## Live reasons (first reason per invoice the VP decided)

| File | Decision | Reason | Conditions |
|---|---|---|---|
| invoice_1001.txt | APPROVED | Vendor Widgets Inc. is on file | Pay on Net 15 from the issue date rather than the stated due date of 2026-02-01 |
| invoice_1004_revised.json | PENDING_HUMAN | Known vendor and line math match the $5,940.00 total, under the approval threshold. | Do not pay until a human confirms the PO amendment and that the prior rejection is cleared. |
| invoice_1006.csv | PENDING_HUMAN | Vendor is on file and line math matches the $2750 total, under the approval threshold. | Confirm remit-to address and that bank details match the approved vendor record before release. |
| invoice_1010.txt | PENDING_HUMAN | Vendor is on file, but history has no earlier invoices. | Pay only after a buyer confirms the rush premium was authorized. |
| invoice_1011.pdf | APPROVED | Vendor Summit Manufacturing Co. is on file | none |
| invoice_1014.xml | PENDING_HUMAN | Vendor is on file, but this is the first payment and invoice history is empty. | Confirm EUR pricing against the purchase order or an updated catalog before release.; Verify bank details on file before the first payment. |
| invoice_1015.csv | APPROVED | Vendor Reliable Components Inc. is on file | none |
