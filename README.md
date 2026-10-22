# Acme invoice agents (Galatiq case)


**Work in progress:** multi-agent invoice processing for the Galatiq case. Landing page: https://galatiq.vercel.app

Acme Corp loses about $2M a year to manual invoice processing (30% error rate, 5-day delays).
This repo is building a four-stage agent pipeline: **Ingest -> Validate -> Approve (VP + critic loop) -> Pay or reject**, with xAI's Grok as the LLM.

## What exists today

| Stage | Status |
|---|---|
| Ingestion agent (PDF, TXT/email, CSV, JSON, XML) | Built. Deterministic parsers read all 20 sample files. Grok repair runs only when the parser fails. |
| Validation agent (inventory, math, dates, FX, prices, vendors, duplicates) | Built. Emits typed flags (info, warn, block) with evidence. |
| Risk agent | **Stub.** Returns score 0. Adam is designing it. |
| Approval agent | **Stub.** Applies only the hard rule: any blocking flag means REJECTED. Everything else goes to PENDING_HUMAN with "approval agent not built". VP and critic loop are Adam's to design. |
| Payment agent | Built. Wraps the case's `mock_payment` unchanged, checks an idempotency key in SQLite before paying, retries 3 times with exponential backoff, `--chaos` fault injection, rejection log. |
| Human review queue | Built. PENDING_HUMAN invoices go to a SQLite queue; `python main.py review INV-1012 --approve`. |
| Orchestration | Built with LangGraph: ingest, validate, risk, approval, then pay, reject or hold, then report. JSONL trace per run in `runs/<run_id>/trace.jsonl`. |
| Golden tests | `tests/golden.yaml` lists the expected decision for all 20 files. Cases that need the real approval agent are marked xfail ("approval agent pending"). |

## CI

The GitHub Actions workflow is ready in `ci/github-actions-ci.yml` (offline suite on Python 3.11 and 3.12, plus an offline batch run). It is not active yet: it needs to be copied to `.github/workflows/ci.yml` by an account allowed to push workflow files. The badge goes here once it runs.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py --invoice_path=data/invoices/invoice_1001.txt
python main.py --batch data/invoices --offline          # all 20 samples
python main.py --batch data/invoices --chaos 0.3        # bank fails 30% of calls; watch the retries
python main.py review                                   # human review queue
python main.py review INV-1012 --approve --note "called vendor"
pytest                                                  # offline suite, a few seconds
```

Without `XAI_API_KEY` everything runs offline. With a key, `--mode auto` (the default) lets Grok repair invoices the parser cannot read. `pytest -m live` runs one real call.
The database (`inventory.db`) is created on first run. Payments are idempotent across runs, so a second batch run pays nothing new.

## How it works

- **Ingestion** (`invoice_agents/agents/ingestion.py`): reads the file (pdfplumber layout text, PyMuPDF fallback), routes to a format parser, fixes OCR look-alikes inside numbers (`2O26` -> `2026`, `$3,500.O0` -> `$3,500.00`), normalizes dates (ISO, `Jan 30 2026`, `26-Jan-2026`, `MM/DD/YYYY`; `yesterday` is kept as raw text and flagged) and maps item names to SKUs with a confidence score. SKU matching only accepts safe changes (case, spacing, a trailing note like `(rush order)`, OCR look-alikes). It never accepts a match by edit distance, so `WidgetC` stays unknown instead of becoming `WidgetA`.
- **LLM repair** (`invoice_agents/llm.py`): `GrokClient` uses the OpenAI client against `https://api.x.ai/v1` with a JSON schema response. Pydantic validation errors are fed back to the model, up to 3 attempts, and every attempt is traced. Invoice text is treated as data, not instructions. `OfflineClient` makes no calls. Arithmetic is always checked by code, never by the model.
- **Validation** (`invoice_agents/validation.py`): small pure functions (`check_inventory`, `check_math`, `check_dates`, `check_currency`, `check_prices`, `check_vendor`, ...) that each return flags.

### Flag codes

