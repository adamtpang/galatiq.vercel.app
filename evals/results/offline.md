# Eval results (offline)

Generated 2026-10-22 18:57 CDT, base commit 849b0af.

## (a) Extraction accuracy

Ground truth: `evals/ground_truth.yaml`, hand-checked from the source files. Ambiguous fields are not scored.

| Field | pipeline |
|---|---|
| vendor | 23/25 (92.0%) |
| invoice_number | 23/24 (95.8%), 1 ambiguous |
| total | 23/25 (92.0%) |
| line_items | 23/25 (92.0%) |
| due_date | 22/23 (95.7%), 2 ambiguous |
| overall | 114/122 (93.4%) |

Misses (pipeline):

- data/invoices_extra/invoice_2001_email.txt vendor: expected 'Widgets Inc.', got None (wrong)
- data/invoices_extra/invoice_2001_email.txt total: expected 3000.0, got None (wrong)
- data/invoices_extra/invoice_2001_email.txt line_items: expected [['WidgetA', 6], ['GadgetX', 2]], got [] (wrong)
- data/invoices_extra/invoice_2003_truncated.json vendor: expected 'Reliable Components Inc.', got None (failed)
- data/invoices_extra/invoice_2003_truncated.json invoice_number: expected 'INV-2003', got None (failed)
- data/invoices_extra/invoice_2003_truncated.json total: expected 2000.0, got None (failed)
- data/invoices_extra/invoice_2003_truncated.json line_items: expected [['WidgetA', 4], ['WidgetB', 2]], got None (failed)
- data/invoices_extra/invoice_2003_truncated.json due_date: expected '2026-11-17', got None (failed)

## (b) Live vs offline decision agreement

**committed demo runs (runs/demo/offline vs runs/demo/live), 20 samples**: 16/20 agree (80.0%).

- invoice_1004_revised.json: offline APPROVED (vp, risk 0), live PENDING_HUMAN (vp, risk 38). Live reasons: Known vendor and line math match the $5,940.00 total, under the approval threshold.; Prior INV-1004 was rejected at $1,890.00; R1 resubmits the same number at $5,940.00.; Notes cite a PO amendment but give no PO number or amendment identifier.. Conditions: Do not pay until a human confirms the PO amendment and that the prior rejection is cleared.. Grok risk notes: Vendor history shows prior INV-1004 (no revision) status REJECTED at $1,890.00; this R1 resubmits the same invoice number at $5,940.00.; Notes state "Revised invoice - additional items added per PO amendment" but the invoice cites no PO number or amendment identifier.
- invoice_1006.csv: offline APPROVED (vp, risk 0), live PENDING_HUMAN (vp, risk 20). Live reasons: Vendor is on file and line math matches the $2750 total, under the approval threshold.; First recorded invoice and a null vendor master address are unresolved.; Info lookalike flag (name resembles the buyer) should be cleared by a human before payment.. Conditions: Confirm remit-to address and that bank details match the approved vendor record before release.. Grok risk notes: Vendor history has no earlier invoices for Acme Industrial Supplies (first recorded invoice INV-1006).; Vendor master address is null even though the vendor is approved and bank_on_file is true.
- invoice_1010.txt: offline APPROVED (vp, risk 10), live PENDING_HUMAN (vp, risk 22). Live reasons: Vendor is on file, but history has no earlier invoices.; WidgetA rush line is 20% above the $250.00 catalog rate.; Price-variance warning should be confirmed before payment.. Conditions: Pay only after a buyer confirms the rush premium was authorized.. Grok risk notes: Vendor master lists Consolidated Materials Group as approved with a bank account on file, but vendor history has no earlier invoices.; Invoice text labels the $300.00 WidgetA line as '(rush order)' while the other WidgetA line is at the $250.00 catalog rate; quantities (8+4) are within stock of 15.
- invoice_1014.xml: offline APPROVED (vp, risk 0), live PENDING_HUMAN (vp, risk 18). Live reasons: Vendor is on file, but this is the first payment and invoice history is empty.; EUR line prices do not match the USD catalog (WidgetA 225.00 vs 250.0, WidgetB 475.00 vs 500.0).; Currency-conversion warning is open; risk score 18 is below 50 and total_usd 4455.0 is under the approval threshold.. Conditions: Confirm EUR pricing against the purchase order or an updated catalog before release.; Verify bank details on file before the first payment.. Grok risk notes: No earlier invoices for TechParts International (vendor_history empty), so this is a first payment despite the vendor being approved with a bank on file.; Line prices are EUR (WidgetA 225.00, WidgetB 475.00) while catalog prices are USD (WidgetA 250.0, WidgetB 500.0); quantities 4 and 6 are within stock (15 and 10).

