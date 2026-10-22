# Run log: all 20 sample invoices

Two committed runs of `python main.py --batch data/invoices`, each on a fresh database, Oct 22 2026:

- **Offline** (`--offline`, deterministic VP and critic rules): `runs/demo/offline/`
- **Live** (`--mode live`, grok-4.7 via the xAI API for risk review, VP and critic): `runs/demo/live/`

Each folder has `trace.jsonl` (every agent step), `summary.json` and `report.md`. Hard rules (any blocking flag) decide 12 of 20 without any LLM call, so both runs agree on those by construction. Regenerate this file with `python scripts/make_run_log.py`.

## Side by side

| File | Total USD | Risk off / live | Offline decision | Live decision | Paid off / live |
|---|---|---|---|---|---|
| invoice_1001.txt | $5,000.00 | 0 / 12 | APPROVED (vp) | APPROVED (vp) | paid $5,000.00 / paid $5,000.00 |
| invoice_1002.txt | $15,000.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1003.txt | $100,000.00 | 60 / 60 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1004.json | $1,890.00 | 30 / 30 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1004_revised.json | $5,940.00 | 30 / 60 | PENDING_HUMAN (vp) | PENDING_HUMAN (vp) | not_paid / not_paid |
| invoice_1005.json | $15,225.00 | 50 / 50 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1006.csv | $2,750.00 | 0 / 20 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $2,750.00 / not_paid |
| invoice_1007.csv | $15,525.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1008.txt | $9,900.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1009.json | $-250.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1010.txt | $7,185.00 | 10 / 35 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $7,185.00 / not_paid |
| invoice_1011.pdf | $3,000.00 | 0 / 5 | APPROVED (vp) | APPROVED (vp) | paid $3,000.00 / paid $3,000.00 |
| invoice_1011.txt | $3,000.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1012.pdf | $9,975.00 | 45 / 74 | PENDING_HUMAN (deadlock, 2 rounds) | PENDING_HUMAN (vp) | not_paid / not_paid |
| invoice_1012.txt | $9,975.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.json | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.pdf | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1014.xml | $4,455.00 | 0 / 18 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $4,455.00 / not_paid |
| invoice_1015.csv | $6,500.00 | 0 / 8 | APPROVED (vp) | APPROVED (vp) | paid $6,500.00 / paid $6,500.00 |
| invoice_1016.json | $3,233.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |

Offline: 6 paid ($28,890.00), 12 rejected, 2 held for a human.

Live: 3 paid ($14,500.00), 12 rejected, 5 held for a human.

## Where live and offline disagree

Both runs use the same policy, including the address watch list (`742 evergreen terrace` was added after an earlier live run flagged it). In live mode the risk agent also calls three read-only tools (`lookup_vendor`, `query_inventory`, `vendor_history`) before it scores; the calls are in the trace as `tool_call` events. Every difference goes the cautious way: Grok sent an invoice to a human where the offline rules paid it. Neither run paid anything the other refused.

- **invoice_1006.csv**: the live VP held it to confirm a remit address and to pay only to the bank on file. Offline sees a known vendor with clean math and pays.
- **invoice_1010.txt**: the live VP held it until a PO or written rush authorization backs the $300 WidgetA rate ($250 catalog). Offline approves with that check as a payment condition.
- **invoice_1014.xml**: the live VP held it as the vendor's first observed invoice, billed in EUR below catalog price. Offline pays the USD amount at the mock FX rate with a treasury condition. In an earlier live run, before the risk agent had tools, Grok paid it; live results vary between runs.
- **invoice_1012.pdf**: both runs end PENDING_HUMAN, by different paths. Offline: the VP approves with conditions, the critic objects twice (the rename, then the total just under $10K) and the loop deadlocks after 2 rounds. Live: the risk agent looked up both vendor names, found that QuickShip Distributers is not a recorded alias of FastShip Ltd. and raised the risk to 74, and the VP held it straight away. The critic only reviews approvals, so it never ran.
- **invoice_1004_revised.json**: PENDING_HUMAN in both runs. Offline holds it on the watch-list hit; live holds it on the watch-list address and a risk score of 60, above the high-risk threshold of 50.

Risk scores differ on most clean invoices because the live risk agent can add points on top of the rule score (it can never lower it). None of those increases crossed a threshold except where noted above.

## Live reasons (first reason per invoice the VP decided)

| File | Decision | Reason | Conditions |
|---|---|---|---|
| invoice_1001.txt | APPROVED | Vendor Widgets Inc. is on file. | Resolve the Net 15 vs due-date mismatch (info) before release; pay on Net 15 unless AP confirms the later due date. |
| invoice_1004_revised.json | PENDING_HUMAN | Vendor is on file, but the address is on the watch list and the risk score is 60, above the high-risk threshold. | Do not pay until procurement confirms the PO amendment and clears the watch-list address. |
| invoice_1006.csv | PENDING_HUMAN | Vendor is approved and on file, and line math matches the $2750.00 total. | Pay only to the bank already on file.; Confirm a remit address before release.; Human to clear the first-payment and name-similarity checks. |
| invoice_1010.txt | PENDING_HUMAN | Vendor is on file and the total is under the approval threshold. | Obtain written rush authorization or a catalog exception before payment.; Pay only the catalog rate for WidgetA unless the premium is approved. |
| invoice_1011.pdf | APPROVED | Vendor Summit Manufacturing Co. is on file | none |
| invoice_1012.pdf | PENDING_HUMAN | New payee QuickShip Distributers is not a registered alias of FastShip Ltd.; bank details must be verified before payment. | Pay only after bank details are confirmed against the FastShip Ltd. record via a known contact, not the invoice.; Record an approved legal-name alias before treating QuickShip Distributers as a known vendor. |
| invoice_1014.xml | PENDING_HUMAN | Vendor is on file, but this is the first observed invoice. | Confirm catalog price agreement before payment.; Pay only after a human reviews the first-invoice and currency mismatch. |
| invoice_1015.csv | APPROVED | Vendor is on file. | none |
