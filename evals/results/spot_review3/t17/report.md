# Run r3spot_t17 (grok, grok-4.7)

| File | Invoice | Vendor | Total USD | Risk | Blocking flags | Decision | By | Rounds | Payment | Reason |
|---|---|---|---|---|---|---|---|---|---|---|
| t17.txt | INV-9217 | Summit Manufacturing Co. | $500.00 | 68 | - | PENDING_HUMAN | a hard hold rule | 0 | not_paid | BANK_DETAILS_CHANGED: Invoice mentions payment instructions or bank details (account ending); confirm where to pay with the vendor contact on file before paying; hold for human verification of the vendor and bank details |

## Decision memos

- **t17.txt** (grok): Invoice INV-9217 from Summit Manufacturing Co. is for $500.00 and is on hold as PENDING_HUMAN. The hard hold is because of the BANK_DETAILS_CHANGED flag: the invoice mentions payment instructions and a bank account ending, so payment must not go out until a person confirms where to pay with the vendor contact on file. The risk score is 68.
