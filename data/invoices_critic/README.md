# Invoices written to make the live critic object (added Oct 23, 2026, not case data)

Each is clean on the hard rules, from Reliable Components Inc. (on file, with INV-1015 paid when the 20 samples run first on the same database), over $10,000 so a VP approval would go to the critic, and carries one subtle problem:

| File | Subtle problem |
|---|---|
| invoice_2007_quarter_close.txt | Asks to "settle this one by Friday" for a quarter close, against Net 30 |
| invoice_2008_ship_to_vendor.txt | Bill to Acme, but ship to the vendor's own dock |
| invoice_2009_price_creep.txt | GadgetX at $810, 8% over the $750 catalog, under the 10% flag |

Each was run live once (`--mode live --no-cache`) after the offline 20-sample batch on a fresh database. In all three the Grok risk review named the problem and the Grok VP held the invoice on its first pass, so the critic was never called. Traces: `runs/demo/critic_live_2007`, `_2008`, `_2009`. Offline, the rules stand-ins approve and pay all three (the critic stand-in sees no rule it checks).
