# Eval summary

Offline: generated 2026-10-22 13:39 CDT, base commit 8dfb426. Live (grok-4.7): run 2026-10-22 13:38 CDT, base commit 8dfb426.

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
| (b) Decision agreement, eval live run, adversarial (7) | - | 6/7 (85.7%) |
| (b) Decision agreement, eval live run, extra (3) | - | 1/3 (33.3%) |
| (c) Adversarial catch rate | 6/7 (85.7%) | 7/7 (100.0%) |
| (d) 20 samples: LLM calls, tokens | 0 | 31 calls; prompt 61,611 (cached 49,536), completion 3,955, reasoning 31,589 |
| (d) 20 samples: billed cost | $0 | $0.2622 total, $0.0131 per invoice |
| (d) 20 samples: latency | 4.1 ms mean per invoice, 0.18s batch | 20.95s mean per invoice, 419.11s batch |

Details: `offline.md` and `live.md` next to this file.