| Code | Severity | Meaning |
|---|---|---|
| UNKNOWN_ITEM | block | Item not in inventory |
| ZERO_STOCK | block | Item exists but stock is 0 |
| STOCK_EXCEEDED | block | Requested qty (summed over repeated lines) > stock. Evidence: item, requested, stock, lines |
| LINES_AGGREGATED | info | SKU on several lines, total still within stock |
| NEGATIVE_QTY, NEGATIVE_PRICE, NEGATIVE_TOTAL | block | Data integrity |
| ZERO_QTY | warn | Line with quantity 0 |
| MISSING_VENDOR, MISSING_ITEMS, MISSING_TOTAL | block | Required field absent |
| MISSING_INVOICE_NUMBER, MISSING_DUE_DATE | warn | Field absent |
| LINE_AMOUNT_MISMATCH, SUBTOTAL_MISMATCH, TOTAL_MISMATCH | block | Arithmetic off by more than $0.01 |
| TAX_MISMATCH | warn | Tax amount does not match the printed rate |
| INVALID_DUE_DATE | block | Due date is relative ("yesterday") or unreadable |
| INVALID_DATE, DUE_BEFORE_ISSUE | warn | Date problems |
| TERMS_MISMATCH | info | "Net N" does not match the due-date gap |
| PRICE_VARIANCE | warn / info | Over 10% above catalog (warn) or over 10% below (info), compared in USD |
| CURRENCY_CONVERTED | warn | Non-USD, converted with the mock FX table |
| UNSUPPORTED_CURRENCY | block | No FX rate |
| SAMPLE_CHARGED | warn | A line marked "Sample" still costs money |
| UNKNOWN_VENDOR, VENDOR_RENAMED | warn | Vendor not on file, or "formerly X" rename |
| VENDOR_NOT_APPROVED | block | Vendor on file but not approved |
| VENDOR_NAME_LOOKALIKE | info | Vendor name contains the buyer's name (Acme) |
| OVER_APPROVAL_THRESHOLD, NEAR_APPROVAL_THRESHOLD | info | Over $10,000, or at least $9,500 |
| DUPLICATE_INVOICE | block | Same number, vendor and total already seen in this run |
| REVISION_SUPERSEDES / SUPERSEDED_BY_REVISION | info / block | A revision (e.g. R1) replaces an earlier copy |
| DUPLICATE_NUMBER_CONFLICT | block | Same number, different content, no revision marker |
| OCR_CORRECTED, SKU_NORMALIZED | info | What the normalizers changed |
| EXTRACTION_FAILED | block | Nothing could be extracted |

## Decisions (Adam)

Source of truth for `config/policy.yaml`:

1. Over-stock (after summing repeated lines): **REJECT**. Encoded as the blocking `STOCK_EXCEEDED` flag with item, requested qty and stock.
2. VP and critic still disagree after 2 rounds: **PENDING_HUMAN**, with both arguments attached.
3. The critic loop runs only for invoices over $10K, near the limit, or high risk. Other invoices are decided by the VP agent alone, after the hard rules.
4. Thresholds: approval $10,000; near the limit means total >= $9,500; high risk means risk_score >= 50 out of 100.

Items 2 to 4 are recorded in `config/policy.yaml` (`approval:`) and will be used by the approval agent once it is built.

## Assumptions

- **Catalog prices** (`config/seed.sql`): WidgetA $250, WidgetB $500, GadgetX $750, the price each item has on most sample invoices. FakeItem has no price (NULL). Stock levels follow the case brief.
- **Vendor master** is a mock. It lists the vendors on the samples that show no other red flags. Fraudster LLC, NoProd Industries and Global Supply Chain Partners are not on file. FastShip Ltd. is on file and its new name, QuickShip Distributers, is not.
- **FX** is a fixed mock table (EUR 1.08 USD) so runs are deterministic.
- **Duplicates and revisions**: a batch is prescanned before any decision, so an original that has a later revision is flagged SUPERSEDED_BY_REVISION and never paid. Across runs, the payment idempotency key prevents paying the same invoice twice.
- **Batch order** is filename order, so `invoice_1011.pdf` counts as the first copy and `invoice_1011.txt` as the duplicate.
- **Payment currency**: the mock bank is paid in USD, using the deterministic FX conversion (1014: EUR 4,125 is paid as $4,455).
- Validation does not decrement stock.

## Project layout

```
main.py                     CLI: single, --batch, review, --offline, --chaos
config/policy.yaml          thresholds, FX table, Adam's decisions
config/seed.sql             schema + seed (inventory, vendors, invoices, payments, audit_log)
scripts/init_db.py          idempotent DB setup
invoice_agents/
  models.py                 LineItem, Invoice, Flag, Decision, InvoiceState (Pydantic v2)
  normalize.py              OCR, money, dates, invoice numbers, SKUs
  parsers/                  text/email, csv (key-value and table), json, xml, pdf
  agents/ingestion.py       parse + optional Grok repair loop
  agents/risk.py            stub (score 0)
  agents/approval.py        stub: hard rule only
  agents/payment.py         mock_payment wrapper, idempotency, retries, chaos, rejection log
  graph.py                  LangGraph StateGraph
  hitl.py                   human review queue
  reporter.py               summary table, summary.json, report.md
  validation.py             validation tools and flags
  llm.py                    GrokClient, OfflineClient
tests/                      parsers, validation, llm, payment, golden (golden.yaml)
web/                        landing page (Vercel)
```

## Data

`data/invoices/` and `data/generate_pdfs.py` are copied unchanged from the case repository
[galatiq-ai/galatiq-case-invoices](https://github.com/galatiq-ai/galatiq-case-invoices).
