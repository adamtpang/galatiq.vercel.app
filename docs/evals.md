# Results and evals in detail

The README has the short version. Every number here comes from a committed file: `evals/results/summary.md`,
`offline.md`, `live.md`, `separate_run_live.md`, `cache_repeatability.md` and `docs/run_log.md`.

**Which code produced which result.** The offline results were made at commit 4d539d3 (demo runs) and 05a4ef5
(evals). All live results were made on Oct 22, 2026 between 7:46 PM and 9:16 PM CT at commit 05a4ef5, which only
added data and docs on top of 4d539d3. One later code change is not in the live numbers: after the live eval showed
that Grok's repair could rebuild adversarial 3014 and drop its wrong-type errors, a file with wrong value types is no
longer sent to Grok repair (`tests/test_review_fixes.py::test_wrong_types_are_never_repaired_by_grok_live`). Live
spot check at commit 7d320a2 (Oct 22, 9:19 PM CT, `python main.py --invoice_path=data/invoices_adversarial/invoice_3014_wrong_types.json --mode live`
on a fresh database): no repair call, REJECTED by hard rules with INVALID_FIELD_TYPE, Grok's rejection review agreed,
not paid; 2 Grok calls, $0.0204 billed.

**Review 3 fixes (commit 76881f7) and the live numbers.** The offline results below were regenerated at 76881f7. The
live numbers were not re-run in full and predate these fixes. Among the 20 samples the fixes change only 1014 (EUR),
which is now held for a person instead of paid at the mock rate; the new payment-instruction hold matches only 1003
("Wire transfer preferred."), which hard rules reject anyway. Live spot checks at 76881f7 on Oct 22, 2026 between
9:50 and 9:52 PM CT, each `python main.py --invoice_path=<file> --mode live` on a fresh database (traces in
`evals/results/spot_review3/`): `invoice_1014.xml` held (CURRENCY_CONVERTED), not paid; the reviewer's `t17.txt`
("payments should now go to our Chase account ending 7781") and `t19.txt` ("use the new remit-to on our portal") both
held (BANK_DETAILS_CHANGED), not paid, and on both Grok's risk review set `payment_details_changed` to true and quoted
the sentence (on 1014 it set it to false). 15 Grok calls, $0.1025 billed in total.

