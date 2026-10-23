# Acme invoice agents

[![CI](https://github.com/adamtpang/galatiq.vercel.app/actions/workflows/ci.yml/badge.svg)](https://github.com/adamtpang/galatiq.vercel.app/actions/workflows/ci.yml)

**Start here: [READ_THIS_FIRST.md](READ_THIS_FIRST.md)** (one page).

A prototype that reads, checks, approves and pays Acme Corp's invoices (the Galatiq FDE case). Deterministic code
reads the files, does all the math and applies the hard rules. Live, Grok agents read every invoice next to the parser,
review risk with read-only tools, argue the approval as VP and critic, review every hard-rule rejection (they can only
escalate it) and write a memo for every decision. Offline, with no API key, fixed **rules stand-ins** written from the
agents' prompts take their place and no model is called. Every decision has reasons and a full trace.

**Site:** https://galatiq.vercel.app replays the committed runs step by step (the system itself runs locally).

## Run it

Python 3.11 or newer, no API key, about a minute:

```bash
git clone https://github.com/adamtpang/galatiq.vercel.app galatiq && cd galatiq
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && python main.py --batch data/invoices
```

The brief's command works as written: `python main.py --invoice_path=data/invoices/invoice1.txt` runs
`invoice_1001.txt` (the case files start at 1001; the CLI says so) and prints one JSON line per agent step, the
`mock_payment` output, the result table and the trace path.

```bash
python main.py --invoice_path=data/invoices/invoice_1012.pdf   # one invoice
python main.py --batch data/invoices --chaos 0.3               # the bank fails 30% of calls; retries, then queued
python main.py review                                          # the human review queue (CLI)
python main.py ui                                              # the review queue in the browser (127.0.0.1:8765)
python main.py --batch data/invoices --mode live               # Grok agents (needs XAI_API_KEY)
python -m evals                                                # five evals offline, about a second
pytest                                                         # 440 offline tests, about 25 seconds
make check                                                     # ruff, mypy and the tests (scripts/check.sh)
```

`requirements.txt` pins ruff and mypy too, and `tests/test_static_checks.py` runs both, so CI enforces them.

## Results

20 case invoices, each run on a fresh database (details: [docs/evals.md](docs/evals.md)):

| Run | Paid | Rejected | Held for a person | Superseded |
|---|---|---|---|---|
| Offline, rules stand-ins | 5 invoices, $23,190.00 | 11 | 3 | 1 |
| Live demo run, grok-4.7 | 4 invoices, $16,705.00 | 12 | 4 | - |
| Live eval run, grok-4.7 | 4 invoices, $17,250.00 | 12 | 4 | - |

- 1004 is replaced by its revision R1: offline it gets its own SUPERSEDED status and is not paid (decision 24). The
  live runs predate that and logged it as REJECTED; nobody pays it.
- The other 11 rejections are the same in every run. Every other difference is an invoice the rules would pay and the
  Grok VP held, except 1014 (EUR): held offline (decision 22), paid by the live demo run made before that rule.
- Adversarial set (15 added traps): 15 of 15 caught offline and live. Unseen layouts (4): offline all held; live Grok
  read all 4 correctly and all 4 were paid. Extraction: 119 of 127 fields offline, 127 of 127 live.
- Live cost on the 20 samples: 85 Grok calls, $0.6575, 38.9 s per invoice. A cached re-run gave identical decisions
  with 0 calls.

The full live runs were made on Oct 22, 2026 at commit 05a4ef5, before the review 3 fixes and decisions 22 to 24;
see [docs/evals.md](docs/evals.md) for the spot checks since.

## Design

```
file ─▶ Ingest ─▶ Validate ─▶ Risk ─▶ Approve ─▶ Memo ─▶ Guard ─┬─▶ Pay (mock_payment, idempotent, retries)
                                                                ├─▶ Reject or supersede (logged with reasons)
                                                                └─▶ Hold (human review queue)
```

- **Code owns the math.** Grok never computes or changes an amount. Any blocking flag rejects, whatever a model says.
- **Hard holds before any opinion:** prompt injection, renamed or lookalike vendor, any payment-instruction wording,
  non-USD, Grok and the parser disagreeing, an ungrounded Grok reading, an unreadable layout, an internal error, and
  (live) a Grok check that failed. Overbilling (over 10% above catalog, shipping or tax over 15%) holds after the VP.
- **Fail closed.** A crash in any step holds or rejects; the guard and the payment step each refuse an invoice with an
  error or a blocking flag. A payment still failing after 3 retries is queued.
- **A person approving is not one click.** The reviewer types the amount when the numbers do not add up or the
  currency is not USD, and over $10,000 needs a second confirmation (decisions 21 and 23).
- **Prompt hygiene.** Invoice text is fenced as data. **Offline, injection detection is pattern-based**: it catches
  the wordings it was written for, not every wording. **Live, Grok is the real reader.**
- **Two loops.** Extraction self-corrects (Pydantic errors back to Grok, up to 3 attempts). The critic reviews VP
  approvals over $10,000, near the limit or high risk; after 2 objections a person decides.

So **Grok cannot pay anything the rules block**. Decisions 1 to 24: [docs/DECISIONS.md](docs/DECISIONS.md);
architecture, assumptions and the production plan: [docs/design.md](docs/design.md).

## Honest limits

- **Live is not perfectly repeatable** (1001 and 1014 differ between live runs). The decision cache makes a re-run
  identical.
- **The critic has never been seen to object live.** It ran once live and signed off. Five invoices written to make it
  object (2005 to 2009, the last three on Oct 23 for $0.14) were each held by the Grok VP first. The loop is shown
  only offline, with rules stand-ins (2005, 2006).
- **The extraction retry** is proven only with a scripted model; Grok's first answer has always passed live.
- **The live rejection review escalated once** (3014); otherwise it agreed with every rejection.
- **Newer than the full live runs:** the review 3 fixes and decisions 22 to 24, checked live only by spot checks.
- **Overfitting.** Parsers, vendor master, watch list and patterns were written while looking at these files. The
  adversarial and unseen sets test generalization, and they are small.
- **Known, not fixed:** stock is not decremented across a batch; `vendor_history` shows earlier rejections without the
  reason; the review UI shows the original text only for unreadable or Grok-rebuilt files.
- **Cut:** a real inbox, ERP and vendor master, live FX, a production review UI with auth, and any real bank call.

## License

Code is MIT licensed (see [LICENSE](LICENSE)). The sample invoices in `data/invoices/` and `data/generate_pdfs.py`
(and their copies in `web/invoices/`) come from https://github.com/galatiq-ai/galatiq-case-invoices and are not
covered by that license.
