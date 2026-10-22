# Run offline (offline)

| File | Invoice | Vendor | Total USD | Risk | Blocking flags | Decision | By | Rounds | Payment | Reason |
|---|---|---|---|---|---|---|---|---|---|---|
| invoice_1001.txt | INV-1001 | Widgets Inc. | $5,000.00 | 0 | - | APPROVED | vp | 0 | paid $5,000.00 | Vendor is on file |
| invoice_1002.txt | INV-1002 | Gadgets Co. | $15,000.00 | 0 | STOCK_EXCEEDED | REJECTED | hard_rules | 0 | not_paid | STOCK_EXCEEDED: GadgetX: requested 20, only 5 in stock |
| invoice_1003.txt | INV-1003 | Fraudster LLC | $100,000.00 | 60 | ZERO_STOCK, INVALID_DUE_DATE | REJECTED | hard_rules | 0 | not_paid | ZERO_STOCK: FakeItem has zero stock (requested 100) |
| invoice_1004.json | INV-1004 | Precision Parts Ltd. | $1,890.00 | 30 | SUPERSEDED_BY_REVISION | REJECTED | hard_rules | 0 | not_paid | SUPERSEDED_BY_REVISION: Replaced by revision R1 in data/invoices/invoice_1004_revised.json |
| invoice_1004_revised.json | INV-1004 R1 | Precision Parts Ltd. | $5,940.00 | 30 | - | PENDING_HUMAN | vp | 0 | not_paid | Vendor address is on the watch list: 742 evergreen terrace |
| invoice_1005.json | INV-1005 | Global Supply Chain Partners | $15,225.00 | 50 | STOCK_EXCEEDED | REJECTED | hard_rules | 0 | not_paid | STOCK_EXCEEDED: GadgetX: requested 8, only 5 in stock |
| invoice_1006.csv | INV-1006 | Acme Industrial Supplies | $2,750.00 | 0 | - | APPROVED | vp | 0 | paid $2,750.00 | Vendor is on file |
| invoice_1007.csv | INV-1007 | MegaWidgets Corp | $15,525.00 | 25 | STOCK_EXCEEDED, STOCK_EXCEEDED, TOTAL_MISMATCH | REJECTED | hard_rules | 0 | not_paid | STOCK_EXCEEDED: WidgetA: requested 20, only 15 in stock |
| invoice_1008.txt | INV-1008 | NoProd Industries | $9,900.00 | 45 | UNKNOWN_ITEM, UNKNOWN_ITEM | REJECTED | hard_rules | 0 | not_paid | UNKNOWN_ITEM: 'SuperGizmo' is not in inventory |
| invoice_1009.json | INV-1009 | - | $-250.00 | 25 | MISSING_VENDOR, NEGATIVE_QTY, NEGATIVE_TOTAL, SUBTOTAL_MISMATCH, TOTAL_MISMATCH | REJECTED | hard_rules | 0 | not_paid | MISSING_VENDOR: Vendor name is missing |
| invoice_1010.txt | INV-1010 | Consolidated Materials Group | $7,185.00 | 10 | - | APPROVED | vp | 0 | paid $7,185.00 | Vendor is on file |
| invoice_1011.pdf | INV-1011 | Summit Manufacturing Co. | $3,000.00 | 0 | - | APPROVED | vp | 0 | paid $3,000.00 | Vendor is on file |
| invoice_1011.txt | INV-1011 | Summit Manufacturing Co. | $3,000.00 | 0 | DUPLICATE_INVOICE | REJECTED | hard_rules | 0 | not_paid | DUPLICATE_INVOICE: Same invoice already received as data/invoices/invoice_1011.pdf |
| invoice_1012.pdf | INV-1012 | QuickShip Distributers | $9,975.00 | 45 | - | PENDING_HUMAN | deadlock | 2 | not_paid | VP and critic still disagree after 2 rounds |
| invoice_1012.txt | INV-1012 | QuickShip Distributers | $9,975.00 | 45 | DUPLICATE_INVOICE | REJECTED | hard_rules | 0 | not_paid | DUPLICATE_INVOICE: Same invoice already received as data/invoices/invoice_1012.pdf |
| invoice_1013.json | INV-1013 | Atlas Industrial Supply | $22,562.80 | 25 | STOCK_EXCEEDED, STOCK_EXCEEDED, STOCK_EXCEEDED, TOTAL_MISMATCH | REJECTED | hard_rules | 0 | not_paid | STOCK_EXCEEDED: WidgetA: requested 22 across lines [1, 4, 7], only 15 in stock |
| invoice_1013.pdf | INV-1013 | Atlas Industrial Supply | $22,562.80 | 25 | STOCK_EXCEEDED, STOCK_EXCEEDED, STOCK_EXCEEDED, TOTAL_MISMATCH, DUPLICATE_INVOICE | REJECTED | hard_rules | 0 | not_paid | STOCK_EXCEEDED: WidgetA: requested 22 across lines [1, 4, 7], only 15 in stock |
| invoice_1014.xml | INV-1014 | TechParts International | $4,455.00 | 0 | - | APPROVED | vp | 0 | paid $4,455.00 | Vendor is on file |
| invoice_1015.csv | INV-1015 | Reliable Components Inc. | $6,500.00 | 0 | - | APPROVED | vp | 0 | paid $6,500.00 | Vendor is on file |
| invoice_1016.json | INV-1016 | Widgets Inc. | $3,233.00 | 0 | UNKNOWN_ITEM | REJECTED | hard_rules | 0 | not_paid | UNKNOWN_ITEM: 'WidgetC' is not in inventory |
