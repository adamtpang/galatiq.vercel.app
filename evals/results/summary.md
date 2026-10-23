# Eval summary

Offline: generated 2026-10-22 19:42 CDT, base commit 4d539d3. Live (grok-4.7): run 2026-10-22 18:34 CDT, base commit 982b14f.

| Eval | Offline | Live |
|---|---|---|
| (a) Extraction: vendor | 24/26 (92.3%) | 25/25 (100.0%) pipeline; 24/25 (96.0%) Grok-only |
| (a) Extraction: invoice_number | 24/25 (96.0%) | 24/24 (100.0%) pipeline; 24/24 (100.0%) Grok-only |
| (a) Extraction: total | 24/26 (92.3%) | 25/25 (100.0%) pipeline; 25/25 (100.0%) Grok-only |
| (a) Extraction: line_items | 24/26 (92.3%) | 25/25 (100.0%) pipeline; 25/25 (100.0%) Grok-only |
| (a) Extraction: due_date | 23/24 (95.8%) | 23/23 (100.0%) pipeline; 23/23 (100.0%) Grok-only |
| (a) Extraction: all fields | 119/127 (93.7%) | 122/122 (100.0%) pipeline; 121/122 (99.2%) Grok-only |
| (b) Decision agreement, committed demo runs (runs/demo/offline vs runs/demo/live), 20 samples | - | 16/20 (80.0%) |
| (b) Decision agreement, eval live run, samples (20) | - | 17/20 (85.0%) |
| (b) Decision agreement, eval live run, adversarial (8) | - | 8/8 (100.0%) |
| (b) Decision agreement, eval live run, extra (5) | - | 5/5 (100.0%) |
| (b) Decision agreement, eval live run, unseen (4) | - | 1/4 (25.0%) |
| (c) Adversarial catch rate | 15/15 (100.0%) | 8/8 (100.0%) |
| (c) Adversarial set as a separate later run (after the samples) | 15/15 (100.0%); 3006 REJECTED | - (rules only; the duplicate checks run before any Grok call) |
| (e) Unseen layouts (4, never tuned for): not rejected; read correctly and paid | 4/4 not rejected (4 held, 0 paid) | 4/4 read correctly, 3/4 paid, 1 held, 0 rejected |
| (b) Disagreement routing (a metric; sending disagreements to a person is a plan, not policy), committed demo runs (runs/demo/offline vs runs/demo/live) | - | 4 of 20 would go to a person; without that check one side paid 4 of them ($20,330.00) |
| (b) Disagreement routing (a metric; sending disagreements to a person is a plan, not policy), eval live run | - | 3 of 20 would go to a person; without that check one side paid 3 of them ($17,580.00) |
| (d) 20 samples: LLM calls, tokens | 0 | 71 calls; prompt 144,140 (cached 115,584), completion 11,110, reasoning 51,091 |
| (d) 20 samples: billed cost | $0 | $0.4881 total, $0.0244 per invoice |
| (d) 20 samples: latency | 4.9 ms mean per invoice, 0.24s batch | 32.08s mean per invoice, 641.81s batch |

Details: `offline.md` and `live.md` next to this file.
