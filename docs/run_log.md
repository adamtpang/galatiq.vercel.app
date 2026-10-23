# Run log: all 20 sample invoices

Two committed runs of `python main.py --batch data/invoices`, each on a fresh database, Oct 22 2026: offline at commit 76881f7, live at commit 05a4ef5. The live run predates the review 3 fixes (76881f7); among the samples they change only 1014, which the offline run now holds (non-USD, decision 22) and the live run paid.

- **Offline** (`--offline`): no model is called; the risk review, VP, critic and rejection review are rules stand-ins (fixed rules written from the agents' prompts), and a template writes the memo: `runs/demo/offline/`
- **Live** (`--mode live`, grok-4.7 via the xAI API for the cross-check, risk review, VP, critic and memo): `runs/demo/live/`

Each folder has `trace.jsonl` (every agent step), `summary.json` and `report.md`. Hard rules (any blocking flag) reject 12 of 20 before any Grok opinion, so both runs agree on those by construction (live, Grok still cross-checks and writes their memo); a hard hold rule holds 1012.pdf (renamed vendor) before the VP. Regenerate this file with `python scripts/make_run_log.py`.

## Side by side

| File | Total USD | Risk off / live | Offline decision | Live decision | Paid off / live |
|---|---|---|---|---|---|
| invoice_1001.txt | $5,000.00 | 0 / 12 | APPROVED (vp, rules stand-in) | PENDING_HUMAN (vp, Grok) **differs** | paid $5,000.00 / not_paid |
| invoice_1002.txt | $15,000.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1003.txt | $100,000.00 | 60 / 60 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1004.json | $1,890.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1004_revised.json | $5,940.00 | 0 / 42 | APPROVED (vp, rules stand-in) | PENDING_HUMAN (vp, Grok) **differs** | paid $5,940.00 / not_paid |
| invoice_1005.json | $15,225.00 | 50 / 50 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1006.csv | $2,750.00 | 0 / 15 | APPROVED (vp, rules stand-in) | APPROVED (vp, Grok) | paid $2,750.00 / paid $2,750.00 |
| invoice_1007.csv | $15,525.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1008.txt | $9,900.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1009.json | $-250.00 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1010.txt | $7,185.00 | 10 / 30 | APPROVED (vp, rules stand-in) | PENDING_HUMAN (vp, Grok) **differs** | paid $7,185.00 / not_paid |
| invoice_1011.pdf | $3,000.00 | 0 / 5 | APPROVED (vp, rules stand-in) | APPROVED (vp, Grok) | paid $3,000.00 / paid $3,000.00 |
| invoice_1011.txt | $3,000.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1012.pdf | $9,975.00 | 45 / 64 | PENDING_HUMAN (hard_hold) | PENDING_HUMAN (hard_hold) | not_paid / not_paid |
| invoice_1012.txt | $9,975.00 | 45 / 45 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.json | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1013.pdf | $22,562.80 | 25 / 25 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |
| invoice_1014.xml | $4,455.00 | 0 / 18 | PENDING_HUMAN (hard_hold) | APPROVED (vp, Grok) **differs** | not_paid / paid $4,455.00 |
| invoice_1015.csv | $6,500.00 | 0 / 5 | APPROVED (vp, rules stand-in) | APPROVED (vp, Grok) | paid $6,500.00 / paid $6,500.00 |
| invoice_1016.json | $3,233.00 | 0 / 0 | REJECTED (hard_rules) | REJECTED (hard_rules) | not_paid / not_paid |

Offline: 6 paid ($30,375.00), 12 rejected, 2 held for a human.

Live: 4 paid ($16,705.00), 12 rejected, 4 held for a human.

## Where live and offline disagree

Both runs use the same code and policy. Each line says which way the decision went; the reasons are the live VP's own, from `runs/demo/live/summary.json`.

- **invoice_1001.txt**: offline APPROVED (paid $5,000.00), live PENDING_HUMAN (risk 12, not_paid). Live reason: Vendor Widgets Inc. is on file and the invoice total is 5000.0 USD. Conditions: Confirm whether payment is Net 15 or due 2026-02-01 before release.
- **invoice_1004_revised.json**: offline APPROVED (paid $5,940.00), live PENDING_HUMAN (risk 42, not_paid). Live reason: Vendor is on file and catalog prices match, but prior INV-1004 was rejected at $1,890.00. Conditions: Do not pay until a human confirms the PO amendment and that the prior rejection is cleared.
- **invoice_1010.txt**: offline APPROVED (paid $7,185.00), live PENDING_HUMAN (risk 30, not_paid). Live reason: Vendor Consolidated Materials Group is on file. Conditions: Confirm the rush-order premium is authorized before payment.
- **invoice_1014.xml**: offline PENDING_HUMAN (not_paid), live APPROVED (risk 18, paid $4,455.00). Live reason: Vendor TechParts International is on file and approved with bank details. Conditions: Pay only to the bank on file.; Settle the EUR invoice amount, or convert only at the recorded rate.

Live results are not perfectly repeatable: the live eval run (`evals/results/live.md`) decided some of these invoices differently. Re-running the same invoices on the same database with the decision cache gives identical decisions (`evals/results/cache_repeatability.md`).

Risk scores differ on most clean invoices because the live risk agent can add points on top of the rule score (it can never lower it).

## Live reasons (first reason per invoice the VP decided)

| File | Decision | Reason | Conditions |
|---|---|---|---|
| invoice_1001.txt | PENDING_HUMAN | Vendor Widgets Inc. is on file and the invoice total is 5000.0 USD. | Confirm whether payment is Net 15 or due 2026-02-01 before release. |
| invoice_1004_revised.json | PENDING_HUMAN | Vendor is on file and catalog prices match, but prior INV-1004 was rejected at $1,890.00. | Do not pay until a human confirms the PO amendment and that the prior rejection is cleared. |
| invoice_1006.csv | APPROVED | Vendor is on file and approved with bank details. | Release as the first payment only to the bank already on file. |
| invoice_1010.txt | PENDING_HUMAN | Vendor Consolidated Materials Group is on file. | Confirm the rush-order premium is authorized before payment. |
| invoice_1011.pdf | APPROVED | Vendor Summit Manufacturing Co. is on file | none |
| invoice_1014.xml | APPROVED | Vendor TechParts International is on file and approved with bank details. | Pay only to the bank on file.; Settle the EUR invoice amount, or convert only at the recorded rate. |
| invoice_1015.csv | APPROVED | Vendor Reliable Components Inc. is on file | none |
