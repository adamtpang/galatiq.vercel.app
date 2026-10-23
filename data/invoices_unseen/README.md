# Unseen-layout invoices (added for the eval, not part of the case data)

Added Oct 22, 2026 after the independent review, to test layouts the parsers were never shown.
Each one is an ordinary, legitimate invoice: a vendor on file, items in stock, clean math, no
pressure or bank wording. They were written, and their expected outcomes put in
`evals/unseen_expected.yaml`, before any run of the pipeline on them, and the parsers were
not changed to read them. So this folder measures what happens with a layout nobody tuned for.

| File | Layout |
|---|---|
| invoice_4001_supplier_at.txt | "Supplier:" label, lines as `2 x WidgetA @ 250.00 = 500.00`, "Amount due" |
| invoice_4002_pipe_table.txt | Markdown-style pipe table, "Invoice total" |
| invoice_4003_prose_email.txt | Plain email prose: "4 WidgetB at $500.00 each, $2,000.00 in total" |
| invoice_4004_odd_headers.csv | CSV with unfamiliar column names (supplier_name, units, price_each, grand_total) |

What should happen (decision 14): offline, an invoice the parser cannot read is held for a person,
never rejected and never paid. Live, Grok reads it; when every number Grok reports is printed in
the file and the checks reconcile, it goes on to normal review and can be paid.
