# Read this first

**What it does.** Reads Acme's invoices (txt, json, csv, xml, pdf), checks them against inventory and policy, decides
approve, reject or hold for a person, and pays approved ones through `mock_payment`. Code does all the math and the
hard rules. Live, Grok agents cross-read every invoice, review risk with read-only tools, argue the approval as VP and
critic, review each rejection (they can only escalate it) and write a memo. Offline, with no API key, fixed rules
stand-ins take their place and no model is called. Every decision has reasons and a trace in `runs/`.

**Run it** (Python 3.11+, no API key, after `pip install -r requirements.txt`):

```bash
python main.py --batch data/invoices     # the 20 case invoices: table, reasons, trace path
pytest                                   # 427 offline tests, about 20 seconds
```

The brief's own command also works: `python main.py --invoice_path=data/invoices/invoice1.txt`.

**Results on the 20 case invoices** (details: [README](README.md), [docs/evals.md](docs/evals.md)):

| Run | Paid | Rejected | Held |
|---|---|---|---|
| Offline, commit 76881f7 | 6, $30,375.00 | 12 | 2 (1012.pdf renamed vendor, 1014 EUR) |
| Live demo run, grok-4.7, commit 05a4ef5 | 4, $16,705.00 | 12 | 4 |

The same 12 are rejected in every run. Adversarial set: 15 of 15 caught offline and live. The third reviewer's 9
bank-change sentences and 10 invented injections are all held offline (tests in `tests/test_review3.py`).

**Honest limits**

- The full live runs predate the review 3 fixes (76881f7). Only three live spot checks were run after them (1014 and
  two bank sentences, all held, $0.10). The live demo run paid 1014 at the mock rate; it is now held.
- Offline injection and bank-change detection is pattern-based. It catches the wordings it was written for, not every
  wording. Live, Grok is the real reader (its `prompt_injection` and `payment_details_changed` fields hold).
- The critic has never been seen to object live. It ran once live (2004) and signed off. The objection and revise loop
  is shown only offline with rules stand-ins (2005, 2006).
- The extraction self-correction retry (Pydantic errors sent back to Grok) is tested only with a scripted model, not
  seen live.
- Live decisions vary run to run on a few invoices (1001, 1014). The decision cache makes a re-run identical.
- In-sample: parsers, vendor master, watch list and patterns were written while looking at these files.
- Known and not fixed (left on purpose for this submission):
  - A superseded original (1004) is REJECTED with a blocking flag, not given its own SUPERSEDED status.
  - No tolerance for a 1 to 3 day TERMS_MISMATCH in the live VP prompt (it is info only, but the VP may still hold).
  - The `vendor_history` tool shows earlier REJECTED invoices without the reason.
  - Stock is never decremented after a payment, so one batch can pay more units than are in stock across invoices.
  - The review UI shows the original file text only for Grok-rebuilt or unreadable invoices, not parser-read ones.
  - The docs are long (`docs/design.md`, `docs/DECISIONS.md`); this page is the short version.
- Cut: a real inbox, ERP, vendor master, FX, bank, and a production review UI with auth.
