# Run offline (offline)

| File | Invoice | Vendor | Total USD | Risk | Blocking flags | Decision | By | Rounds | Payment | Reason |
|---|---|---|---|---|---|---|---|---|---|---|
| invoice_1001.txt | INV-1001 | Widgets Inc. | $5,000.00 | 0 | - | APPROVED | the VP rules stand-in | 0 | paid $5,000.00 | Vendor is on file |
| invoice_1002.txt | INV-1002 | Gadgets Co. | $15,000.00 | 0 | STOCK_EXCEEDED | REJECTED | the hard rules | 0 | not_paid | STOCK_EXCEEDED: GadgetX: requested 20, only 5 in stock |
| invoice_1003.txt | INV-1003 | Fraudster LLC | $100,000.00 | 60 | ZERO_STOCK, INVALID_DUE_DATE | REJECTED | the hard rules | 0 | not_paid | ZERO_STOCK: FakeItem has zero stock (requested 100) |
| invoice_1004.json | INV-1004 | Precision Parts Ltd. | $1,890.00 | 0 | SUPERSEDED_BY_REVISION | REJECTED | the hard rules | 0 | not_paid | SUPERSEDED_BY_REVISION: Replaced by revision R1 in invoice_1004_revised.json |
| invoice_1004_revised.json | INV-1004 R1 | Precision Parts Ltd. | $5,940.00 | 0 | - | APPROVED | the VP rules stand-in | 0 | paid $5,940.00 | Vendor is on file |
| invoice_1005.json | INV-1005 | Global Supply Chain Partners | $15,225.00 | 50 | STOCK_EXCEEDED | REJECTED | the hard rules | 0 | not_paid | STOCK_EXCEEDED: GadgetX: requested 8, only 5 in stock |
| invoice_1006.csv | INV-1006 | Acme Industrial Supplies | $2,750.00 | 0 | - | APPROVED | the VP rules stand-in | 0 | paid $2,750.00 | Vendor is on file |
| invoice_1007.csv | INV-1007 | MegaWidgets Corp | $15,525.00 | 25 | STOCK_EXCEEDED, STOCK_EXCEEDED, TOTAL_MISMATCH | REJECTED | the hard rules | 0 | not_paid | STOCK_EXCEEDED: WidgetA: requested 20, only 15 in stock |
| invoice_1008.txt | INV-1008 | NoProd Industries | $9,900.00 | 45 | UNKNOWN_ITEM, UNKNOWN_ITEM | REJECTED | the hard rules | 0 | not_paid | UNKNOWN_ITEM: 'SuperGizmo' is not in inventory |
| invoice_1009.json | INV-1009 | - | $-250.00 | 25 | MISSING_VENDOR, NEGATIVE_QTY, NEGATIVE_TOTAL, SUBTOTAL_MISMATCH, TOTAL_MISMATCH | REJECTED | the hard rules | 0 | not_paid | MISSING_VENDOR: Vendor name is missing |
| invoice_1010.txt | INV-1010 | Consolidated Materials Group | $7,185.00 | 10 | - | APPROVED | the VP rules stand-in | 0 | paid $7,185.00 | Vendor is on file |
| invoice_1011.pdf | INV-1011 | Summit Manufacturing Co. | $3,000.00 | 0 | - | APPROVED | the VP rules stand-in | 0 | paid $3,000.00 | Vendor is on file |
| invoice_1011.txt | INV-1011 | Summit Manufacturing Co. | $3,000.00 | 0 | DUPLICATE_INVOICE | REJECTED | the hard rules | 0 | not_paid | DUPLICATE_INVOICE: Same invoice already received as invoice_1011.pdf |
| invoice_1012.pdf | INV-1012 | QuickShip Distributers | $9,975.00 | 45 | - | PENDING_HUMAN | a hard hold rule | 0 | not_paid | VENDOR_RENAMED: Vendor says it was formerly 'FastShip Ltd.' (on file); new name is not, so verify bank details; hold for human verification of the vendor and bank details |
| invoice_1012.txt | INV-1012 | QuickShip Distributers | $9,975.00 | 45 | DUPLICATE_INVOICE | REJECTED | the hard rules | 0 | not_paid | DUPLICATE_INVOICE: Same invoice already received as invoice_1012.pdf |
| invoice_1013.json | INV-1013 | Atlas Industrial Supply | $22,562.80 | 25 | STOCK_EXCEEDED, STOCK_EXCEEDED, STOCK_EXCEEDED, TOTAL_MISMATCH | REJECTED | the hard rules | 0 | not_paid | STOCK_EXCEEDED: WidgetA: requested 22 across lines [1, 4, 7], only 15 in stock |
| invoice_1013.pdf | INV-1013 | Atlas Industrial Supply | $22,562.80 | 25 | STOCK_EXCEEDED, STOCK_EXCEEDED, STOCK_EXCEEDED, TOTAL_MISMATCH, DUPLICATE_INVOICE | REJECTED | the hard rules | 0 | not_paid | STOCK_EXCEEDED: WidgetA: requested 22 across lines [1, 4, 7], only 15 in stock |
| invoice_1014.xml | INV-1014 | TechParts International | $4,455.00 | 0 | - | PENDING_HUMAN | a hard hold rule | 0 | not_paid | CURRENCY_CONVERTED: Billed in EUR; $4,125.00 EUR = $4,455.00 USD at mock rate 1.08; hold for a person to confirm the USD amount; nothing is paid at a fixed rate |
| invoice_1015.csv | INV-1015 | Reliable Components Inc. | $6,500.00 | 0 | - | APPROVED | the VP rules stand-in | 0 | paid $6,500.00 | Vendor is on file |
| invoice_1016.json | INV-1016 | Widgets Inc. | $3,233.00 | 0 | UNKNOWN_ITEM | REJECTED | the hard rules | 0 | not_paid | UNKNOWN_ITEM: 'WidgetC' is not in inventory |

