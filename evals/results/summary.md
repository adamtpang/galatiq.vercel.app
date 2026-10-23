# Eval summary

Offline: generated 2026-10-23 14:40 CDT, base commit 2a07cb7. Live (grok-4.7): run 2026-10-22 20:28 CDT, base commit 05a4ef5.

| Eval | Offline | Live |
|---|---|---|
| (a) Extraction: vendor | 24/26 (92.3%) | 26/26 (100.0%) pipeline; 25/26 (96.2%) Grok-only |
| (a) Extraction: invoice_number | 24/25 (96.0%) | 25/25 (100.0%) pipeline; 25/25 (100.0%) Grok-only |
| (a) Extraction: total | 24/26 (92.3%) | 26/26 (100.0%) pipeline; 26/26 (100.0%) Grok-only |
| (a) Extraction: line_items | 24/26 (92.3%) | 26/26 (100.0%) pipeline; 26/26 (100.0%) Grok-only |
| (a) Extraction: due_date | 23/24 (95.8%) | 24/24 (100.0%) pipeline; 24/24 (100.0%) Grok-only |
| (a) Extraction: all fields | 119/127 (93.7%) | 127/127 (100.0%) pipeline; 126/127 (99.2%) Grok-only |
| (b) Decision agreement, committed demo runs (runs/demo/offline vs runs/demo/live), 20 samples | - | 17/20 (85.0%) |
| (b) Decision agreement, eval live run, samples (20) | - | 17/20 (85.0%) |
| (b) Decision agreement, eval live run, adversarial (15) | - | 15/15 (100.0%) |
| (b) Decision agreement, eval live run, extra (6) | - | 5/6 (83.3%) |
| (b) Decision agreement, eval live run, unseen (4) | - | 0/4 (0.0%) |
| (c) Adversarial catch rate | 15/15 (100.0%) | 15/15 (100.0%) |
| (c) Adversarial set as a separate later run (after the samples) | 15/15 (100.0%); 3006 REJECTED | - (rules only; the duplicate checks run before any Grok call) |
| (e) Unseen layouts (4, never tuned for): not rejected; read correctly and paid | 4/4 not rejected (4 held, 0 paid) | 4/4 read correctly, 4/4 paid, 0 held, 0 rejected |
| (b) Disagreement routing (a metric; sending disagreements to a person is a plan, not policy), committed demo runs (runs/demo/offline vs runs/demo/live) | - | 3 of 20 would go to a person; without that check one side paid 3 of them ($15,395.00) |
| (b) Disagreement routing (a metric; sending disagreements to a person is a plan, not policy), eval live run | - | 3 of 20 would go to a person; without that check one side paid 3 of them ($17,580.00) |
| (d) 20 samples: LLM calls, tokens | 0 | 85 calls; prompt 175,886 (cached 104,704), completion 11,803, reasoning 65,325 |
| (d) 20 samples: billed cost | $0 | $0.6575 total, $0.0329 per invoice |
| (d) 20 samples: latency | 7.2 ms mean per invoice, 0.3s batch | 38.93s mean per invoice, 778.87s batch |

Details: `offline.md` and `live.md` next to this file.
