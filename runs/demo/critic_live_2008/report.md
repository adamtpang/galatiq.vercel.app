# Run critic_live_2008 (grok, grok-4.7)

| File | Invoice | Vendor | Total USD | Risk | Blocking flags | Decision | By | Rounds | Payment | Reason |
|---|---|---|---|---|---|---|---|---|---|---|
| invoice_2008_ship_to_vendor.txt | INV-2008 | Reliable Components Inc. | $10,250.00 | 35 | - | PENDING_HUMAN | the VP agent (Grok) | 0 | not_paid | Vendor Reliable Components Inc. is on file |

## Decision memos

- **invoice_2008_ship_to_vendor.txt** (grok): Invoice INV-2008 from Reliable Components Inc. bills Acme $10,250.00. The decision is PENDING_HUMAN: the vendor is on file and the authoritative total of $10,250.00 has clean line math, but the ship-to is Reliable Components Inc. Receiving Dock 3, not Acme, so the goods are not directed to the payer. The flag OVER_APPROVAL_THRESHOLD notes that $10,250.00 is over $10,000.00 and needs extra scrutiny. Do not pay until a person confirms why the shipment goes to the vendor and matches a valid purchase order or return authorization.
