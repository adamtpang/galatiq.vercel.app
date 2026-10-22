# Demo script: what to run and what to point at

The original case brief (since removed from the case README) asked for a demo script with the architecture, design rationale, run logs and edge cases. This is that, kept short. Architecture and design are in the [README](../README.md); full run logs are in [run_log.md](run_log.md).

## Setup (once)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 1. One invoice, the exact command from the brief

```bash
python main.py --invoice_path=data/invoices/invoice_1001.txt
```

Point at: one JSON line per agent step (ingest, validate, risk, approval, payment), the `mock_payment` output, the summary table, and the trace path `runs/<run_id>/trace.jsonl`.

## 2. The whole batch, offline

```bash
python main.py --batch data/invoices --offline
```

Expected: 6 paid ($28,890.00), 12 rejected, 2 held for a human. Same result every run.

## 3. Edge cases worth showing

| Invoice | What happens | Where to look |
|---|---|---|
| 1003 | Fraudster LLC, FakeItem at zero stock, due "yesterday", wire pressure. Rejected by hard rules, risk 60. | flags and risk signals in the trace |
| 1004 + 1004_revised | Revision R1 supersedes the original, so the original is never paid. The revision is held because its address (742 Evergreen Terrace) is on the watch list. | `SUPERSEDED_BY_REVISION`, `REVISION_SUPERSEDES` |
| 1008 | $9,900 from an unknown vendor for items not in inventory. | `UNKNOWN_ITEM` x2 |
| 1009 | Missing vendor, negative quantity, negative total, subtotal that does not add up. | five blocking flags |
| 1010 | WidgetA on two lines (8 + 4 = 12, within stock of 15); the rush line is 20% over catalog. | `LINES_AGGREGATED`, `PRICE_VARIANCE` |
| 1011, 1012, 1013 | Same invoice in two formats. The second copy is rejected as a duplicate. | `DUPLICATE_INVOICE` |
| 1012.pdf | OCR noise fixed (`2O26`, `$3,500.O0`), vendor renamed ("formerly FastShip Ltd."), $25 under the limit. The rename hard hold sends it to a human before the VP (decision 9). | `VENDOR_RENAMED`, decided_by `hard_hold` |
| 1013 | WidgetA, WidgetB and GadgetX each over stock only after summing repeated lines; a "Sample" line is charged; total off by $50. | `STOCK_EXCEEDED` evidence lists the lines |
| 1014 | Billed in EUR, paid in USD at the fixed mock rate. | `CURRENCY_CONVERTED` |
| 3005 (adversarial) | $9,990 from a known vendor. The VP approves, the critic objects twice (just under the limit), and the deadlock goes to a human. Run it with `python main.py --invoice_path data/invoices_adversarial/invoice_3005_just_under_limit.txt --offline`. | `critic_review`, `vp_revise` |

## 4. Payments are safe to retry

```bash
python main.py --batch data/invoices --offline --chaos 0.3 --seed 7   # bank fails 30% of calls
python main.py --batch data/invoices --offline                        # second run pays nothing new
```

Point at: `bank_error` events and retries with backoff, then `idempotency_skip` on the second run.

## 5. Human in the loop

```bash
python main.py review
python main.py review INV-1012                 # what a reviewer sees for one held invoice
python main.py review INV-1012 --approve --note "called FastShip, rename confirmed"
```

## 6. Live Grok (needs XAI_API_KEY)

```bash
python main.py --invoice_path=data/invoices/invoice_1012.pdf --mode live
python main.py --batch data/invoices_extra --mode live
```

Point at: `tool_call` events (the risk agent looks up the vendor master, inventory and vendor history before scoring), the `llm_repair` event on the free-form email and the truncated JSON, which the decision 10 hard hold then sends to a person (`python main.py review INV-2003` shows the original next to Grok's reading), and the prompt-injection invoice (2002), which the injection hard hold sends to a human (decision 8).

## 7. The web replay

https://galatiq.vercel.app replays the committed runs in `runs/demo/` invoice by invoice. It is a static page over exported traces; the system itself runs locally.
