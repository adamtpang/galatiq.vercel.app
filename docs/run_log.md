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
| invoice_1004_revised.json | $5,940.00 | 30 / 72 | PENDING_HUMAN (vp) | PENDING_HUMAN (vp) | not_paid / not_paid |
| invoice_1005.json | $15,225.00 | 50 / 50 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1006.csv | $2,750.00 | 0 / 32 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $2,750.00 / not_paid |
| invoice_1007.csv | $15,525.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1008.txt | $9,900.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1009.json | $-250.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1010.txt | $7,185.00 | 10 / 36 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $7,185.00 / not_paid |
| invoice_1011.pdf | $3,000.00 | 0 / 8 | APPROVED (vp) | APPROVED (vp) | paid $3,000.00 / paid $3,000.00 |
| invoice_1011.txt | $3,000.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1012.pdf | $9,975.00 | 45 / 64 | PENDING_HUMAN (deadlock, 2 rounds) | PENDING_HUMAN (vp) | not_paid / not_paid |
| invoice_1012.txt | $9,975.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.json | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.pdf | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1014.xml | $4,455.00 | 0 / 15 | APPROVED (vp) | APPROVED (vp) | paid $4,455.00 / paid $4,455.00 |
| invoice_1015.csv | $6,500.00 | 0 / 5 | APPROVED (vp) | APPROVED (vp) | paid $6,500.00 / paid $6,500.00 |
| invoice_1016.json | $3,233.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |

Offline: 6 paid ($28,890.00), 12 rejected, 2 held for a human.

Live: 4 paid ($18,955.00), 12 rejected, 4 held for a human.

## Where live and offline disagree

Both runs use the same policy, including the address watch list (`742 evergreen terrace` was added after the first live run flagged it). Every difference goes the cautious way: Grok sent an invoice to a human where the offline rules paid it. Neither run paid anything the other refused on hard rules.

- **invoice_1006.csv**: the live VP held it because the due date (16 days) does not match Net 15. Offline treats TERMS_MISMATCH as info only and pays.
- **invoice_1010.txt**: the live VP held it until a PO or written rush authorization backs the $300 WidgetA rate ($250 catalog). Offline approves with that check as a payment condition.
- **invoice_1012.pdf**: both runs end PENDING_HUMAN, by different paths. Offline: the VP approves with conditions, the critic objects twice (the rename, then the total just under $10K) and the loop deadlocks after 2 rounds. Live: the VP held it straight away (unverified rename, risk 64 above the threshold of 50, total just under $10K). The critic only reviews approvals, so it never ran.
- **invoice_1004_revised.json**: same decision (PENDING_HUMAN) in both runs now. Offline holds it on the watch-list hit; live holds it because the risk score (72) is above the high-risk threshold of 50.

Risk scores differ on most clean invoices because the live risk agent can add points on top of the rule score (it can never lower it). None of those increases crossed a threshold except the ones above.

## Live reasons (first reason per invoice the VP decided)

| File | Decision | Reason | Conditions |
|---|---|---|---|
| invoice_1001.txt | APPROVED | Vendor Widgets Inc. is on file. | Pay on Net 15 from the invoice date unless AP confirms the stated due date (17 days, not 15). |
| invoice_1004_revised.json | PENDING_HUMAN | Risk score 72 exceeds the high-risk threshold of 50. | Do not pay until a human confirms the watch-list address and the PO amendment that supports the added lines. |
| invoice_1006.csv | PENDING_HUMAN | Vendor is on file and line math matches the invoice total. | Confirm the correct due date against Net 15 before releasing payment. |
| invoice_1010.txt | PENDING_HUMAN | Vendor Consolidated Materials Group is on file and the invoice total of 7185.00 USD is under the 10000 approval threshold. | Do not pay the WidgetA premium until a PO or written rush authorization for the 300.00 rate is on file.; If authorization is not produced, pay WidgetA at the catalog rate of 250.00 and short-pay the premium. |
| invoice_1011.pdf | APPROVED | Vendor Summit Manufacturing Co. is on file. | none |
| invoice_1012.pdf | PENDING_HUMAN | Vendor renamed from FastShip Ltd.; new name is not on file, so bank details are unverified. | Confirm bank details against the on-file FastShip Ltd. record before any payment.; Human review of the near-limit total and remaining invoice anomalies before release. |
| invoice_1014.xml | APPROVED | Vendor TechParts International is on file. | Settle the billed EUR total using the treasury FX rate at payment. |
| invoice_1015.csv | APPROVED | Vendor Reliable Components Inc. is on file | none |
