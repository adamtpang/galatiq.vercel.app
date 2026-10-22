# Run log: all 20 sample invoices

Two committed runs of `python main.py --batch data/invoices`, each on a fresh database, Oct 22 2026:

- **Offline** (`--offline`, deterministic VP and critic rules): `runs/demo/offline/`
- **Live** (`--mode live`, grok-4.7 via the xAI API for risk review, VP and critic): `runs/demo/live/`

Each folder has `trace.jsonl` (every agent step), `summary.json` and `report.md`. Hard rules (any blocking flag) decide 12 of 20 without any LLM call, so both runs agree on those by construction; a hard hold rule holds 1012.pdf (renamed vendor) before the VP. Regenerate this file with `python scripts/make_run_log.py`.

## Side by side

| File | Total USD | Risk off / live | Offline decision | Live decision | Paid off / live |
|---|---|---|---|---|---|
| invoice_1001.txt | $5,000.00 | 0 / 12 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $5,000.00 / not_paid |
| invoice_1002.txt | $15,000.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1003.txt | $100,000.00 | 60 / 60 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1004.json | $1,890.00 | 30 / 30 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1004_revised.json | $5,940.00 | 30 / 48 | PENDING_HUMAN (vp) | PENDING_HUMAN (vp) | not_paid / not_paid |
| invoice_1005.json | $15,225.00 | 50 / 50 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1006.csv | $2,750.00 | 0 / 15 | APPROVED (vp) | APPROVED (vp) | paid $2,750.00 / paid $2,750.00 |
| invoice_1007.csv | $15,525.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1008.txt | $9,900.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1009.json | $-250.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1010.txt | $7,185.00 | 10 / 28 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $7,185.00 / not_paid |
| invoice_1011.pdf | $3,000.00 | 0 / 8 | APPROVED (vp) | APPROVED (vp) | paid $3,000.00 / paid $3,000.00 |
| invoice_1011.txt | $3,000.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1012.pdf | $9,975.00 | 45 / 62 | PENDING_HUMAN (hard_hold) | PENDING_HUMAN (hard_hold) | not_paid / not_paid |
| invoice_1012.txt | $9,975.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.json | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.pdf | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1014.xml | $4,455.00 | 0 / 15 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $4,455.00 / not_paid |
| invoice_1015.csv | $6,500.00 | 0 / 5 | APPROVED (vp) | APPROVED (vp) | paid $6,500.00 / paid $6,500.00 |
| invoice_1016.json | $3,233.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |

Offline: 6 paid ($28,890.00), 12 rejected, 2 held for a human.

Live: 3 paid ($12,250.00), 12 rejected, 5 held for a human.

## Where live and offline disagree

Both runs use the same policy, including the address watch list and the hard hold rules for prompt injection, renamed or lookalike vendors and Grok-rebuilt invoices (decisions 8, 9 and 10 in `docs/DECISIONS.md`). In live mode the risk agent also calls three read-only tools (`lookup_vendor`, `query_inventory`, `vendor_history`) before it scores; the calls are in the trace as `tool_call` events. Every difference goes the cautious way: Grok sent an invoice to a human where the offline rules paid it. Neither run paid anything the other refused.

- **invoice_1001.txt**: the live VP held it on the terms mismatch (Net 15 printed, due date 17 days after issue) and because it is the first invoice on file from the vendor. Offline treats the terms gap as info and pays.
- **invoice_1010.txt**: the live VP held it until a PO covers the $300 WidgetA rush rate (20% over the $250 catalog price). Offline approves with that check as a payment condition.
- **invoice_1014.xml**: the live VP held it as the first invoice from the vendor, billed in EUR, and asked for the prices to be confirmed after the conversion to USD. Offline pays it with the conversion as a payment condition.

Live results are not perfectly repeatable. In the eval run of the same code (`evals/results/live.md`), Grok paid 1001 and 1014, which this demo run held; 1010 was held in both live runs. 1006 was paid in this demo run and in the eval run (the previous demo run held it).

Same outcome, by a different path:

- **invoice_1012.pdf**: PENDING_HUMAN in both runs, decided by the vendor-rename hard hold (decision 9) before the VP and critic. Live, the risk agent still ran its tools and raised the risk to 62, but no VP or critic call was made.
- **invoice_1004_revised.json**: PENDING_HUMAN in both runs. Offline holds it on the watch-list address; live, the VP holds it on the watch-list address and on the earlier rejected INV-1004 (risk 48).

Risk scores differ on most clean invoices because the live risk agent can add points on top of the rule score (it can never lower it). None of those increases crossed a threshold except where noted above.

## Live reasons (first reason per invoice the VP decided)

| File | Decision | Reason | Conditions |
|---|---|---|---|
| invoice_1001.txt | PENDING_HUMAN | Vendor Widgets Inc. is on file and the $5000 total matches the line items. | Confirm whether payment follows Net 15 or the stated due date before release. |
| invoice_1004_revised.json | PENDING_HUMAN | Vendor is on file and the $5,940.00 total matches the stated lines and tax, but the vendor address is on the watch list. | Do not pay until a human confirms the PO amendment and why the prior rejection was cleared.; Confirm the watch-list address before any payment is released. |
| invoice_1006.csv | APPROVED | Vendor is on the approved master file with bank details on file. | Confirm bank details against the vendor master before this first payment is released. |
| invoice_1010.txt | PENDING_HUMAN | Vendor Consolidated Materials Group is on file and the $7,185.00 total matches the invoice. | Confirm the rush surcharge is authorized on the PO before paying the $300.00 WidgetA line. |
| invoice_1011.pdf | APPROVED | Vendor Summit Manufacturing Co. is on file. | none |
| invoice_1014.xml | PENDING_HUMAN | Vendor is on file, but this is the first invoice with no prior history. | Confirm prices against the PO or catalog before release.; Verify bank details on file for this first payment. |
| invoice_1015.csv | APPROVED | Vendor Reliable Components Inc. is on file. | none |
