# Run r3spot_t19 (grok, grok-4.7)

| File | Invoice | Vendor | Total USD | Risk | Blocking flags | Decision | By | Rounds | Payment | Reason |
|---|---|---|---|---|---|---|---|---|---|---|
| t19.txt | INV-9219 | Summit Manufacturing Co. | $500.00 | 65 | - | PENDING_HUMAN | a hard hold rule | 0 | not_paid | BANK_DETAILS_CHANGED: Invoice mentions payment instructions or bank details (remit); confirm where to pay with the vendor contact on file before paying; hold for human verification of the vendor and bank details |

## Decision memos

- **t19.txt** (grok): Invoice INV-9219 from Summit Manufacturing Co. is for $500.00 (two WidgetA items). The decision is PENDING_HUMAN, placed on hold by hard_hold. The main reason is the flag BANK_DETAILS_CHANGED: the invoice mentions payment instructions or bank details (remit), so where to pay must be confirmed with the vendor contact on file before any payment.
