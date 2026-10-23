# Acme invoice agents

[![CI](https://github.com/adamtpang/galatiq.vercel.app/actions/workflows/ci.yml/badge.svg)](https://github.com/adamtpang/galatiq.vercel.app/actions/workflows/ci.yml)

**Start here: [READ_THIS_FIRST.md](READ_THIS_FIRST.md)** (one page: what it does, two commands, results, limits).

A prototype that reads, checks, approves and pays Acme Corp's invoices (the Galatiq FDE case). Deterministic code
reads the files, does all the math and applies the hard rules. Live, Grok agents read every invoice next to the parser,
review risk with read-only tools, argue the approval as VP and critic, review every hard-rule rejection (they can only
escalate it to a person) and write a memo for every decision. Offline, with no API key, fixed **rules stand-ins**
written from the agents' prompts take their place and no model is called. Every decision has reasons and a full trace.

**Site:** https://galatiq.vercel.app replays the committed runs step by step (the system itself runs locally).

## Run it

Python 3.11 or newer, no API key, about a minute:

```bash
git clone https://github.com/adamtpang/galatiq.vercel.app galatiq && cd galatiq
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && python main.py --batch data/invoices
```

The brief's command works as written: `python main.py --invoice_path=data/invoices/invoice1.txt` runs
`invoice_1001.txt` (the case files are numbered from 1001; the CLI says which file it used) and prints one valid JSON
line per agent step, the `mock_payment` output, the result table and the trace path.

```bash
python main.py --invoice_path=data/invoices/invoice_1012.pdf   # one invoice
python main.py --batch data/invoices --chaos 0.3               # the bank fails 30% of calls; failed payments are queued
python main.py review                                          # the human review queue (CLI)
python main.py ui                                              # the review queue in the browser (127.0.0.1:8765)
python main.py --batch data/invoices --mode live               # Grok agents (needs XAI_API_KEY)
python -m evals                                                # five evals offline, about a second (--live adds Grok)
pytest                                                         # 437 offline tests, about 20 seconds
```

Each run writes `runs/<run_id>/trace.jsonl` (every step), `summary.json` and `report.md`. Times are local with the
zone shown (for example `2026-10-22 7:36 PM CDT`). At 80 columns the table wraps the reason and the payment cell.

## Results

20 case invoices, each run on a fresh database (details: [docs/evals.md](docs/evals.md), [docs/run_log.md](docs/run_log.md)):

| Run | Paid | Rejected | Held for a person |
|---|---|---|---|
| Offline, rules stand-ins | 5 invoices, $23,190.00 | 12 | 3 |
| Live demo run, grok-4.7 | 4 invoices, $16,705.00 | 12 | 4 |
| Live eval run, grok-4.7 | 4 invoices, $17,250.00 | 12 | 4 |

- The same 12 are rejected in every run (over stock, unknown items, missing vendor, duplicates, a superseded
  revision). Every other live and offline difference is an invoice the rules would pay and the Grok VP held, except
  1014 (EUR): offline it is now held because every non-USD invoice goes to a person (decision 22), and the live demo
  run, made before that change, paid it at the mock rate. Offline 1010 is now held too (a unit price 20% over
  catalog must be checked against the PO, decision 23), as the Grok VP held it live.
- Adversarial set (15 added traps: injections, lookalike and renamed vendors, bank changes, duplicates, wrong types,
  a closing prompt-fence tag): 15 of 15 caught offline and live, and again as a separate later run.
- Unseen layouts (4 added, never tuned on): offline all 4 held for a person; live Grok read all 4 correctly and
  all 4 were paid.
- Extraction: 119 of 127 fields offline, 127 of 127 live.
- Live cost on the 20 samples: 85 Grok calls, $0.6575 billed, 38.9 s mean per invoice. A re-run on the same
  database with the decision cache gave identical decisions for 20 of 20 with 0 calls.

All live results in the table were run on Oct 22, 2026 at commit 05a4ef5 (the review 2 code), before the review 3
fixes (commit 76881f7). Those fixes change one sample result, 1014, now held. They were not re-run live in full;
three live spot checks at 76881f7 (1014 and two of the reviewer's bank sentences) are in `docs/evals.md`. The
committed live runs cost $3.87 billed in total, plus $0.10 for the spot checks.

## Design

```
file ─▶ Ingest ─▶ Validate ─▶ Risk ─▶ Approve ─▶ Memo ─▶ Guard ─┬─▶ Pay (mock_payment, idempotent, retries)
                                                                ├─▶ Reject (logged with reasons and memo)
                                                                └─▶ Hold (human review queue)
```

A LangGraph `StateGraph` passes one typed Pydantic state through the nodes; every node appends to the trace.

- **Code owns the math.** Grok never computes or changes an amount. Any blocking flag rejects, whatever a model says.
- **Hard holds before any opinion:** prompt injection, renamed or lookalike vendor, any wording about where or how to
  pay (bank, account number, wire, ACH, Zelle, PayPal, crypto, escrow, remit-to; live also Grok's
  `payment_details_changed` field), a non-USD invoice, Grok and the parser disagreeing, an ungrounded Grok reading,
  an unreadable layout, an internal error, and (live) a Grok check that failed to run. Each sends the invoice to a
  person.
- **Overbilling is held, not paid with a condition** (decision 23): a unit price more than 10% over catalog (the
  "confirm the price against the PO" condition), a unit price more than 25% over catalog, or shipping or tax over 15%
  of the goods subtotal. This check runs after the VP and critic, so it turns an approval into a hold and never
  changes a rejection. Thresholds are in `config/policy.yaml`.
- **Fail closed.** An exception while reading the file holds the invoice for a person (INTERNAL_ERROR) before any
  other rule. An exception in validation or risk adds an INTERNAL_ERROR flag: a blocking flag found before the crash
  still rejects, otherwise the invoice is held. An exception in the approval step holds it. A guard after the memo turns
  any approval with an error or a blocking flag into a hold or a rejection. The payment step refuses again on its own
  (errors, blocking flags, an interrupted earlier payment, an amount that is not a positive finite USD number). If the
  bank call raises an unexpected exception, or anything else in the payment step raises, the invoice is held for a
  person and nothing is paid (after a bank-call exception the payments row is marked `unknown`: check with
  the bank before paying). A bank error
  that is still failing after 3 retries leaves the invoice approved but unpaid, marked failed and queued as
  PAYMENT_FAILED. Wrong value types (including a quantity like "two") are a blocking INVALID_FIELD_TYPE.
- **A person approving is not one click.** In the review queue (CLI or `python main.py ui`), when the numbers do not
  add up or the currency is not USD the reviewer must type the amount to pay (prefilled with what the lines add up
  to). It must equal the line sum or the printed total to the cent unless the reviewer sets "override amount"
  (`--override-amount`), which is recorded in the audit log; a USD amount for a non-USD invoice always needs the
  override. Any approval paying over $10,000 needs a second confirmation. The server enforces all of it (decision 21).
- **Prompt hygiene.** Invoice text goes inside `<invoice_document>` tags as data; fence and role tags in the text are
  neutralized first. **Offline, injection detection is pattern-based**: regular expressions run on the text after
  Unicode normalization, lower-casing and joining spaced-out letters. They catch the wordings they were written for
  (including the 10 the third reviewer invented), not every wording. **Live, Grok is the real reader**: it reads every
  invoice and its structured `prompt_injection` field holds the invoice like a pattern hit.
- **Two loops.** Extraction self-corrects: Pydantic errors go back to Grok, up to 3 attempts (tested with a scripted model;
  not seen live). Approval: when the VP
  approves an invoice over $10,000, near the limit or high risk, a critic can object and the VP can revise; after 2
  objections it goes to a person with both arguments.
- **Rejection review.** Every hard-rule rejection is reviewed (Grok live, a rules stand-in offline). It can only
  agree or escalate to a person.

So, by construction, **Grok cannot pay anything the rules block**: blocking flags reject before the VP, the rejection
review can only escalate, and the guard and the payment step both refuse an invoice with a blocking flag unless a
person approved it in the review queue. Policy decisions 1 to 23 are in [docs/DECISIONS.md](docs/DECISIONS.md);
architecture, assumptions, testing and the production plan are in [docs/design.md](docs/design.md).

## Honest limits

- **Live is not perfectly repeatable.** Fresh live runs of the same code differ on a few invoices (1001 and 1014
  above). The decision cache makes a re-run of the same invoice identical.
- **The critic has not been seen to object live.** On Oct 22 the Grok critic ran once (2004, eval run) and signed
  off. 2005 and 2006 were written to make it object, but the Grok VP held both on its first pass. Offline, 2005
  (deadlock) and 2006 (the critic objects, the VP revises to a rejection) show the loop with rules stand-ins.
- **The live rejection review escalated once** (3014 in the separate later run); otherwise it agreed with every
  rejection. Its offline rules stand-in escalates only arithmetic-only rejections from known, low-risk vendors.
- **The review 3 fixes are newer than the full live runs** (see Results). Three live spot checks confirm the main
  ones; everything else about them is tested offline.
- **One fix is newer than the live numbers.** The live eval found that Grok's repair could rebuild 3014 and drop its
  wrong-type errors (it was still not paid: a duplicate rule rejected it). Files with wrong types are no longer sent to
  Grok repair. This is tested with a scripted model and spot-checked live on 3014 (see `docs/evals.md`).
- **Earlier live results** came from local checkpoint commits 4719dbe, 982b14f and 849b0af that were never pushed
  to main. They are now on the branch
  [`live-eval-checkpoints`](https://github.com/adamtpang/galatiq.vercel.app/tree/live-eval-checkpoints); every live
  result on main was re-run at 05a4ef5 and replaces them.
- **Overfitting.** The parsers, mock vendor master, watch list and fraud patterns were written while looking at these
  files, so the sample scores are in-sample. The adversarial and unseen sets test generalization, and they are small.
- **Cut:** a real inbox, ERP and vendor master, live FX, a production review UI with auth, and any real bank call.

## License

Code is MIT licensed (see [LICENSE](LICENSE)). The sample invoices in `data/invoices/` and `data/generate_pdfs.py`
(and their copies in `web/invoices/`) come from https://github.com/galatiq-ai/galatiq-case-invoices and are not
covered by that license.
