# Eval summary

Offline: generated 2026-10-22 15:14 CDT, base commit 47ba5b7. Live (grok-4.7): run 2026-10-22 15:13 CDT, base commit 47ba5b7.

| Eval | Offline | Live |
|---|---|---|
| (a) Extraction: vendor | 21/23 (91.3%) | 23/23 (100.0%) pipeline; 23/23 (100.0%) Grok-only |
| (a) Extraction: invoice_number | 21/22 (95.5%) | 22/22 (100.0%) pipeline; 22/22 (100.0%) Grok-only |
| (a) Extraction: total | 21/23 (91.3%) | 23/23 (100.0%) pipeline; 23/23 (100.0%) Grok-only |
| (a) Extraction: line_items | 21/23 (91.3%) | 23/23 (100.0%) pipeline; 23/23 (100.0%) Grok-only |
| (a) Extraction: due_date | 20/21 (95.2%) | 21/21 (100.0%) pipeline; 21/21 (100.0%) Grok-only |
| (a) Extraction: all fields | 104/112 (92.9%) | 112/112 (100.0%) pipeline; 112/112 (100.0%) Grok-only |
| (b) Decision agreement, committed demo runs (runs/demo/offline vs runs/demo/live), 20 samples | - | 17/20 (85.0%) |
| (b) Decision agreement, eval live run, samples (20) | - | 19/20 (95.0%) |
| (b) Decision agreement, eval live run, adversarial (7) | - | 7/7 (100.0%) |
| (b) Decision agreement, eval live run, extra (3) | - | 1/3 (33.3%) |
| (c) Adversarial catch rate | 7/7 (100.0%) | 7/7 (100.0%) |
| (c) Adversarial set as a separate later run (after the samples) | 7/7 (100.0%); 3006 REJECTED | - (rules only; the duplicate checks run before any Grok call) |
| (b) Disagreement routing (a metric; sending disagreements to a person is a plan, not policy), committed demo runs (runs/demo/offline vs runs/demo/live) | - | 3 of 20 would go to a person; without that check one side paid 3 of them ($16,640.00) |
| (b) Disagreement routing (a metric; sending disagreements to a person is a plan, not policy), eval live run | - | 1 of 20 would go to a person; without that check one side paid 1 of them ($7,185.00) |
| (d) 20 samples: LLM calls, tokens | 0 | 31 calls; prompt 63,587 (cached 52,352), completion 4,473, reasoning 29,816 |
| (d) 20 samples: billed cost | $0 | $0.2544 total, $0.0127 per invoice |
| (d) 20 samples: latency | 5.4 ms mean per invoice, 0.23s batch | 27.53s mean per invoice, 550.74s batch |

Details: `offline.md` and `live.md` next to this file.
