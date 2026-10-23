# Run r3spot_invoice_1014 (grok, grok-4.7)

| File | Invoice | Vendor | Total USD | Risk | Blocking flags | Decision | By | Rounds | Payment | Reason |
|---|---|---|---|---|---|---|---|---|---|---|
| invoice_1014.xml | INV-1014 | TechParts International | $4,455.00 | 18 | - | PENDING_HUMAN | a hard hold rule | 0 | not_paid | CURRENCY_CONVERTED: Billed in EUR; $4,125.00 EUR = $4,455.00 USD at mock rate 1.08; hold for a person to confirm the USD amount; nothing is paid at a fixed rate |

## Decision memos

- **invoice_1014.xml** (grok): Invoice INV-1014 from TechParts International is billed in euros for $4,125.00 EUR, shown as $4,455.00 USD. The decision is PENDING_HUMAN because of the flag warn CURRENCY_CONVERTED: it was converted at a mock rate of 1.08 and is on hold until a person confirms the USD amount. Nothing is paid at a fixed rate.