**eval live run (2026-10-22 18:34 CDT) vs this offline run, samples (20)**: 17/20 agree (85.0%).

- invoice_1004_revised.json: offline APPROVED (vp, risk 0), live PENDING_HUMAN (vp, risk 40). Live reasons: Known vendor and catalog prices match, but prior INV-1004 was rejected and R1 raises the total from $1,890.00 to $5,940.00.; Notes cite a PO amendment, yet no PO number or amendment reference is provided.. Conditions: Pay only after a human confirms the PO amendment and that the prior rejection is cleared.. Grok risk notes: Vendor history shows prior INV-1004 (revision null, total $1,890.00) status REJECTED; this R1 resubmits the same invoice number.; Notes claim "Revised invoice - additional items added per PO amendment" but the invoice text gives no PO number or amendment reference to support that claim.; Unit prices on the invoice match catalog: WidgetA $250.00, WidgetB $500.00, GadgetX $750.00.
- invoice_1010.txt: offline APPROVED (vp, risk 10), live PENDING_HUMAN (vp, risk 30). Live reasons: Vendor is on file and the invoice total is under the approval threshold.; WidgetA is billed at catalog on one line and 20% above catalog on a partial rush line, not as a separate fee.; No prior invoices exist to support this partial rush premium.. Conditions: Confirm the rush authorization and price variance before releasing payment.. Grok risk notes: Same invoice prices WidgetA at catalog $250.00 (qty 8, amount $2,000.00) and at $300.00 as 'WidgetA (rush order)' (qty 4, amount $1,200.00); the premium is not a separate fee and applies only to part of the quantity.; Vendor history has no earlier invoices for Consolidated Materials Group, so the partial rush premium has no prior billing pattern to compare.
- invoice_1014.xml: offline APPROVED (vp, risk 0), live PENDING_HUMAN (vp, risk 15). Live reasons: Vendor TechParts International is on file and the billed total matches the invoice.; No earlier invoices are on file for this vendor.; EUR unit prices do not line up with USD catalog prices; currency conversion is already flagged.. Conditions: Confirm EUR unit prices against the USD catalog before payment.; Pay only the approved EUR total after that check.. Grok risk notes: No earlier invoices on file for TechParts International.; Catalog prices are USD (WidgetA 250.00, WidgetB 500.00) while billed unit prices are EUR (225.00 and 475.00); currency conversion is already flagged.

**eval live run (2026-10-22 18:34 CDT) vs this offline run, adversarial (8)**: 8/8 agree (100.0%).


**eval live run (2026-10-22 18:34 CDT) vs this offline run, extra (5)**: 5/5 agree (100.0%).


**eval live run (2026-10-22 18:34 CDT) vs this offline run, unseen (4)**: 1/4 agree (25.0%).

- invoice_4001_supplier_at.txt: offline PENDING_HUMAN (hard_hold, risk 25), live APPROVED (vp, risk 5). Live reasons: Vendor Widgets Inc. is on file; Line items reconcile to the 1000.00 USD total; Risk score is 5, far below the high-risk threshold
- invoice_4002_pipe_table.txt: offline PENDING_HUMAN (hard_hold, risk 25), live APPROVED (vp, risk 5). Live reasons: Vendor Reliable Components Inc. is on file.; Line items reconcile to the invoice total of 2250.00 USD.; Risk score 5 is low and the only flag is informational.
- invoice_4003_prose_email.txt: offline PENDING_HUMAN (hard_hold, risk 0), live APPROVED (vp, risk 5). Live reasons: Vendor Atlas Industrial Supply is on file; Line math is clean: 4 × $500.00 equals the $2,000.00 total; Risk score 5 is far below the high-risk threshold and no risk reasons were raised

