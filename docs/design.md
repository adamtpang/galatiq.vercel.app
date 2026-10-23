# Design, assumptions and testing

## Architecture

```
file ─▶ Ingest ─▶ Validate ─▶ Risk ─▶ Approve ─▶ Memo ─▶ Guard ─┬─▶ Pay (mock_payment, idempotent, retries)
                                                                ├─▶ Reject or supersede (logged with reasons)
                                                                └─▶ Hold (human review queue)
```

A LangGraph `StateGraph` (`invoice_agents/graph.py`) passes one typed `InvoiceState` (Pydantic v2, validated on assignment) through the nodes; each node appends to a JSONL trace. Live there are six Grok agents, each with its own prompt and Pydantic output schema: extractor, risk reviewer, VP, critic, rejection reviewer and memo writer. Offline no model is called: rules stand-ins written from the prompts take their place and a template writes the memo.

- **Ingest:** format parsers (text, email, CSV, JSON, XML, PDF), OCR fixes inside numbers, SKU matching with a confidence. Live, Grok also reads every file and any difference from the parser is a hold (decision 12); when the parser fails, Grok rebuilds the invoice and the rebuild must be grounded in the file (decisions 10 and 14).
- **Validate:** small pure checks (stock, arithmetic, dates, currency, prices, vendor, bank wording, duplicates across the batch and earlier runs), each a flag with a severity and evidence.
- **Risk:** weighted signals from `config/policy.yaml`; live, Grok uses three read-only tools (`lookup_vendor`, `query_inventory`, `vendor_history`) and can raise the score, never lower it.
- **Approve:** hard rules (then a rejection review that can only escalate), a superseded original gets SUPERSEDED (decision 24), then hard holds, the VP, and the critic loop when triggered; overbilling holds after the loop (decision 23).
- **Memo, Guard, Pay:** the memo is written after the decision and never read back. The guard and the payment step each refuse anything with an error or a blocking flag. Payment is idempotent with retries; a payment that keeps failing is queued.

## The two loops

**Self-correction.** When a structured answer fails Pydantic validation, the errors go back to Grok, up to 3 attempts, every attempt traced. Grok's first answer has always passed live, so the retry is proven only by `tests/test_agentic.py` with a scripted model.

**Critique.** When the VP approves an invoice over $10,000, near the limit or high risk, the critic objects or signs off and the VP may revise; after 2 objections it goes to a person. No sample reaches it, so extras 2004 to 2006 were added. Offline, 2005 deadlocks and 2006 is revised to a rejection. Live, the critic ran once (2004, signed off). On Oct 23, three more invoices were written to make it object (`data/invoices_critic/`, traces `runs/demo/critic_live_2007` to `_2009`); the Grok VP held all three on its first pass, so the critic was never called.

## Assumptions

- Catalog prices: WidgetA $250, WidgetB $500, GadgetX $750; stock follows the brief.
- The vendor master is a mock: the sample vendors with no other red flags.
- The address watch list is two addresses; it skips a vendor's own address on file.
- FX is a fixed mock table, display only; non-USD invoices are held.
- Batch order is filename order, so the first copy of a duplicate is the original.
- Payment conditions are recorded, not enforced; anything that must block is a hold.
- INV-1004 passes validation but is superseded by R1, which is paid offline.
- A Net-terms mismatch is info only; past-due dates are a display-only warning.
- Stock is not decremented across invoices in a batch.

## Overfitting, honestly

Parsers, vendor master, watch list and patterns were written while looking at these files, so sample scores are in-sample. The adversarial set (15) and unseen layouts (4) test generalization, and they are small.

## Cut, and a production plan

Cut: a real inbox, ERP and vendor master, live FX, stock reservation, a production review UI with auth, any real bank call.

- **Weeks 1 to 2:** mailbox and ERP connectors, PO matching, bank details checked against the vendor master; shadow mode next to the AP team.
- **Weeks 3 to 4:** production review UI with SSO and role limits, Postgres, a job queue, an eval set from the shadow run in CI.
- **Weeks 5 to 6:** go live for low-risk known vendors under $10K; widen only where the override rate stays low.

## Business impact

The case gives about $2M a year in manual processing, a 30% error rate and 5-day delays. Offline, 17 of the 20 samples finish without a person (5 paid, 11 rejected, 1 superseded original) and 3 are held; live at 05a4ef5, 16 of 20 finished without a person in both runs. Live cost was $0.0329 per invoice.

A rough estimate, with assumptions to replace with Acme's numbers:

- Assume 70% of the $2M is people touching invoices.
- Assume people still handle the held share, 15% to 20% of invoices as on the samples, plus spot checks.
- Then touch work falls by roughly 80% to 85%, about $1.1M to $1.2M a year, before running costs.

Not estimated: fraud losses avoided and early-payment discounts.

## Testing

`pytest` runs the offline suite in about 25 seconds with no network: parsers, every validation check, payment idempotency and chaos, the review queue and UI, approval rules, hard holds, the critic loop, a golden test pinning every sample's decision, the evals, the reviewers' own repro files, and ruff and mypy (`tests/test_static_checks.py`). `make check` runs the same lint, type check and tests. `pytest -m live` makes one real Grok call. CI runs on Python 3.11 and 3.12. A Dockerfile runs the offline batch.
