# Read this first

**What it does.** Reads Acme's invoices (txt, json, csv, xml, pdf), checks them against inventory and policy, decides
approve, reject or hold for a person, and pays approved ones through `mock_payment`. Code does all the math and the
hard rules. Live, Grok agents cross-read every invoice, review risk with read-only tools, argue the approval as VP and
critic, review each rejection (they can only escalate it) and write a memo. Offline, rules stand-ins take their place
and no model is called. Every decision has reasons and a trace in `runs/`.

**Run it** (Python 3.11+, no API key, after `python -m pip install -r requirements.txt`):

```bash
python main.py --batch data/invoices --offline  # the 20 case invoices: table, reasons, trace path
pytest                                          # the offline suite, including ruff and mypy
```

The brief's own command also works: `python main.py --invoice_path=data/invoices/invoice1.txt`.
`--offline` prevents model calls even if an API key is set. Windows setup is in the [README](README.md).

**Results on the 20 case invoices** (details: [README](README.md), [docs/evals.md](docs/evals.md)):

| Run | Paid | Rejected | Held |
|---|---|---|---|
| Offline, commit 2a07cb7 | 5, $23,190.00 | 12 | 3 (1010 price 20% over catalog, 1012.pdf renamed vendor, 1014 EUR) |
| Live demo run, grok-4.7, commit 05a4ef5 | 4, $16,705.00 | 12 | 4 |

1004 is rejected as superseded by its revision R1 (reason SUPERSEDED_BY_REVISION, decision 24); R1 is paid.

Adversarial set: 15 of 15 caught offline and live. The third reviewer's 9 bank-change sentences and 10 invented
injections are all held offline.

**Honest limits**

- The full live runs predate the review 3 fixes and decisions 22 to 24 (live spot checks only) and the later
  payment and parser hardening (tested offline only).
- Offline injection and bank-change detection is pattern-based; live, Grok is the real reader.
- The critic objected live only with proposals injected at the critic stage (3 of 4 flawed, 0 of 2 sound, $0.1113).
  In full live runs the Grok VP held 2005 to 2009 first, so the critic never objected there.
- The extraction self-correction retry is tested only with a scripted model.
- Live decisions vary run to run on a few invoices. The decision cache reproduced all 20 recorded sample decisions
  on a repeat run; cached reasoning uses earlier context, so use `--no-cache` after data changes.
- In-sample: parsers, vendor master, watch list and patterns were written while looking at these files.
- PDF parsing needs a text layer. Numeric repair grounding checks occurrence, not exact field association.
- Known and not fixed: no tolerance for a 1 to 3 day terms mismatch in the live VP prompt; `vendor_history` omits
  rejection reasons; stock is not decremented across a batch; the review UI shows the original text only for
  unreadable or Grok-rebuilt files.
- Cut: a real inbox, ERP, vendor master, FX, bank, and a production review UI with auth.