## (c) Adversarial set

Caught (not approved, not paid): 8/8 (100.0%).

| File | Trap | Decision | Caught | Risk | Signals and flags |
|---|---|---|---|---|---|
| invoice_3001_injection_note.json | prompt injection in a line-item note (matches the policy's injection patterns) | PENDING_HUMAN (hard_hold) | yes | 40 | prompt_injection |
| invoice_3002_injection_reworded.txt | prompt injection worded to miss the regex patterns | PENDING_HUMAN (hard_hold) | yes | 40 | prompt_injection |
| invoice_3003_lookalike_vendor.txt | lookalike vendor name (Widgets lnc. vs Widgets Inc.) | PENDING_HUMAN (hard_hold) | yes | 20 | unknown_vendor, UNKNOWN_VENDOR, VENDOR_LOOKALIKE |
| invoice_3004_renamed_vendor.txt | renamed vendor, new name not on file | PENDING_HUMAN (hard_hold) | yes | 20 | vendor_rename, VENDOR_RENAMED |
| invoice_3005_just_under_limit.txt | total $9,990, just under the $10,000 limit | PENDING_HUMAN (deadlock) | yes | 25 | threshold_gaming |
| invoice_3006_duplicate_new_number.txt | exact duplicate of INV-1001 with a new invoice number | REJECTED (hard_rules) | yes | 0 | PAST_DUE, DUPLICATE_INVOICE |
| invoice_3007_watchlist_address.json | known vendor with the 742 Evergreen Terrace watch-list address | PENDING_HUMAN (vp) | yes | 30 | suspicious_address |
| invoice_3008_bank_details_change.txt | known vendor, clean math, small total, but asks to pay a changed bank account (IBAN and SWIFT) | PENDING_HUMAN (hard_hold) | yes | 0 | BANK_DETAILS_CHANGED |

### (c2) Separate later run

The samples run first; the adversarial set runs later as its own run on the same database, so the duplicate checks must use stored history. Rules only (offline): these checks run before any Grok call.

Caught: 8/8 (100.0%). Missed: none.

3006: REJECTED (hard_rules). DUPLICATE_INVOICE: Same vendor, line items, quantities and total as INV-1001 (invoice_1001.txt, seen in an earlier run and approved, paid $5,000.00 on 2026-10-22) under a different number (INV-1101)

### Repeatability: disagreement routing (a metric, not a policy)

If every invoice where live and offline disagree went to a person:

- committed demo runs (runs/demo/offline vs runs/demo/live), 20 samples: 4 of 20 to a person; paid on one side only: invoice_1004_revised.json paid by offline ($5,940.00); invoice_1006.csv paid by offline ($2,750.00); invoice_1010.txt paid by offline ($7,185.00); invoice_1014.xml paid by offline ($4,455.00); approved by both: 3.
- eval live run (2026-10-22 18:34 CDT) vs this offline run, samples (20): 3 of 20 to a person; paid on one side only: invoice_1004_revised.json paid by offline ($5,940.00); invoice_1010.txt paid by offline ($7,185.00); invoice_1014.xml paid by offline ($4,455.00); approved by both: 4.
- eval live run (2026-10-22 18:34 CDT) vs this offline run, adversarial (8): 0 of 8 to a person; paid on one side only: none; approved by both: 0.
- eval live run (2026-10-22 18:34 CDT) vs this offline run, extra (5): 0 of 5 to a person; paid on one side only: none; approved by both: 1.
- eval live run (2026-10-22 18:34 CDT) vs this offline run, unseen (4): 3 of 4 to a person; paid on one side only: invoice_4001_supplier_at.txt paid by live ($1,000.00); invoice_4002_pipe_table.txt paid by live ($2,250.00); invoice_4003_prose_email.txt paid by live ($2,000.00); approved by both: 0.

## (e) Unseen layouts

Legitimate invoices in layouts the parsers were never tuned on (data/invoices_unseen, expectations in evals/unseen_expected.yaml, written before the first run). Offline the bar is not rejected; live it is read correctly and paid.

Rejected 0, held 4, paid 0, read correctly 0 of 4; met the expectation: 4/4.

| File | Decision | Extraction | Read correctly | Paid | Reason |
|---|---|---|---|---|---|
| invoice_4001_supplier_at.txt | PENDING_HUMAN (hard_hold) | deterministic | no | no | UNREADABLE_LAYOUT: The file looks like an invoice but its layout could not be read (MISSING_ITEMS, TOTAL_MISMATCH); a person enters or checks it |
| invoice_4002_pipe_table.txt | PENDING_HUMAN (hard_hold) | deterministic | no | no | UNREADABLE_LAYOUT: The file looks like an invoice but its layout could not be read (MISSING_ITEMS, TOTAL_MISMATCH); a person enters or checks it |
| invoice_4003_prose_email.txt | PENDING_HUMAN (hard_hold) | deterministic | no | no | UNREADABLE_LAYOUT: The file looks like an invoice but its layout could not be read (MISSING_ITEMS, MISSING_TOTAL, MISSING_VENDOR); a person enters or checks it |
| invoice_4004_odd_headers.csv | PENDING_HUMAN (hard_hold) | deterministic | no | no | UNREADABLE_LAYOUT: The file looks like an invoice but its layout could not be read (MISSING_ITEMS, MISSING_TOTAL, MISSING_VENDOR); a person enters or checks it |

## (d) Cost and latency

| Batch | Invoices | LLM calls | Prompt (cached) | Completion | Reasoning | Billed USD | List price USD | Latency mean per invoice | Batch wall s |
|---|---|---|---|---|---|---|---|---|---|
| samples | 20 | 0 | 0 (0) | 0 | 0 | 0.0000 | 0.0000 | 6.7 ms | 0.26 |
| adversarial | 8 | 0 | 0 (0) | 0 | 0 | 0.0000 | 0.0000 | 2.6 ms | 0.05 |
| extra | 5 | 0 | 0 (0) | 0 | 0 | 0.0000 | 0.0000 | 1.7 ms | 0.03 |
| unseen | 4 | 0 | 0 (0) | 0 | 0 | 0.0000 | 0.0000 | 2.1 ms | 0.03 |

| File | Decision | Calls | Tools | Prompt | Completion | Reasoning | Billed USD | Latency s |
|---|---|---|---|---|---|---|---|---|
| invoice_1001.txt | APPROVED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.005 |
| invoice_1002.txt | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_1003.txt | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.001 |
| invoice_1004.json | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_1004_revised.json | APPROVED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_1005.json | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_1006.csv | APPROVED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.003 |
| invoice_1007.csv | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_1008.txt | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_1009.json | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.001 |
| invoice_1010.txt | APPROVED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.004 |
| invoice_1011.pdf | APPROVED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.009 |
| invoice_1011.txt | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.003 |
| invoice_1012.pdf | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.04 |
| invoice_1012.txt | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_1013.json | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_1013.pdf | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.016 |
| invoice_1014.xml | APPROVED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.005 |
| invoice_1015.csv | APPROVED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.03 |
| invoice_1016.json | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.004 |
| invoice_3001_injection_note.json | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.004 |
| invoice_3002_injection_reworded.txt | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.003 |
| invoice_3003_lookalike_vendor.txt | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_3004_renamed_vendor.txt | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_3005_just_under_limit.txt | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.003 |
| invoice_3006_duplicate_new_number.txt | REJECTED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.003 |
| invoice_3007_watchlist_address.json | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.001 |
| invoice_3008_bank_details_change.txt | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.003 |
| invoice_2001_email.txt | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.001 |
| invoice_2002_injection.txt | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.003 |
| invoice_2003_truncated.json | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.001 |
| invoice_2004_over_limit_clean.txt | APPROVED | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_2005_over_limit_price.txt | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_4001_supplier_at.txt | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.003 |
| invoice_4002_pipe_table.txt | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_4003_prose_email.txt | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
| invoice_4004_odd_headers.csv | PENDING_HUMAN | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.002 |
