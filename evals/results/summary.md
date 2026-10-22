# Eval summary

Offline: generated 2026-10-22 13:00 CDT, base commit c71dfbe. Live (grok-4.7): run 2026-10-22 12:57 CDT, base commit c71dfbe.

| Eval | Offline | Live |
|---|---|---|
| (a) Extraction: vendor | 21/23 (91.3%) | 23/23 (100.0%) pipeline; 23/23 (100.0%) Grok-only |
| (a) Extraction: invoice_number | 21/22 (95.5%) | 22/22 (100.0%) pipeline; 22/22 (100.0%) Grok-only |
| (a) Extraction: total | 21/23 (91.3%) | 23/23 (100.0%) pipeline; 23/23 (100.0%) Grok-only |
| (a) Extraction: line_items | 21/23 (91.3%) | 23/23 (100.0%) pipeline; 23/23 (100.0%) Grok-only |
| (a) Extraction: due_date | 20/21 (95.2%) | 21/21 (100.0%) pipeline; 21/21 (100.0%) Grok-only |
| (a) Extraction: all fields | 104/112 (92.9%) | 112/112 (100.0%) pipeline; 112/112 (100.0%) Grok-only |
| (b) Decision agreement, committed demo runs (runs/demo/offline vs runs/demo/live), 20 samples | - | 17/20 (85.0%) |
| (b) Decision agreement, this eval run, samples (20) | - | 18/20 (90.0%) |
| (b) Decision agreement, this eval run, adversarial (7) | - | 4/7 (57.1%) |
| (b) Decision agreement, this eval run, extra (3) | - | 0/3 (0.0%) |
| (c) Adversarial catch rate | 3/7 (42.9%) | 6/7 (85.7%) |
| (d) 20 samples: LLM calls, tokens | 0 | 32 calls; prompt 64,039 (cached 41,344), completion 4,268, reasoning 33,095 |
| (d) 20 samples: billed cost | $0 | $0.2902 total, $0.0145 per invoice |
| (d) 20 samples: latency | 3.3 ms mean per invoice, 0.19s batch | 22.22s mean per invoice, 444.6s batch |

Details: `evals/results/offline.md` and `evals/results/live.md`.
