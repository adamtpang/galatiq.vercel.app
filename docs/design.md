# Design, assumptions and testing

Moved here from the README after independent review 2. The README has the short version.

## Architecture

```
file ─▶ Ingest ─▶ Validate ─▶ Risk ─▶ Approve ─▶ Memo ─▶ Guard ─┬─▶ Pay (mock_payment, idempotent, retries)
                                                                ├─▶ Reject (logged with reasons and memo)
                                                                └─▶ Hold (human review queue)
```

A LangGraph `StateGraph` (`invoice_agents/graph.py`) passes one typed `InvoiceState` (Pydantic v2) through the nodes. Each node appends to a JSONL trace. There are six Grok agents, each with its own prompt and Pydantic output schema: the extractor, the risk reviewer, the VP, the critic, the rejection reviewer and the memo writer. Validation and payment are deterministic code. Offline no model is called: rules stand-ins (fixed rules written from the agents' prompts) take the place of the risk reviewer, VP, critic and rejection reviewer, a template writes the memo, and there is no cross-check. The CLI, report and site label them "rules stand-in" (decision 19).

- **Ingest** (`agents/ingestion.py`): pdfplumber layout text with a PyMuPDF fallback, then format parsers for text/email, CSV, JSON, XML and PDF. Fixes OCR look-alikes inside numbers (`2O26`, `$3,500.O0`), normalizes dates, maps item names to SKUs with a confidence score. The parser's reading is the one used. Live, the Grok extractor also reads every file the parser read, and the two readings are compared on vendor, number, total, line items and unit prices (trace step `grok_cross_check`); any difference is an `EXTRACTION_DISAGREEMENT` and a hard hold (decision 12). When the parser cannot read a file, Grok rebuilds it from the raw text (trace step `llm_repair`) and the repair is checked against the file: is the file intact, and is every number Grok reported printed in it (decision 14).
- **Validate** (`validation.py`): small pure functions for inventory, arithmetic, dates, currency, prices, vendor, bank details and duplicates. Each returns flags with a code, a severity (info, warn, block) and evidence. NaN, infinite, zero, negative and fractional amounts are blocking (decision 15). A batch prescan finds revisions and duplicates before any decision, and every invoice is also compared with the invoices stored by earlier runs.
- **Risk** (`agents/risk.py`): weighted signals from `config/policy.yaml` (urgency wording, wire pressure, unknown vendor, watch-listed address, total just under the limit, vendor rename, math mismatch, price variance, instruction-like text), score 0 to 100. In live mode Grok gets three read-only tools through function calling (`lookup_vendor`, `query_inventory`, `vendor_history`), checks the invoice's claims against them, then adds reasons and can raise the score, never lower it. Its answer also has a boolean `prompt_injection` field with the quoted words; `true` triggers the injection hard hold. Every tool call and result is in the trace. Grok's risk review is skipped when a hard rule already failed.
- **Approve** (`agents/approval.py`): hard rules (a rejection then goes to the rejection review, which can only agree or escalate it to a person, decision 18), then the hard holds, then a VP agent, then a critic loop when triggered. Every model answer is a Pydantic schema (`VPOpinion`, `CriticOpinion`, `RiskReview`, `ExtractedInvoice`, `DecisionMemo`) requested as JSON schema output and validated before use.
- **Memo** (`agents/memo.py`): after the decision is final, Grok writes a short memo for the AP clerk and the audit log on every invoice, hard-rule rejections included, plus the next step. It is stored with the decision, shown in the review queue, the UI and `report.md`, and never read back by any agent, so it cannot change an outcome (the code asserts the decision is unchanged). Offline a template writes it.
- **Guard** (`graph.py`, `fail_closed`): runs after the memo. An APPROVED invoice with a step error becomes PENDING_HUMAN, one with a blocking flag becomes REJECTED, and an invoice with no decision is held. Only a clean APPROVED invoice is routed to Pay. An exception in ingestion, validation or risk is recorded as an INTERNAL_ERROR flag; an exception in the approval step holds the invoice; a crash of the whole graph for one invoice holds that invoice and the batch goes on (decision 16).
- **Pay** (`agents/payment.py`): wraps the case's `mock_payment` unchanged. An idempotency key in SQLite stops double payment, 3 retries with exponential backoff, `--chaos` fault injection, and a last guard: it rejects an amount that is not a finite number above zero or a non-USD amount with no USD conversion, and holds the invoice for a person when it has a step error, a blocking flag (unless a person approved it) or an interrupted earlier payment. A payment that still fails after the retries is queued for review as PAYMENT_FAILED. Rejections go to an audit log; holds go to the `review_queue` table.

Design rules: the LLM never computes or changes an amount. Invoice text is passed inside `<invoice_document>` tags and treated as data, not instructions; fence and role tags inside the text (for example `</invoice_document>`) are neutralized first, so the text cannot close the fence (decision 17). Any blocking flag means REJECTED, whatever the model says. These mean PENDING_HUMAN before the VP is asked (hard holds): a detected prompt injection, a renamed or lookalike vendor, changed bank details, a Grok reading that disagrees with the parser, a Grok-rebuilt invoice whose reading is not grounded in the file, an invoice-like file nobody could read, an internal error, and (live) a Grok check that failed to run (decisions 8 to 12, 14, 16 and 17).


## The two loops

**Self-correction (extraction).** When the deterministic parser fails, `GrokClient` asks for JSON matching the invoice schema. If Pydantic rejects the answer, the validation errors go back to the model, up to 3 attempts, and every attempt is traced. The same loop wraps every structured call (cross-check, risk, VP, critic, memo).

The 20 samples never need a repair, because the parsers read every file; live, Grok still reads each one as the cross-check. The extras in `data/invoices_extra/` include a free-form email with quantities in words (2001) and a truncated JSON file (2003). In the committed live run (`runs/demo/extra_live`) Grok extracted both on its first attempt, and both are still held for a person: the email's quantities and one price are not printed in the file as digits, and the JSON is damaged, so the reading is not grounded (decisions 10 and 14). `python main.py review INV-2003` shows the original text next to Grok's reading. Offline, the parser cannot read them, and since they look like invoices they are held with an `UNREADABLE_LAYOUT` reason instead of being rejected. The unseen-layout eval shows the other side: live, Grok's grounded readings of new layouts go on to the normal review (see "Evals"). Because Grok's first answer passed validation each time, the retry itself is proven by `tests/test_agentic.py`: a scripted client returns `"qty": "six"` first, and the test checks that the exact Pydantic error went back to the model and the second answer was used.

**Critique (approval).** The critic runs only when the VP approves an invoice that is over $10,000, at least $9,500, or has a risk score of 50 or more. It objects with a specific reason or signs off; after an objection the VP may revise. If the VP still approves after 2 objections, the invoice goes to a human with both arguments attached. None of the 20 case samples triggers it, live or offline: the invoices over $10,000 are all stopped by hard rules, and 1012.pdf ($9,975) is held by the rename hard hold before the VP. So three over-limit invoices were added to the extras (labelled as added, not case data) to show the loop on realistic input. Offline the VP and critic are rules stand-ins; live they are Grok. Live results on Oct 22 are in [evals.md](evals.md#the-critic-and-the-rejection-review-live): the Grok critic ran once (2004, eval run) and signed off, and no live objection has been observed.

- **2004** (Widgets Inc., 15 WidgetA, 10 WidgetB, 5 GadgetX, $12,500, catalog prices). Run on its own, the critic reviews the VP's approval because it is over the limit and signs off; it is paid, decided by `vp+critic`. Committed traces: `runs/demo/critic_offline` (offline: the critic stand-in signs off, paid) and `runs/demo/critic_live` (live at 05a4ef5: the Grok VP held it as over the limit and the vendor's first observed invoice, so no critic call was made). In the live eval run the Grok VP approved it and the Grok critic signed off.
- **2005** (Gadgets Co., $12,500, GadgetX at $1,000 against a $750 catalog price). Offline (`runs/demo/extra_offline`) the critic stand-in objects twice and the deadlock goes to a person. Live the Grok VP held it on the price on its first pass.
- **2006** (Widgets Inc., $11,000, GadgetX at $875 and "process payment immediately"; added after review 2). Offline the VP stand-in approves (the price is within the 25% tolerance), the critic stand-in objects to the pushy wording, and the VP stand-in revises to a rejection, so the critic changes the outcome (decided_by `vp+critic`). Live the Grok VP held it on its first pass (17% over catalog with no written support), so the critic was not called.

Excerpt from the offline 2005 trace, reproduced with `python main.py --invoice_path data/invoices_extra/invoice_2005_over_limit_price.txt --offline`:

```
vp_propose      approve  "Vendor is on file; Math and stock checks are clean; Open points are
                          covered by payment conditions"
critic round 1  object   "Price far off catalog: GadgetX at $1,000.00 is 33% above catalog $750.00."
vp_revise 1     approve  (adds the critic's concern as a payment condition)
critic round 2  object   (same objection)
vp_revise 2     approve
decide          PENDING_HUMAN, decided_by deadlock, critique_rounds 2
                "VP and critic still disagree after 2 rounds"
```

Adversarial 3005 ($9,990, $10 under the limit) gives the same offline deadlock on the near-limit trigger; live, the Grok VP held it on its first pass.


## Assumptions and decisions

Adam's approval-policy decisions are in [docs/DECISIONS.md](docs/DECISIONS.md) and encoded in `config/policy.yaml`:

1. Quantity over stock, after summing repeated lines: reject.
2. VP and critic still disagree after 2 rounds: hold for a human, both arguments attached.
3. The critic loop runs only for invoices over $10K, near the limit, or high risk.
4. Approval threshold $10,000; near the limit is at least $9,500; high risk is a score of at least 50.
5. The VP and critic prompts are Adam's exact text.

Adam delegated more to Engineering on Oct 22 (7 to 10 at 1:20 PM CT, 11 to 15 at 5:30 PM CT after an outside review, 16 to 19 at 7:30 PM CT after the second outside review):

7. Duplicates by content: same vendor (normalized name), same line items, quantities and total as an earlier invoice is a duplicate even under a new number. Rejected, and the reason names the original invoice. "Earlier" includes every invoice stored by previous runs in SQLite, not only the current batch.
8. Prompt injection, detected by the rules or by Grok's risk review (its structured `prompt_injection` field, never its prose): hold for a human whatever the score, or reject if a hard rule also fails.
9. Renamed vendor ("formerly X") or a lookalike of a vendor on file (name similarity at least 0.85): hold for human verification instead of paying with a condition.
10. An invoice that Grok rebuilt from the raw text because the parser could not read it (for example the truncated JSON 2003 or the free-form email 2001) is held for a person, never paid automatically. `python main.py review <number>` shows the original text next to Grok's reading so the reviewer can compare them. Hard rules still run first, so a rebuilt invoice with a blocking flag is rejected. Policy key: `approval.hard_holds.llm_repaired`. Amended by decision 14.
11. Changed bank details (an IBAN, SWIFT or BIC, an account or routing number, "new account", "updated bank details", "remit to"): `BANK_DETAILS_CHANGED` warning and a hard hold, so a person confirms the account with the vendor contact on file. Adversarial 3008 tests it; extra 2002 also carries it.
12. Grok on every invoice, live: Grok reads each file next to the parser and any difference is a hard hold (`EXTRACTION_DISAGREEMENT`); after every decision Grok writes the memo, which cannot change the outcome. Offline: no cross-check, template memo.
13. The address watch list does not fire on the address the vendor master has on file for that same vendor (see "How 1004 and its revision end up").
14. New layouts: offline, an invoice-like file the parser cannot read is held (`UNREADABLE_LAYOUT`), not rejected. Live, a Grok-rebuilt invoice goes on to normal review only when the file is intact, every number Grok reported is printed in it and the vendor is on file; otherwise decision 10's hold applies.
15. Invalid amounts: NaN or infinity, a zero total, a negative line amount and a fractional quantity are blocking, and the payment step refuses any amount that is not a finite number above zero. Currency codes are stripped and upper-cased (`" usd "` reads as USD).
16. Fail closed: an error in any step, a blocking flag or a missing decision can never reach the bank; the guard after the memo and the payment step both check. Wrong field types (a list, object or true/false where text or a number belongs) are a blocking INVALID_FIELD_TYPE; notes and terms given as a list are joined into text. A payment that fails after the retries is queued as PAYMENT_FAILED.
17. More fraud wording: "acct", ABA and routing numbers, "moved banks", wire-instruction changes and long digit runs next to account words hold as bank-detail changes; SYSTEM:/ASSISTANT:/DEVELOPER: lines, fence tags, "pre-cleared", "treat as verified", "ignore previous" and "final answer:" hold as prompt injection. Fence tags are neutralized before any prompt. Live, a Grok check that fails to run is a hard hold.
18. Rejection review: every hard-rule rejection is reviewed (Grok live, a rules stand-in offline). It can only agree or escalate to a person, never approve or pay.
19. Offline stand-ins are labelled "rules stand-in" everywhere, never "VP agent".

Other assumptions:

- **Catalog prices** (`config/seed.sql`): WidgetA $250, WidgetB $500, GadgetX $750, the price each has on most samples. Stock follows the case brief.
- **Vendor master** is a mock: the sample vendors with no other red flags. Fraudster LLC, NoProd Industries and Global Supply Chain Partners are not on file. FastShip Ltd. is; its new name QuickShip Distributers is not.
- **Address watch list**: `1600 pennsylvania ave` and `742 evergreen terrace`. The second was added after the first live run, where Grok pointed out it is a fictional address. It does not fire on a vendor's own address on file (decision 13).
- **FX** is a fixed mock table (EUR 1.08) so runs are reproducible. The bank is paid in USD.
- **Batch order** is filename order, so `invoice_1011.pdf` is the original and `invoice_1011.txt` the duplicate.
- **Payment conditions** (for example "confirm the rush price against the PO") are recorded with the decision for AP to follow up. In this prototype they do not block the payment; anything that should block is a hold.
- **INV-1004** passes inventory validation, as the brief expects, but it is not paid: revision R1 (`invoice_1004_revised.json`) supersedes it, and R1 is paid offline (see "How 1004 and its revision end up").
- **Terms mismatch** ("Net 15" with a 16 or 17 day due date) is info only offline. Grok sometimes holds on it.
- Validation does not decrement stock across invoices in a batch.
- **Duplicates across runs.** Each processed invoice is stored in the `invoices` table with three keys: its number and vendor, its fingerprint (number, vendor, total, revision) and its content (vendor, items, quantities, total). Every new invoice is checked against the current batch and against the stored history, so `--batch data/invoices_adversarial` run on its own after the sample batch still rejects 3006 as a copy of INV-1001 and names the earlier run and its payment. Only the earliest stored copy counts, so re-running the same file is idempotent: an approved invoice shows `already_paid`, a copy stays a rejected copy, and an invoice a person already decided keeps that decision instead of going back into the queue.
- **Past due dates are a warning, not a decision.** An invoice whose due date is before the day of the run gets a `PAST_DUE` warning with the number of days. It shows in the CLI table, report.md and on the site, but the risk, VP and critic agents do not see it, so it changes no decision; AP still pays a past-due invoice. Every sample is dated January or February 2026, so in an October run nearly all of them carry it. Due dates that are not dates ("yesterday") are blocking. The reference date is `due_dates.as_of` in `config/policy.yaml` (default: the day of the run).
- **Other currencies.** EUR, GBP and CAD are converted at the fixed mock rates. A currency with no rate (for example JPY), or amounts written with another currency's symbol or code (`¥5,000.00`, `500.00 EUR` on an invoice that reads as USD), get a blocking `UNSUPPORTED_CURRENCY` flag that names the currency, instead of failing later as "no line items" or being read as dollars.
- **Size limit:** a file over 10 MB is rejected at ingestion without being read.


## Overfitting, honestly

Much of the offline behaviour was built while looking at the same files it is scored on. The parsers were written against the 20 samples, so their 99 of 99 sample fields are in-sample. The mock vendor master is the sample vendors without other red flags, so "not on file" for Fraudster LLC, NoProd Industries and Global Supply Chain Partners follows from how it was built. Both address watch-list entries come from sample files. The injection patterns were widened after adversarial 3002 slipped through, and the unreadable-layout heuristic learned the word "bill" from extra 2001. None of that is evidence the rules generalize.

What does test generalization: the adversarial set (15 invoices, expected outcomes written before each run) and the unseen-layout set in `data/invoices_unseen/` (4 invoices in layouts the parsers were never tuned on, expected outcomes in `evals/unseen_expected.yaml` written before the first run). Offline the parsers read none of the 4 unseen layouts, and all 4 are held for a person rather than rejected. Live (at 05a4ef5), Grok read all 4 correctly and all 4 were paid after the normal review. Four files is a small sample, not proof. In production the vendor master, watch list and patterns would come from Acme's ERP and from shadow-mode data, not from the test files.


## What was cut, and a production plan

Cut for the take-home: a real email or upload inbox, a production review UI (`python main.py ui` is a local, single-user prototype with no login), a real vendor master and ERP connection, live FX rates, stock reservation across a batch, auth, and any real bank call.

A 3 to 6 week plan:

- **Weeks 1 to 2:** connect to Acme's mailbox and ERP (vendor master, POs, inventory). Add PO matching (2 and 3 way) and check bank details against the vendor master (today any bank-detail text is held). Run in shadow mode next to the AP team on last quarter's invoices and measure agreement.
- **Weeks 3 to 4:** a production review UI for the hold queue with the trace and flags, SSO, role-based approval limits, an audit export, Postgres instead of SQLite, a job queue with retries and dead letters. Evaluation set built from the shadow run, run in CI against every prompt or policy change.
- **Weeks 5 to 6:** go live for low-risk known vendors under $10K first, humans approve everything else. Monitoring on hold rate, override rate, latency and model cost. Widen auto-approval only where the override rate stays low.


## Business impact

The case gives the inputs: about $2M a year in manual processing, a 30% error rate and 5-day delays. What the samples show directly: offline the system decided 19 of 20 invoices without a person (live at 05a4ef5, 16 of 20 in both the demo run and the eval run). The offline batch takes under a second; the live batch took 844.6 s in the demo run and 778.9 s in the eval run, and every rejection names the failing check. Model cost in the live eval run was $0.6575 for the 20 samples, $0.0329 per invoice, with Grok called on every invoice (see [evals.md](evals.md)).

A rough estimate, with assumptions stated so they can be replaced with Acme's real numbers:

- Assume 70% of the $2M is people touching invoices (entry, checking, chasing approvals).
- Assume a human still handles the held share, 10% to 20% of invoices as on the samples, plus spot checks.
- Then touch work falls by roughly 80% to 90%, about $1.1M to $1.25M a year (80% to 90% of $1.4M), before the cost of running the system and the review team.

Not estimated: losses from paying wrong or fraudulent invoices, early-payment discounts from paying in hours instead of 5 days. Both need Acme's data.


## Testing

- `pytest`: 394 offline tests in about 20 seconds, no network. Parsers on all 20 files, every validation check, payment idempotency, retries and chaos, the HITL queue, approval rules, the hard holds and the critic loop, a golden test (`tests/golden.yaml`) that pins the expected offline decision and paid amount for every sample, and `tests/test_agentic.py`, which drives the real `GrokClient` with a scripted OpenAI-compatible client to test the self-correction retry, the tool-call loop (including an unknown tool) and API retries. `tests/test_evals.py` runs the five evals offline and pins their numbers (see "Evals"). `tests/test_history.py` covers duplicates against stored history across separate runs, idempotent re-runs, and the review command approving and rejecting a held invoice end to end, plus decision 10 (a Grok-rebuilt invoice held, shown next to its original, then approved). `tests/test_cache.py` covers the decision cache (a re-run reuses every answer and is identical; with `--no-cache` a drifting scripted model differs; the key ignores line endings but not content or model) and the model pin (a different reported model holds; the configured one is quiet). `tests/test_history.py` also checks the backfill: an old row with empty history keys is filled in on connect and then catches 3006. `tests/test_validation.py` covers PAST_DUE and UNSUPPORTED_CURRENCY, and `tests/test_approval.py` checks the injection patterns on held-out injections and on harmless notes. `tests/test_review_fixes.py` covers the outside-review fixes: NaN, infinity, zero, negative and fractional amounts rejected and the payment guard, currency codes normalized, the bank-details hold and harmless notes that must not trigger it (adversarial 3008 is pinned in the adversarial eval), the Grok cross-check (agreement, and a disagreement as a hard hold), the memo (written on every invoice, cannot change a hard-rule rejection), the unreadable-layout hold (and a non-invoice still rejected), the grounded-repair rule, and the 80-column table wrapping on word boundaries. `tests/test_review2.py` covers the second outside review: a wrong type in every field, a simulated exception in each step (nothing pays), the payment guard on errors, blocking flags and an interrupted payment, each bank-change and injection wording plus harmless notes and no false positive on the 20 samples, the fence neutralization, the rejection review (escalates, never pays), extra 2006 (the critic objects and the VP revises), the rules stand-in labels, every console log line being valid JSON (also through the CLI), failed payments queued, local dates with a zone, and the payment cell wrapping at 80 columns. `tests/test_ui.py` drives the review UI over HTTP (queue page, approve pays and writes the audit log, reject logs without paying, an unreadable file cannot be approved, bad token and foreign Host refused). `tests/test_cli.py` runs the brief's literal `invoice1.txt` command. `parse_text` was split into small helpers; its output on 341 inputs (every sample, extra, adversarial and edge file plus 300 shuffled line sets) was compared before and after and is identical.
- `pytest -m live`: one real Grok extraction of invoice 1001 (needs `XAI_API_KEY`).
- Container: `docker build -t galatiq-invoices .` then `docker run --rm galatiq-invoices` (the offline batch) or `docker run --rm galatiq-invoices pytest -q`. Mount `-v galatiq-state:/app/state` to keep the database, and with it the review queue, between runs. Built and run on Python 3.12 with podman 5.4 for this submission; docker was not available on the build machine, but the file is a standard Dockerfile.
- CI runs the offline suite on Python 3.11 and 3.12 plus an offline batch run. The workflow source is in `ci/github-actions-ci.yml`; the active copy is `.github/workflows/ci.yml`.


## Project layout

```
main.py                     CLI: single file, --batch, review, ui, eval, --offline, --mode, --chaos
config/policy.yaml          thresholds, risk weights, watch list, FX table
config/seed.sql             schema and seed data
invoice_agents/
  models.py                 Invoice, Flag, Decision, InvoiceState (Pydantic v2)
  normalize.py, parsers/    OCR fixes, money, dates, SKUs; one parser per format
  validation.py             validation checks and flags
  agents/                   ingestion (parser, Grok cross-check and repair), risk, approval (VP, critic, rejection review), memo, payment
  graph.py                  LangGraph StateGraph
  llm.py                    GrokClient, OfflineClient
  hitl.py, reporter.py      review queue; summary table, review view, summary.json, report.md
  ui.py                     local review UI (python main.py ui, stdlib HTTP server on 127.0.0.1)
tests/                      unit and golden tests
runs/demo/                  committed offline and live runs (samples, extras, and 2004 alone for the critic)
scripts/                    DB setup, run_log and web data exporters
data/invoices_extra/        6 extra test invoices (added, not from the case)
data/invoices_adversarial/  15 adversarial invoices for the eval (added, not from the case)
data/invoices_unseen/       4 invoices in layouts the parsers were never tuned on (added, for the eval)
evals/                      python -m evals: ground truth, expected outcomes, pricing, results
docs/                       evals.md, design.md, run_log.md, DECISIONS.md, demo_script.md, presentation.md
web/                        static trace-replay demo (Vercel); data in web/data/ (scripts/export_web_data.py, python -m evals --write-snapshot)
Dockerfile                  offline container (python:3.12-slim); state in /app/state
```

`data/invoices/` and `data/generate_pdfs.py` are copied unchanged from [galatiq-ai/galatiq-case-invoices](https://github.com/galatiq-ai/galatiq-case-invoices).

