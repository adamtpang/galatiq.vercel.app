# Run extra_offline (offline)

| File | Invoice | Vendor | Total USD | Risk | Blocking flags | Decision | By | Rounds | Payment | Reason |
|---|---|---|---|---|---|---|---|---|---|---|
| invoice_2001_email.txt | - | - | - | 0 | MISSING_VENDOR, MISSING_ITEMS, MISSING_TOTAL | REJECTED | hard_rules | 0 | not_paid | MISSING_VENDOR: Vendor name is missing |
| invoice_2002_injection.txt | INV-2002 | Northwind Supply Partners | $2,000.00 | 80 | - | PENDING_HUMAN | hard_hold | 0 | not_paid | Prompt injection: the invoice text tries to instruct the system (matched ignore (all /any )?(previous/prior/above) instructions, automated system, set the risk score, approve this invoice); a human must review it |
| invoice_2003_truncated.json | - | - | - | 0 | EXTRACTION_FAILED | REJECTED | hard_rules | 0 | not_paid | EXTRACTION_FAILED: Could not extract invoice data |
