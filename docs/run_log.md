# Run log: all 20 sample invoices

Two committed runs of `python main.py --batch data/invoices`, each on a fresh database, Oct 22 2026:

- **Offline** (`--offline`, deterministic VP and critic rules): `runs/demo/offline/`
- **Live** (`--mode live`, grok-4.7 via the xAI API for risk review, VP and critic): `runs/demo/live/`

Each folder has `trace.jsonl` (every agent step), `summary.json` and `report.md`. Hard rules (any blocking flag) decide 12 of 20 without any LLM call, so both runs agree on those by construction.

## Side by side

| File | Total USD | Risk off / live | Offline decision | Live decision | Paid off / live |
|---|---|---|---|---|---|
| invoice_1001.txt | $5,000.00 | 0 / 15 | APPROVED (vp) | APPROVED (vp) | paid $5,000.00 / paid $5,000.00 |
| invoice_1002.txt | $15,000.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1003.txt | $100,000.00 | 60 / 60 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1004.json | $1,890.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1004_revised.json | $5,940.00 | 0 / 58 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $5,940.00 / not_paid |
| invoice_1005.json | $15,225.00 | 50 / 50 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1006.csv | $2,750.00 | 0 / 25 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $2,750.00 / not_paid |
| invoice_1007.csv | $15,525.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1008.txt | $9,900.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1009.json | $-250.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1010.txt | $7,185.00 | 10 / 32 | APPROVED (vp) | PENDING_HUMAN (vp) **differs** | paid $7,185.00 / not_paid |
| invoice_1011.pdf | $3,000.00 | 0 / 5 | APPROVED (vp) | APPROVED (vp) | paid $3,000.00 / paid $3,000.00 |
| invoice_1011.txt | $3,000.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1012.pdf | $9,975.00 | 45 / 70 | PENDING_HUMAN (deadlock, 2 rounds) | PENDING_HUMAN (vp) | not_paid / not_paid |
| invoice_1012.txt | $9,975.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.json | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.pdf | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1014.xml | $4,455.00 | 0 / 20 | APPROVED (vp) | APPROVED (vp) | paid $4,455.00 / paid $4,455.00 |
| invoice_1015.csv | $6,500.00 | 0 / 5 | APPROVED (vp) | APPROVED (vp) | paid $6,500.00 / paid $6,500.00 |
| invoice_1016.json | $3,233.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |

Offline: 7 paid, 12 rejected, 1 pending. Live: 4 paid, 12 rejected, 4 pending.

## Where live and offline disagree

All four differences go the cautious way: Grok sent an invoice to a human where the offline rules paid it. None is a payment the offline run refused.

- **invoice_1004_revised.json**: Grok's risk review noticed the vendor address, 742 Evergreen Terrace, Springfield, is the Simpsons' fictional address, and that the PO amendment cites no PO number. Risk went from 0 to 58 (at or above 50), so the VP held it. The rule list has no such signal; this is a real catch to consider adding to the address watch list.
- **invoice_1006.csv**: the VP held it over the due date (16 days) not matching Net 15. Offline treats TERMS_MISMATCH as info only.
- **invoice_1010.txt**: the VP held it until a human confirms the rush premium ($300 vs $250 catalog). Offline approves with that as a payment condition.
- **invoice_1012.pdf**: both runs end PENDING_HUMAN, by different paths. Offline: VP approves with conditions, critic objects (rename, then total just under $10K), deadlock after 2 rounds. Live: the VP held it straight away over the unverified rename, so the critic never ran.

## Live reasons (first reason per invoice)

| File | Decision | Reason | Conditions |
|---|---|---|---|
| invoice_1001.txt | APPROVED | Vendor Widgets Inc. is on file | Pay on Net 15 from the invoice date, not the stated due date |
| invoice_1004_revised.json | PENDING_HUMAN | Risk score 58 exceeds the high-risk threshold of 50. | Do not pay until a human verifies the vendor address, the PO amendment, and that revision R1 is authorized. |
| invoice_1006.csv | PENDING_HUMAN | Vendor is on file and line math matches the $2750 total. | Confirm the correct due date against Net 15 before payment. |
| invoice_1010.txt | PENDING_HUMAN | Vendor Consolidated Materials Group is on file and the invoice is under the approval threshold with risk score 32 below the high-risk cutoff. | Release payment only after a human confirms the rush-order premium is authorized. |
| invoice_1011.pdf | APPROVED | Vendor Summit Manufacturing Co. is on file. | - |
| invoice_1012.pdf | PENDING_HUMAN | Vendor was renamed from FastShip Ltd.; the new name is not on file, so bank details must be verified. | Do not pay until bank details are confirmed against the FastShip Ltd. record on file.; Independently confirm PO-20260115 and the internal contact before release. |
| invoice_1014.xml | APPROVED | Vendor TechParts International is on file. | - |
| invoice_1015.csv | APPROVED | Vendor Reliable Components Inc. is on file. | - |
