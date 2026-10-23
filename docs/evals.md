# Results, evals and demo

Every number comes from a committed file in `evals/results/` (`summary.md`, `offline.md` with every demo-run disagreement and its live reasons, `live.md`, `separate_run_live.md`, `cache_repeatability.md`) or in `runs/demo/*/summary.json`.

**Which code produced which result.** Saved offline results identify their producing commit in each `summary.json`; current golden tests verify the sample outcomes. Later changes do not retroactively update a saved run. All full live runs were made on Oct 22, 2026, 7:46 PM to 9:16 PM CT, at commit 05a4ef5. Later changes were not re-run live in full: the review 3 fixes, decisions 22 to 24 and the later payment and parser hardening. Live spot checks after them: 3014 at 7d320a2 (rejected, no repair call, $0.0204); 1014 and two reviewer bank sentences at 76881f7 (all held, $0.1025, traces in `evals/results/spot_review3/`).

## Results on the 20 samples

| Run | Paid | Rejected | Held |
|---|---|---|---|
| Offline rules stand-ins (`runs/demo/offline`) | 5, $23,190.00 | 12 | 3 |
| Live demo run, grok-4.7 (`runs/demo/live`) | 4, $16,705.00 | 12 | 4 |
| Live eval run, grok-4.7 (`evals/results/runs/live/main`) | 4, $17,250.00 | 12 | 4 |

The 12 rejections are the same in every run, including 1004 (superseded by R1, decision 24), and live Grok's rejection review agreed with all of them. 1012.pdf is held everywhere (renamed vendor). Where the VP decides:

| File | Offline | Live demo | Live eval |
|---|---|---|---|
| 1001 | Paid | Held (Net 15 vs due date) | Paid |
| 1004_revised | Paid $5,940.00 | Held (earlier 1004 rejected) | Held |
| 1006, 1011.pdf, 1015 | Paid | Paid | Paid |
| 1010 | Held (20% over catalog, decision 23) | Held | Held |
| 1014 (EUR) | Held (decision 22) | Paid (before decision 22) | Held |

**Live is not perfectly repeatable** (1001 and 1014 above): model differences changed which valid invoices were paid or held. Hard rules and holds still stop payment of blocked invoices.

**The decision cache** reproduced all 20 recorded decisions (83 calls, then 0 on the repeat). It reuses earlier model answers and tool results while deterministic checks run again; use `--no-cache` after data changes.

## Evals

`python -m evals` runs five evals offline in about a second; `tests/test_evals.py` pins them.

| Eval | Offline | Live (grok-4.7, 05a4ef5) |
|---|---|---|
| (a) Extraction, 26 files | 119/127 fields | 127/127 pipeline; 126/127 Grok-only |
| (b) Agreement, 20 samples | - | 17/20 eval run; 17/20 committed demo runs |
| (c) Adversarial caught (15) | 15/15, also as a separate later run | 15/15, also as a separate later run |
| (d) Cost and latency, 20 samples | $0; under 10 ms per invoice | $0.6575, 85 calls; 38.9 s per invoice |
| (e) Unseen layouts (4) | 4 held | 4/4 read correctly and paid |

- (a) Ground truth was written by reading each file. Offline misses are the two extras the parser cannot read (2001, 2003).
- (b) Demo-run disagreements: 1001, 1004_revised and 1014 (above). Extras agree on 5 of 6 (2006: rejected offline after the critic objects, held live). Unseen: 0 of 4 (offline holds, live pays).
- (c) Traps: injections, lookalike and renamed vendors, bank changes, duplicates, wrong types, a closing fence tag. Live, the rejection review escalated one (3014) to a person, its only escalation.
- (d) Billed cost is the API's own `cost_in_usd_ticks`. All committed live runs cost $3.87, plus $0.10 for the review 3 spot checks and $0.14 for the critic attempts below.

## The critic, live

The critic runs when the VP approves over $10,000, near the limit or high risk. Live it ran once (2004, eval run) and signed off. In full live runs it has never objected. 2005 and 2006 were written to make it object; the Grok VP held both first. On Oct 23 three more tries, each a hard-rule-clean invoice from Reliable Components (paid history from the 20 samples, run first on the same database), each run once with `--mode live --no-cache`:

| Invoice | Subtle problem | Grok VP | Cost |
|---|---|---|---|
| 2007 ($11,000) | "Kindly settle by Friday" against Net 30 | held | $0.0505 |
| 2008 ($10,250) | ships to the vendor itself | held | $0.0492 |
| 2009 ($10,490) | GadgetX 8% over catalog, under the 10% flag | held | $0.0402 |

Grok's risk review spotted each problem, so the VP held before any critic call. Traces: `runs/demo/critic_live_2007` to `_2009`; invoices in `data/invoices_critic/`. Offline, 2005 (deadlock) and 2006 (objection, then a rejection) show the loop with rules stand-ins.

**Critic eval: proposals injected at the critic stage** (`evals/critic_eval.py`, cases in `evals/critic_eval_cases.yaml`, written before the run). A component eval, not an end-to-end run: after the offline checks, the real `approval.decide()` runs with a fixed VP proposal as the VP's first answer, then the real Grok critic and Grok VP revise. Live on Oct 23 at 9:39 AM CT (before the later payment and parser hardening, which left the critic and VP prompts unchanged and only reworded the VP's `conditions` field description), for $0.1113: the critic objected to 3 of 4 flawed proposals and 0 of 2 sound ones, and the VP revised 3 times (2 holds; on the misstated total it kept approving). It missed the ship-to-vendor case. Results: `evals/results/critic_eval_live.md`; unedited trace: `runs/demo/critic_eval_live/`. Offline, the rules critic catches 1 of 4.

## Demo: what to run and what to point at

1. `python main.py --invoice_path=data/invoices/invoice1.txt --offline`: runs `invoice_1001.txt` (the case files start at 1001) with one JSON line per step, the `mock_payment` output and the trace path. The brief's command without `--offline` also works; it uses Grok if an API key is configured.
2. `python main.py --batch data/invoices --offline`: 5 paid ($23,190.00), 12 rejected, 3 held (1010, 1012.pdf, 1014).
3. Edge cases: 1003 (fraud, rejected, risk 60); 1004 (`SUPERSEDED_BY_REVISION` info flag, rejected by supersession, R1 paid, decision 13 address on file); 1010 (lines aggregated, 20% over catalog, held); 1011 to 1013 (duplicates across formats); 1012.pdf (OCR fixes, renamed vendor, hard hold); 1013 (over stock only after summing lines); 1014 (EUR, held); 2005 and 3005 (offline critic deadlock); 3008 (new IBAN, held).
4. `--offline --chaos 0.3 --seed 7`, then the same batch again: retries with backoff, then `idempotency_skip`.
5. `python main.py review INV-1012` and `python main.py ui`: the queue; approve pays through the same idempotent step.
6. `--mode live` (needs `XAI_API_KEY`): `grok_cross_check`, `tool_call`, `memo`, `llm_repair` on 2001 and 2003.
7. https://galatiq.vercel.app replays the committed runs.
