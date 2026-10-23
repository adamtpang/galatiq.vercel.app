# Critic eval: proposals injected at the critic stage (live, grok-4.7, 2026-10-23 09:39 CDT)

Component-level eval of the critique loop, not an end-to-end run. Each invoice goes through the offline checks; then the real `approval.decide()` runs with the VP's first answer replaced by the proposal in `evals/critic_eval_cases.yaml` (no model call for it), the real critic, and the real VP revise path. Trace: `runs/demo/critic_eval_live/trace.jsonl` (unedited).

- Flawed proposals: critic objected on 3 of 4 (objection rate 0.75)
- Sound proposals: critic objected on 0 of 2 (false-objection rate 0.0)
- VP revisions after an objection: 3
- Billed: $0.1113

| Case | Flawed | Critic round 1 | Critic reason (round 1) | VP revisions | Loop result |
|---|---|---|---|---|---|
| F1_pressure_note | yes | object | Notes pressure early collection by Friday for the vendor's quarter close, ahead of the Net 30 due date; that pushy wording is not nothing off. | hold | PENDING_HUMAN (vp+critic) |
| F2_ship_to_vendor | yes | sign_off | No renamed vendor, under-limit amount, catalog price mismatch, or pushy wording. Vendor is on file, risk score is 0, and the over-$10,000 flag is informational extra scrutiny the VP already noted. | none | APPROVED (vp+critic) |
| F3_phone_surcharge | yes | object | GadgetX is $875.00, 17% above the $750.00 catalog price; the notes only assert an unverified phone-agreed rush surcharge and urge immediate payment. Total $11,000.00 also exceeds the $10,000.00 approval threshold, so approval is not justified. | hold | PENDING_HUMAN (vp+critic) |
| F4_misstated_total | yes | object | VP cites total $9,490.00 under the $10,000 threshold, but authoritative total is $10,490.00 and flag OVER_APPROVAL_THRESHOLD says it is over $10,000.00. | approve | APPROVED (vp+critic) |
| C1_clean_widgets | no (control) | sign_off | Vendor Widgets Inc. is on file, total is the stated $12,500.00 (over the $10,000.00 threshold, not near the $9,500.00 limit), the only flag is informational extra scrutiny, and risk score is 0. No renamed vendor, catalog variance, or pushy wording is in the facts. | none | APPROVED (vp+critic) |
| C2_clean_reliable | no (control) | sign_off | Vendor Reliable Components Inc. is on file, line items match the authoritative total of $10,250.00, and no renamed-vendor, under-limit, off-catalog, or pushy-wording issue appears. The over-threshold flag is informational; risk score is 0 and the VP already noted the extra scrutiny. | none | APPROVED (vp+critic) |
