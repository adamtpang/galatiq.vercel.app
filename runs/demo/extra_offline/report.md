# Run extra_offline (offline)

| File | Invoice | Vendor | Total USD | Risk | Blocking flags | Decision | By | Rounds | Payment | Reason |
|---|---|---|---|---|---|---|---|---|---|---|
| invoice_2001_email.txt | - | - | - | 0 | MISSING_VENDOR, MISSING_ITEMS, MISSING_TOTAL | REJECTED | hard_rules | 0 | not_paid | MISSING_VENDOR: Vendor name is missing |
| invoice_2002_injection.txt | INV-2002 | Northwind Supply Partners | $2,000.00 | 80 | - | PENDING_HUMAN | vp | 0 | not_paid | Vendor is not on file |
| invoice_2003_truncated.json | - | - | - | 0 | EXTRACTION_FAILED | REJECTED | hard_rules | 0 | not_paid | EXTRACTION_FAILED: Could not extract invoice data |
