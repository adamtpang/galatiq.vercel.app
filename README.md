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
python -m pip install -r requirements.txt && python main.py --batch data/invoices --offline
```

Windows PowerShell: `py -3 -m venv .venv`, then use `.\.venv\Scripts\python.exe` in place of `python`.
`--offline` prevents model calls even if an API key is set. The SQLite database is created and seeded
automatically and keeps payment history, so a repeated run does not pay the same invoice twice.

The brief's command works as written: `python main.py --invoice_path=data/invoices/invoice1.txt` runs
`invoice_1001.txt` (the case files start at 1001; the CLI says so) and prints one JSON line per agent step, the
`mock_payment` output, the result table and the trace path.

```bash
python main.py --invoice_path=data/invoices/invoice_1012.pdf --offline  # one invoice
python main.py --batch data/invoices --offline --chaos 0.3      # the bank fails 30% of calls; retries, then queued
python main.py review                                          # the human review queue (CLI)
python main.py ui                                              # the review queue in the browser (127.0.0.1:8765)
python main.py --batch data/invoices --mode live               # Grok agents (needs XAI_API_KEY)
python -m evals                                                # five evals offline, about a second
pytest                                                         # 518 offline tests, including lint and types
make check                                                     # ruff, mypy and the tests (scripts/check.sh)
```

`requirements.txt` pins ruff and mypy too, and `tests/test_static_checks.py` runs both, so CI enforces them.

## Results

20 case invoices, each run on a fresh database (details: [docs/evals.md](docs/evals.md)):

| Run | Paid | Rejected | Held for a person |
|---|---|---|---|
| Offline, rules stand-ins | 5 invoices, $23,190.00 | 12 | 3 |
| Live demo run, grok-4.7 | 4 invoices, $16,705.00 | 12 | 4 |
| Live eval run, grok-4.7 | 4 invoices, $17,250.00 | 12 | 4 |

- 1004 is replaced by its revision R1, which is paid. 1004 passes validation (an info flag) and is REJECTED with
  reason SUPERSEDED_BY_REVISION, decided by `supersession`, not by a blocking flag (decision 24).
- The 12 rejections are the same in every run. Every other difference is an invoice the rules would pay and the
  Grok VP held, except 1014 (EUR): held offline (decision 22), paid by the live demo run made before that rule.
- Adversarial set (15 added traps): 15 of 15 caught offline and live. Unseen layouts (4): offline all held; live Grok
  read all 4 correctly and all 4 were paid. Extraction: 119 of 127 fields offline, 127 of 127 live.
- Live cost on the 20 samples: 85 Grok calls, $0.6575, 38.9 s per invoice. A cached re-run gave identical decisions
  with 0 calls.

The full live runs were made on Oct 22, 2026 at commit 05a4ef5, before the review 3 fixes, decisions 22 to 24 and
the later payment and parser hardening; [docs/evals.md](docs/evals.md) lists the live spot checks since.

## Design

```
file ─▶ Ingest ─▶ Validate ─▶ Risk ─▶ Approve ─▶ Memo ─▶ Guard ─┬─▶ Pay (mock_payment, idempotent, retries)
                                                                ├─▶ Reject (logged with reasons)
                                                                └─▶ Hold (human review queue)
```

- **Code owns the math.** Code computes and validates payable amounts. Model opinions cannot override a blocking flag.
- **Hard holds before any opinion:** prompt injection, renamed or lookalike vendor, any payment-instruction wording,
  non-USD, Grok and the parser disagreeing, an ungrounded Grok reading, an unreadable layout, an internal error, and
  (live) a Grok check that failed. Overbilling (over 10% above catalog, shipping or tax over 15%) holds after the VP.
- **Fail closed.** A crash in any step holds or rejects; the guard and the payment step each refuse an invoice with an
  error or a blocking flag. A payment still failing after 3 retries is queued.
- **A person approving is not one click.** The reviewer types the amount when the numbers do not add up or the
  currency is not USD, and over $10,000 needs a second confirmation (decisions 21 and 23).
- **One payment path.** Automatic and human approvals pay through the same step. A review is versioned and bound to
  its USD amount; a human rejection sticks; an uncertain bank outcome is held for reconciliation; unmet VP
  conditions go to a person.
- **Numbers are read in full.** `$5,000.00 USD` and `$0.00 (exempt)` are read; `(500)` is negative; an unreadable
  number blocks; amounts in A$, CA$, R$ and similar are held for a person, never read as dollars.
- **Prompt hygiene.** Invoice text is fenced as data. **Offline, injection detection is pattern-based**: it catches
  the wordings it was written for, not every wording. **Live, Grok is the real reader.**
- **Two loops.** Extraction self-corrects (Pydantic errors back to Grok, up to 3 attempts). The critic reviews VP
  approvals over $10,000, near the limit or high risk; after 2 objections a person decides.

So **Grok cannot pay anything the rules block**. Decisions 1 to 24: [docs/DECISIONS.md](docs/DECISIONS.md);
architecture, assumptions and the production plan: [docs/design.md](docs/design.md).

## Honest limits

- **Live is not perfectly repeatable** (1001 and 1014 differ between live runs). The decision cache reproduced
  all 20 recorded sample decisions on a repeat run; cached reasoning uses earlier context, so use `--no-cache` after
  data changes.
- **The critic objected live only with proposals injected at the critic stage.** In that component eval (6 cases,
  $0.1113) Grok objected to 3 of 4 flawed VP proposals and 0 of 2 sound ones, and the VP revised 3 times. In full
  live runs it has never objected: on 2005 to 2009 the Grok VP held first ([docs/evals.md](docs/evals.md)).
- **The extraction retry** is proven only with a scripted model; Grok's first answer has always passed live.
- **The live rejection review escalated once** (3014); otherwise it agreed with every rejection.
- **Newer than the full live runs:** the review 3 fixes and decisions 22 to 24 had live spot checks only; the later
  payment and parser hardening (including the wider Grok and parser comparison) is tested offline only.
- **Overfitting.** Parsers, vendor master, watch list and patterns were written while looking at these files. The
  adversarial and unseen sets test generalization, and they are small.
- **Extraction has limits.** PDFs need a text layer (no OCR of scans); repair grounding checks that each number is
  printed in the file, not that it sits in the right field.
- **Known, not fixed:** stock is not decremented across a batch; `vendor_history` shows earlier rejections without the
  reason; the review UI shows the original text only for unreadable or Grok-rebuilt files.
- **Cut:** a real inbox, ERP and vendor master, live FX, a production review UI with auth, and any real bank call.

## License

Code is MIT licensed (see [LICENSE](LICENSE)). The sample invoices in `data/invoices/` and `data/generate_pdfs.py`
(and their copies in `web/invoices/`) come from https://github.com/galatiq-ai/galatiq-case-invoices and are not
covered by that license.
