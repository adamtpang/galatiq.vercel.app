# Live re-run with the decision cache: runs/demo/live, then the same 20 samples again on the same database

Model grok-4.7. Same database, cache on. Decision, decided by, risk, reason, flags and conditions identical for 20 of 20 invoices. Code commit 05a4ef5 (second run 05a4ef5).

| | first run | second run |
|---|---|---|
| Approved / rejected / held | 4 / 12 / 4 | 4 / 12 / 4 |
| Approved total | $16,705.00 | $16,705.00 |
| API calls | 83 | 0 |
| Grok answers stored / reused | 55 / 0 | 0 / 55 |
| Billed | $0.6346 | $0.0 |
| Trace span | 844.6 s | 0.2 s |
| Model ids recorded (a cached answer keeps the id of its original call) | grok-4.7 | grok-4.7 |

| file | decision 1 | decision 2 | risk 1 | risk 2 | payment 1 | payment 2 | identical |
|---|---|---|---|---|---|---|---|
| invoice_1001.txt | PENDING_HUMAN | PENDING_HUMAN | 12 | 12 | not_paid | not_paid | yes |
| invoice_1002.txt | REJECTED | REJECTED | 0 | 0 | not_paid | not_paid | yes |
| invoice_1003.txt | REJECTED | REJECTED | 60 | 60 | not_paid | not_paid | yes |
| invoice_1004.json | REJECTED | REJECTED | 0 | 0 | not_paid | not_paid | yes |
| invoice_1004_revised.json | PENDING_HUMAN | PENDING_HUMAN | 42 | 42 | not_paid | not_paid | yes |
| invoice_1005.json | REJECTED | REJECTED | 50 | 50 | not_paid | not_paid | yes |
| invoice_1006.csv | APPROVED | APPROVED | 15 | 15 | paid $2,750.00 | already_paid $2,750.00 | yes |
| invoice_1007.csv | REJECTED | REJECTED | 25 | 25 | not_paid | not_paid | yes |
| invoice_1008.txt | REJECTED | REJECTED | 45 | 45 | not_paid | not_paid | yes |
| invoice_1009.json | REJECTED | REJECTED | 25 | 25 | not_paid | not_paid | yes |
| invoice_1010.txt | PENDING_HUMAN | PENDING_HUMAN | 30 | 30 | not_paid | not_paid | yes |
| invoice_1011.pdf | APPROVED | APPROVED | 5 | 5 | paid $3,000.00 | already_paid $3,000.00 | yes |
| invoice_1011.txt | REJECTED | REJECTED | 0 | 0 | not_paid | not_paid | yes |
| invoice_1012.pdf | PENDING_HUMAN | PENDING_HUMAN | 64 | 64 | not_paid | not_paid | yes |
| invoice_1012.txt | REJECTED | REJECTED | 45 | 45 | not_paid | not_paid | yes |
| invoice_1013.json | REJECTED | REJECTED | 25 | 25 | not_paid | not_paid | yes |
| invoice_1013.pdf | REJECTED | REJECTED | 25 | 25 | not_paid | not_paid | yes |
| invoice_1014.xml | APPROVED | APPROVED | 18 | 18 | paid $4,455.00 | already_paid $4,455.00 | yes |
| invoice_1015.csv | APPROVED | APPROVED | 5 | 5 | paid $6,500.00 | already_paid $6,500.00 | yes |
| invoice_1016.json | REJECTED | REJECTED | 0 | 0 | not_paid | not_paid | yes |