Earlier live results (before review 2) came from local checkpoint commits 4719dbe, 982b14f and 849b0af that were
never pushed to main. They are now on the branch
[`live-eval-checkpoints`](https://github.com/adamtpang/galatiq.vercel.app/tree/live-eval-checkpoints). Every live
result now committed on main was re-run at 05a4ef5 and replaces them.

## Results on the 20 samples

| Run | Paid | Rejected | Held for a person |
|---|---|---|---|
| Offline rules stand-ins (`runs/demo/offline`, 76881f7) | 6 invoices, $30,375.00 | 12 | 2 |
| Live demo run, grok-4.7 (`runs/demo/live`, 8:29 PM CT) | 4 invoices, $16,705.00 | 12 | 4 |
| Live eval run, grok-4.7 (`evals/results/runs/live/main`, 7:46 PM CT) | 4 invoices, $17,250.00 | 12 | 4 |

The same 12 are rejected in every run: hard rules run first and any blocking flag rejects. Live, Grok's rejection
review read all 12 in each run and agreed with all 12; it can only escalate a rejection to a person, never pay it.
1012.pdf is held in every run by the vendor-rename hard hold. Offline, 1014 is also held (non-USD, decision 22). The
other invoices are the ones the VP decides:

| File | Offline | Live demo run | Live eval run |
|---|---|---|---|
| 1001 | Paid | Held (confirm Net 15 against the due date) | Paid |
| 1004_revised | Paid $5,940.00 | Held (earlier INV-1004 rejected, PO amendment) | Held (same) |
| 1006 | Paid | Paid | Paid |
| 1010 | Paid | Held (rush price 20% over catalog) | Held (same) |
| 1011.pdf, 1015 | Paid | Paid | Paid |
| 1014 (EUR) | Held (non-USD, decision 22) | Paid (before decision 22) | Held (first payment, EUR prices off the USD catalog) |

Every other live and offline difference is an invoice the rules stand-ins would pay and the Grok VP held, never the
reverse. 1014 is the exception: the live demo run predates decision 22 and paid it. The full side by side with live reasons is in `docs/run_log.md`.

**How 1004 and its revision end up.** INV-1004 (Precision Parts, $1,890.00) passes every inventory check, but `invoice_1004_revised.json` is revision R1 of the same invoice ($5,940.00), so the batch prescan rejects the original as superseded (`SUPERSEDED_BY_REVISION`) and R1 carries on (`REVISION_SUPERSEDES`). Before decision 13 the address watch list listed 742 Evergreen Terrace, which is also the address the mock vendor master has on file for Precision Parts, so R1 was always held and the 1004 family was never paid: the mock data contradicted itself. Now a watch-list entry does not fire on the vendor's own address on file (an `ADDRESS_ON_FILE` info flag records the match), so offline R1 is paid $5,940.00 and the original is never paid. Another vendor at that address still fires the watch list (adversarial 3007, held).

**Live decisions are not perfectly repeatable.** Grok runs at `temperature=0` and the same invoice can still get a
different decision in a fresh run (1001 and 1014 above). The design limits what that can do: hard rules and hard
holds run before any model opinion, Grok's risk review can only raise the score, the rejection review can only
escalate, the memo is written after the decision and never read back, and the fail-closed guard and the payment step
refuse anything with an error or a blocking flag. So a run-to-run difference moves an invoice between paid and held,
never pays what the rules block.

**Decision cache.** Every Grok answer for an invoice is stored in SQLite under a hash of the file content, the policy,
the model id and the prompt code, and reused when the same invoice runs again. Measured at 05a4ef5
(`evals/results/cache_repeatability.md`): the 20 samples run twice on one database gave identical decisions, reasons,
risk scores and flags for 20 of 20; the first run made 83 API calls ($0.6346, 844.6 s), the second made 0 (0.2 s).
A new invoice, policy, model id or prompt is a new key. `--no-cache` turns it off. The model id the API returns is
recorded on every call; a different id is a MODEL_MISMATCH hold. On Oct 22 the API returned `grok-4.7` on every call.

## Evals

`python -m evals` runs five evals offline in about a second; `--live` adds the live runs; `--write-snapshot` writes the
committed copy (`evals/results/`, `web/data/evals.json`). `tests/test_evals.py` pins the offline numbers in CI.

| Eval | Offline | Live (grok-4.7, 05a4ef5) |
|---|---|---|
| (a) Extraction, all fields, 26 files | 119/127 (93.7%) | 127/127 pipeline; 126/127 Grok-only |
| (b) Agreement with offline, 20 samples | - | 17/20 in the eval run (against the offline run at 05a4ef5); 16/20 in the committed demo runs (offline at 76881f7) |
| (c) Adversarial set caught (15) | 15/15; 15/15 as a separate later run | 15/15; 15/15 as a separate later run |
| (d) Cost, 20 samples | $0, 0 calls | $0.6575 billed, 85 calls |
| (d) Latency, 20 samples | 4.7 ms mean per invoice | 38.9 s mean per invoice, 778.9 s batch |
| (e) Unseen layouts (4) | 4 held, none rejected, none paid | 4/4 read correctly, 4/4 paid |

**(a) Extraction.** `evals/ground_truth.yaml` was written by reading each source file, not from pipeline output. It
scores vendor, invoice number, printed total, line items and due date for the 20 samples and 6 extras. Offline every
miss is one of the two extras the parsers cannot read (2001 email, 2003 truncated JSON). The parsers were written
against the samples, so their sample score is in-sample. Grok-only extraction missed one field: 1012.pdf's vendor
kept "(formerly FastShip Ltd.)".

**(b) Agreement.** See the tables above. On the 15 adversarial invoices the modes agree on 15. On the 6 extras they
agree on 5: 2006 is rejected offline after the critic objects, held live by the VP. On the 4 unseen layouts they agree
on 0: offline holds all 4 (unreadable layout), live pays all 4 after a grounded Grok reading.

**(c) Adversarial set.** 15 added invoices in `data/invoices_adversarial/`, with expected outcomes written in
`evals/adversarial_expected.yaml` before each run. "Caught" means not approved and not paid. 3009 to 3015 were added
after review 2: moved banks with acct and ABA numbers, a SYSTEM: pre-cleared note, an ASSISTANT: final-answer note, a
closing `</invoice_document>` tag, notes as a JSON list (the crash that paid INV-1005 before the fix), wrong types in
every field, and a wire-instruction change. Live, 15 of 15 were caught in the eval run and 15 of 15 in the separate
later run (`separate_run_live.md`, 154 Grok calls for both runs, $1.1465). In that separate run Grok's rejection
review escalated 3014 to a person: it pointed out that the "missing" items and total were present but had wrong
types. That is the only live escalation so far, and the invoice was still not paid. In the eval run 3014 was rejected
as a content duplicate of 3010 after Grok rebuilt it; that rebuild is the gap fixed after the run (see the top of
this file).

**(d) Cost and latency.** Billed cost is the API's own `cost_in_usd_ticks`; it matches the published grok-4.7 prices.

| Live batch | Invoices | Calls | Billed | Mean latency |
|---|---|---|---|---|
| 20 samples | 20 | 85 | $0.6575 | 38.9 s |
| Adversarial | 15 | 71 | $0.5360 | 80.4 s |
| Extra | 6 | 34 | $0.2564 | 54.8 s |
| Unseen | 4 | 24 | $0.1432 | 44.0 s |
| Grok-only extraction | 26 files | 26 | $0.2175 | 10.6 s |

The adversarial mean is pulled up by one slow call: Grok's repair of 3014 took 485 s.

**(e) Unseen layouts.** Four added invoices in layouts the parsers were never tuned on. Offline the parsers read none
and all 4 are held as unreadable layouts. Live, Grok read all 4 correctly, each reading was grounded in the file, and
all 4 were paid after the normal risk review and VP. That includes 4004, which an earlier checkpoint held because of a
bug in our CSV grounding check; this run confirms the fix live.

## The critic and the rejection review, live

The critic runs only when the VP approves an invoice over $10,000, near the limit or high risk. Live on Oct 22 at
05a4ef5 it ran once, on 2004 in the eval run, and signed off. In the committed live demo runs the Grok VP held 2004
(both alone and in the extras batch), so no critic call was made. 2005 and 2006, written to make the critic object,
were held by the Grok VP on its first pass both times. So a live critic objection followed by a VP revision has not
been observed; offline, 2005 (deadlock) and 2006 (objection, then revised to a rejection) show the loop with the rules
stand-ins.

The rejection review ran on every hard-rule rejection live: it agreed with all 12 sample rejections in the demo run
and with all 15 rejections in the eval run, and escalated one (3014) in the separate later run.