## Decision memos

- **invoice_1001.txt** (template): INV-1001 from Widgets Inc. for $5,000.00 was approved for payment by the VP rules stand-in (offline: no model was called). Main reason: Vendor is on file.
- **invoice_1002.txt** (template): INV-1002 from Gadgets Co. for $15,000.00 was rejected by the hard rules. Main reason: STOCK_EXCEEDED: GadgetX: requested 20, only 5 in stock.
- **invoice_1003.txt** (template): INV-1003 from Fraudster LLC for $100,000.00 was rejected by the hard rules. Main reason: ZERO_STOCK: FakeItem has zero stock (requested 100).
- **invoice_1004.json** (template): INV-1004 from Precision Parts Ltd. for $1,890.00 was rejected by the hard rules. Main reason: SUPERSEDED_BY_REVISION: Replaced by revision R1 in invoice_1004_revised.json.
- **invoice_1004_revised.json** (template): INV-1004 from Precision Parts Ltd. for $5,940.00 was approved for payment by the VP rules stand-in (offline: no model was called). Main reason: Vendor is on file.
- **invoice_1005.json** (template): INV-1005 from Global Supply Chain Partners for $15,225.00 was rejected by the hard rules. Main reason: STOCK_EXCEEDED: GadgetX: requested 8, only 5 in stock.
- **invoice_1006.csv** (template): INV-1006 from Acme Industrial Supplies for $2,750.00 was approved for payment by the VP rules stand-in (offline: no model was called). Main reason: Vendor is on file.
- **invoice_1007.csv** (template): INV-1007 from MegaWidgets Corp for $15,525.00 was rejected by the hard rules. Main reason: STOCK_EXCEEDED: WidgetA: requested 20, only 15 in stock.
- **invoice_1008.txt** (template): INV-1008 from NoProd Industries for $9,900.00 was rejected by the hard rules. Main reason: UNKNOWN_ITEM: 'SuperGizmo' is not in inventory.
- **invoice_1009.json** (template): INV-1009 for $-250.00 was rejected by the hard rules. Main reason: MISSING_VENDOR: Vendor name is missing.
- **invoice_1010.txt** (template): INV-1010 from Consolidated Materials Group for $7,185.00 was approved for payment by the VP rules stand-in (offline: no model was called). Main reason: Vendor is on file. Condition: Confirm the price against the PO: WidgetA at $300.00 is 20% above catalog $250.00.
- **invoice_1011.pdf** (template): INV-1011 from Summit Manufacturing Co. for $3,000.00 was approved for payment by the VP rules stand-in (offline: no model was called). Main reason: Vendor is on file.
- **invoice_1011.txt** (template): INV-1011 from Summit Manufacturing Co. for $3,000.00 was rejected by the hard rules. Main reason: DUPLICATE_INVOICE: Same invoice already received as invoice_1011.pdf.
- **invoice_1012.pdf** (template): INV-1012 from QuickShip Distributers for $9,975.00 was held for a person by a hard hold rule. Main reason: VENDOR_RENAMED: Vendor says it was formerly 'FastShip Ltd.' (on file); new name is not, so verify bank details; hold for human verification of the vendor and bank details.
- **invoice_1012.txt** (template): INV-1012 from QuickShip Distributers for $9,975.00 was rejected by the hard rules. Main reason: DUPLICATE_INVOICE: Same invoice already received as invoice_1012.pdf.
- **invoice_1013.json** (template): INV-1013 from Atlas Industrial Supply for $22,562.80 was rejected by the hard rules. Main reason: STOCK_EXCEEDED: WidgetA: requested 22 across lines [1, 4, 7], only 15 in stock.
- **invoice_1013.pdf** (template): INV-1013 from Atlas Industrial Supply for $22,562.80 was rejected by the hard rules. Main reason: STOCK_EXCEEDED: WidgetA: requested 22 across lines [1, 4, 7], only 15 in stock.
- **invoice_1014.xml** (template): INV-1014 from TechParts International for $4,455.00 was held for a person by a hard hold rule. Main reason: CURRENCY_CONVERTED: Billed in EUR; $4,125.00 EUR = $4,455.00 USD at mock rate 1.08; hold for a person to confirm the USD amount; nothing is paid at a fixed rate.
- **invoice_1015.csv** (template): INV-1015 from Reliable Components Inc. for $6,500.00 was approved for payment by the VP rules stand-in (offline: no model was called). Main reason: Vendor is on file.
- **invoice_1016.json** (template): INV-1016 from Widgets Inc. for $3,233.00 was rejected by the hard rules. Main reason: UNKNOWN_ITEM: 'WidgetC' is not in inventory.
