# Eval summary

Offline: generated 2026-10-22 14:27 CDT, base commit 8636c0e. Live (grok-4.7): run 2026-10-22 14:22 CDT, base commit 8636c0e.

| Eval | Offline | Live |
|---|---|---|
| (a) Extraction: vendor | 21/23 (91.3%) | 23/23 (100.0%) pipeline; 23/23 (100.0%) Grok-only |
| (a) Extraction: invoice_number | 21/22 (95.5%) | 22/22 (100.0%) pipeline; 22/22 (100.0%) Grok-only |
| (a) Extraction: total | 21/23 (91.3%) | 23/23 (100.0%) pipeline; 23/23 (100.0%) Grok-only |
| (a) Extraction: line_items | 21/23 (91.3%) | 23/23 (100.0%) pipeline; 23/23 (100.0%) Grok-only |
| (a) Extraction: due_date | 20/21 (95.2%) | 21/21 (100.0%) pipeline; 21/21 (100.0%) Grok-only |
| (a) Extraction: all fields | 104/112 (92.9%) | 112/112 (100.0%) pipeline; 112/112 (100.0%) Grok-only |
| (b) Decision agreement, committed demo runs (runs/demo/offline vs runs/demo/live), 20 samples | - | 17/20 (85.0%) |
| (b) Decision agreement, eval live run, samples (20) | - | 18/20 (90.0%) |
| (b) Decision agreement, eval live run, adversarial (7) | - | 7/7 (100.0%) |
| (b) Decision agreement, eval live run, extra (3) | - | 1/3 (33.3%) |
| (c) Adversarial catch rate | 7/7 (100.0%) | 7/7 (100.0%) |
| (d) 20 samples: LLM calls, tokens | 0 | 31 calls; prompt 63,463 (cached 52,736), completion 4,513, reasoning 26,628 |
| (d) 20 samples: billed cost | $0 | $0.2347 total, $0.0117 per invoice |
| (d) 20 samples: latency | 4.9 ms mean per invoice, 0.23s batch | 16.57s mean per invoice, 331.6s batch |

Details: `offline.md` and `live.md` next to this file.
