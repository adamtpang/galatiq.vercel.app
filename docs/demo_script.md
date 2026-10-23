# Demo script: what to run and what to point at

The original case brief (since removed from the case README) asked for a demo script with the architecture, design rationale, run logs and edge cases. This is that, kept short. Architecture and design are in the [README](../README.md); full run logs are in [run_log.md](run_log.md).

## Setup (once)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 1. One invoice, the exact command from the brief

```bash
python main.py --invoice_path=data/invoices/invoice1.txt
```

The brief's literal path does not exist in the case data, so it runs the matching sample `data/invoices/invoice_1001.txt` and prints a note saying so. `--invoice_path=data/invoices/invoice_1001.txt` gives the same run without the note.

Point at: one JSON line per agent step (ingest, validate, risk, approval, memo, payment), the `mock_payment` output, the summary table, and the trace path `runs/<run_id>/trace.jsonl`.

## 2. The whole batch, offline

```bash
python main.py --batch data/invoices --offline
```

Expected: 6 paid ($30,375.00), 12 rejected, 2 held for a human (1012.pdf and 1014.xml). Same result every run.

## 3. Edge cases worth showing

| Invoice | What happens | Where to look |
|---|---|---|
| 1003 | Fraudster LLC, FakeItem at zero stock, due "yesterday", wire pressure. Rejected by hard rules, risk 60. | flags and risk signals in the trace |
| 1004 + 1004_revised | Revision R1 supersedes the original, so the original is rejected as superseded and never paid. R1 is paid offline ($5,940.00): its address, 742 Evergreen Terrace, is the one on file for Precision Parts, so the watch list does not fire (decision 13). Live, the Grok VP held R1 in the committed run. | `SUPERSEDED_BY_REVISION`, `REVISION_SUPERSEDES`, `ADDRESS_ON_FILE` |
| 1008 | $9,900 from an unknown vendor for items not in inventory. | `UNKNOWN_ITEM` x2 |
| 1009 | Missing vendor, negative quantity, negative total, subtotal that does not add up. | five blocking flags |
| 1010 | WidgetA on two lines (8 + 4 = 12, within stock of 15); the rush line is 20% over catalog. | `LINES_AGGREGATED`, `PRICE_VARIANCE` |
| 1011, 1012, 1013 | Same invoice in two formats. The second copy is rejected as a duplicate. | `DUPLICATE_INVOICE` |
| 1012.pdf | OCR noise fixed (`2O26`, `$3,500.O0`), vendor renamed ("formerly FastShip Ltd."), $25 under the limit. The rename hard hold sends it to a human before the VP (decision 9). | `VENDOR_RENAMED`, decided_by `hard_hold` |
| 1013 | WidgetA, WidgetB and GadgetX each over stock only after summing repeated lines; a "Sample" line is charged; total off by $50. | `STOCK_EXCEEDED` evidence lists the lines |
| 1014 | Billed in EUR. Held for a person, who types the USD amount; nothing is paid at the fixed mock rate (decision 22). | `CURRENCY_CONVERTED` |
| 2004 (extra, added) | A clean $12,500 invoice from Widgets Inc. Over the $10,000 limit, so the critic reviews the VP's approval. Offline the VP and critic rules stand-ins approve it and it is paid (`runs/demo/critic_offline`). Live results vary: in the live eval run the Grok VP approved and the Grok critic signed off; in the committed live demo runs (`runs/demo/critic_live`, `runs/demo/extra_live`) the Grok VP held it, so no critic call was made. | `critic_review`, decided_by `vp+critic` |
| 2005 (extra, added) | $12,500 from Gadgets Co. with GadgetX at $1,000 (catalog $750). Offline the critic rules stand-in objects twice and the deadlock goes to a person (`runs/demo/extra_offline`); live the Grok VP held it on the price. | `critic_review`, `vp_revise`, decided_by `deadlock` |
| 3008 (adversarial) | Known vendor, $1,000, clean math, but asks to pay a new IBAN. Held by the bank-details hard hold (decision 11). | `BANK_DETAILS_CHANGED` |
| 2006 (extra, added) | $11,000 from Widgets Inc. with GadgetX at $875 and "process payment immediately". Offline the VP rules stand-in approves, the critic rules stand-in objects to the pushy wording, and the VP stand-in revises to a rejection (`runs/demo/extra_offline`). Live the Grok VP held it on its first pass (17% over catalog, no written support for the surcharge), so the critic was not called. | `critic_review`, `vp_revise`, decided_by `vp+critic` |
| 3005 (adversarial) | $9,990 from a known vendor. Offline the VP rules stand-in approves, the critic stand-in objects twice (just under the limit), and the deadlock goes to a human. Run it with `python main.py --invoice_path data/invoices_adversarial/invoice_3005_just_under_limit.txt --offline`. | `critic_review`, `vp_revise` |

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
python main.py ui                              # the same queue in the browser, with approve and reject buttons
```

`python main.py ui` serves a local page (http://127.0.0.1:8765 by default, local only) that lists the held invoices with their reason, flags and memo (and the original text when the file could not be parsed); approve pays through the same idempotent payment step, reject logs the rejection.

## 6. Live Grok (needs XAI_API_KEY)

```bash
python main.py --invoice_path=data/invoices/invoice_1012.pdf --mode live
python main.py --batch data/invoices_extra --mode live
```

Point at: `grok_cross_check` (Grok reads every invoice next to the parser; a difference is a hold), `tool_call` events (the risk agent looks up the vendor master, inventory and vendor history before scoring), the `memo` step on every invoice, the `llm_repair` event on the free-form email and the truncated JSON, which the decision 10 hard hold then sends to a person (`python main.py review INV-2003` shows the original next to Grok's reading), and the prompt-injection invoice (2002), which the injection hard hold sends to a human (decision 8).

## 7. The web replay

https://galatiq.vercel.app replays the committed runs in `runs/demo/` invoice by invoice. It is a static page over exported traces; the system itself runs locally.
