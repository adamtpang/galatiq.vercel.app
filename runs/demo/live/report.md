# Run live (grok, grok-4.7)

| File | Invoice | Vendor | Total USD | Risk | Blocking flags | Decision | By | Rounds | Payment | Reason |
|---|---|---|---|---|---|---|---|---|---|---|
| invoice_1001.txt | INV-1001 | Widgets Inc. | $5,000.00 | 12 | - | PENDING_HUMAN | vp | 0 | not_paid | Vendor Widgets Inc. is on file and the $5000 total matches the line items. |
| invoice_1002.txt | INV-1002 | Gadgets Co. | $15,000.00 | 0 | STOCK_EXCEEDED | REJECTED | hard_rules | 0 | not_paid | STOCK_EXCEEDED: GadgetX: requested 20, only 5 in stock |
| invoice_1003.txt | INV-1003 | Fraudster LLC | $100,000.00 | 60 | ZERO_STOCK, INVALID_DUE_DATE | REJECTED | hard_rules | 0 | not_paid | ZERO_STOCK: FakeItem has zero stock (requested 100) |
| invoice_1004.json | INV-1004 | Precision Parts Ltd. | $1,890.00 | 30 | SUPERSEDED_BY_REVISION | REJECTED | hard_rules | 0 | not_paid | SUPERSEDED_BY_REVISION: Replaced by revision R1 in invoice_1004_revised.json |
| invoice_1004_revised.json | INV-1004 R1 | Precision Parts Ltd. | $5,940.00 | 48 | - | PENDING_HUMAN | vp | 0 | not_paid | Vendor is on file and the $5,940.00 total matches the stated lines and tax, but the vendor address is on the watch list. |
| invoice_1005.json | INV-1005 | Global Supply Chain Partners | $15,225.00 | 50 | STOCK_EXCEEDED | REJECTED | hard_rules | 0 | not_paid | STOCK_EXCEEDED: GadgetX: requested 8, only 5 in stock |
| invoice_1006.csv | INV-1006 | Acme Industrial Supplies | $2,750.00 | 15 | - | APPROVED | vp | 0 | paid $2,750.00 | Vendor is on the approved master file with bank details on file. |
| invoice_1007.csv | INV-1007 | MegaWidgets Corp | $15,525.00 | 25 | STOCK_EXCEEDED, STOCK_EXCEEDED, TOTAL_MISMATCH | REJECTED | hard_rules | 0 | not_paid | STOCK_EXCEEDED: WidgetA: requested 20, only 15 in stock |
| invoice_1008.txt | INV-1008 | NoProd Industries | $9,900.00 | 45 | UNKNOWN_ITEM, UNKNOWN_ITEM | REJECTED | hard_rules | 0 | not_paid | UNKNOWN_ITEM: 'SuperGizmo' is not in inventory |
| invoice_1009.json | INV-1009 | - | $-250.00 | 25 | MISSING_VENDOR, NEGATIVE_QTY, NEGATIVE_TOTAL, SUBTOTAL_MISMATCH, TOTAL_MISMATCH | REJECTED | hard_rules | 0 | not_paid | MISSING_VENDOR: Vendor name is missing |
| invoice_1010.txt | INV-1010 | Consolidated Materials Group | $7,185.00 | 28 | - | PENDING_HUMAN | vp | 0 | not_paid | Vendor Consolidated Materials Group is on file and the $7,185.00 total matches the invoice. |
| invoice_1011.pdf | INV-1011 | Summit Manufacturing Co. | $3,000.00 | 8 | - | APPROVED | vp | 0 | paid $3,000.00 | Vendor Summit Manufacturing Co. is on file. |
| invoice_1011.txt | INV-1011 | Summit Manufacturing Co. | $3,000.00 | 0 | DUPLICATE_INVOICE | REJECTED | hard_rules | 0 | not_paid | DUPLICATE_INVOICE: Same invoice already received as invoice_1011.pdf |
| invoice_1012.pdf | INV-1012 | QuickShip Distributers | $9,975.00 | 62 | - | PENDING_HUMAN | hard_hold | 0 | not_paid | VENDOR_RENAMED: Vendor says it was formerly 'FastShip Ltd.' (on file); new name is not, so verify bank details; hold for human verification of the vendor and bank details |
| invoice_1012.txt | INV-1012 | QuickShip Distributers | $9,975.00 | 45 | DUPLICATE_INVOICE | REJECTED | hard_rules | 0 | not_paid | DUPLICATE_INVOICE: Same invoice already received as invoice_1012.pdf |
| invoice_1013.json | INV-1013 | Atlas Industrial Supply | $22,562.80 | 25 | STOCK_EXCEEDED, STOCK_EXCEEDED, STOCK_EXCEEDED, TOTAL_MISMATCH | REJECTED | hard_rules | 0 | not_paid | STOCK_EXCEEDED: WidgetA: requested 22 across lines [1, 4, 7], only 15 in stock |
| invoice_1013.pdf | INV-1013 | Atlas Industrial Supply | $22,562.80 | 25 | STOCK_EXCEEDED, STOCK_EXCEEDED, STOCK_EXCEEDED, TOTAL_MISMATCH, DUPLICATE_INVOICE | REJECTED | hard_rules | 0 | not_paid | STOCK_EXCEEDED: WidgetA: requested 22 across lines [1, 4, 7], only 15 in stock |
| invoice_1014.xml | INV-1014 | TechParts International | $4,455.00 | 15 | - | PENDING_HUMAN | vp | 0 | not_paid | Vendor is on file, but this is the first invoice with no prior history. |
| invoice_1015.csv | INV-1015 | Reliable Components Inc. | $6,500.00 | 5 | - | APPROVED | vp | 0 | paid $6,500.00 | Vendor Reliable Components Inc. is on file. |
| invoice_1016.json | INV-1016 | Widgets Inc. | $3,233.00 | 0 | UNKNOWN_ITEM | REJECTED | hard_rules | 0 | not_paid | UNKNOWN_ITEM: 'WidgetC' is not in inventory |
