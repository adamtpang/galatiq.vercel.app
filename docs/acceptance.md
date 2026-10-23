# Submission acceptance checklist

This is an implementation checklist against the [official assessment](https://github.com/galatiq-ai/galatiq-case-invoices/blob/main/README.md), reviewed October 23, 2026 (README blob `cf307998db23060b9abaf5396cf40a25cde9a0a4`). It is not Galatiq's grading rubric or a claim of defect-free software. Its qualitative criteria still require a reviewer's judgment.

A check passes only when its stated evidence exists and its limitations are disclosed. These checks are not a numerical employer score. Passing the implementation checks does not imply that a fresh live run has passed.

| ID | Acceptance condition | Evidence |
|---|---|---|
| 01 | The complete workflow processes all 20 supplied invoices and reaches a reasoned outcome. | `tests/test_golden.py`; `runs/demo/offline/summary.json` |
| 02 | PDF and text inputs work, with CSV, JSON and XML support for the supplied formats. | `tests/test_parsers.py`; `invoice_agents/parsers/` |
| 03 | Extracted records include vendor, amount, items with quantities, and due date, preserving missing or ambiguous fields. | `evals/ground_truth.yaml`; `tests/test_evals.py::test_offline_extraction_numbers` |
| 04 | Typos and malformed or unreadable inputs produce corrections, flags or a human hold instead of silent payment. | `tests/test_review2.py`; `tests/test_review3.py`; `tests/test_agentic.py` |
| 05 | A persistent local SQLite inventory is created with WidgetA 15, WidgetB 10, GadgetX 5 and FakeItem 0. | `config/seed.sql`; `invoice_agents/db.py`; `tests/test_validation.py::test_init_db_is_idempotent` |
| 06 | INV-1001, INV-1004 and INV-1006 pass the applicable stock checks. A replaced original is not paid twice. | `tests/test_validation.py`; `tests/test_review3.py::test_superseded_original_passes_validation_and_is_not_paid` |
| 07 | Excess quantities and zero-stock items are flagged, including INV-1002 and INV-1003. | `tests/test_validation.py`; `tests/golden.yaml` |
| 08 | Unknown items and invalid quantities are flagged, including INV-1008, INV-1016 and INV-1009. | `tests/test_validation.py`; `tests/golden.yaml` |
| 09 | VP review uses explicit policy and extra scrutiny above $10,000. | `config/policy.yaml`; `tests/test_approval.py::test_critic_runs_over_threshold_and_can_sign_off` |
| 10 | The critic can object, the VP can revise, and unresolved disagreement reaches a human after a bounded loop. | `tests/test_approval.py::test_vp_can_concede`; `test_loop_stops_after_two_rounds_and_deadlocks`; offline extras 2005 and 2006 |
| 11 | Only authorized invoices reach the supplied mock payment function; human rejections persist, stale reviews cannot pay, conditions block, and failed or unknown payments remain visible. | `tests/test_submission_safety.py`; `tests/test_payment.py`; `tests/test_history.py` |
| 12 | Rejections record reasons, and results and agent steps are available as structured output. | `tests/test_golden.py::test_trace_written`; `tests/test_review2.py::test_every_step_log_line_is_valid_json` |
| 13 | Grok performs extraction cross-checks and risk/approval reasoning in live mode; offline stand-ins are labeled accurately. | `invoice_agents/llm.py`; `invoice_agents/agents/`; recorded live traces and provenance in `docs/evals.md` |
| 14 | Multiple stages are orchestrated with explicit state and conditional routes. | `invoice_agents/graph.py` uses LangGraph and Pydantic; `tests/test_golden.py` |
| 15 | The model can call local vendor, inventory and history tools and receive their results. | `tests/test_agentic.py::test_risk_agent_calls_tools_and_cannot_lower_score`; recorded live `tool_call` events |
| 16 | Model output is schema-validated and failed output is retried with validation feedback, then fails safely. | `tests/test_agentic.py::test_ingestion_self_corrects_after_schema_error`; `test_ingestion_gives_up_after_three_bad_answers` |
| 17 | The prototype runs locally in Python with simulated inventory and payments and an explicit mode that makes no model calls. | `main.py --offline`; `tests/test_evals.py::test_offline_makes_no_llm_calls`; `.github/workflows/ci.yml` |
| 18 | The brief's example command works, and documented setup supports Windows and POSIX shells. | `tests/test_cli.py::test_brief_example_path_runs_the_matching_sample`; `README.md`; Windows portability verification |
| 19 | A reviewer can inspect decisions, use the local review queue, reproduce tests, and understand business assumptions, scope cuts and evidence limits. | `tests/test_ui.py`; `READ_THIS_FIRST.md`; `docs/design.md`; `docs/evals.md`; `docs/presentation.md` |
| 20 | The submitted public GitHub revision contains the reviewed changes and its CI passes. | Verify the submitted commit and its [CI run](https://github.com/adamtpang/galatiq.vercel.app/actions/workflows/ci.yml) before sending the link. Local changes alone do not satisfy this check. |

## Verification baseline

The October 23 Windows continuation verified 440 offline tests passing with one live test deselected, including ruff and mypy. This was commit `3187839` plus the four portability changes in `invoice_agents/graph.py`, `tests/test_history.py`, `tests/test_review2.py` and `tests/test_validation.py`. Fresh offline evaluation caught 15/15 bundled adversarial cases, caught 15/15 in a separate later run, and held all four unseen layouts. That evidence can be reused while those implementation files are unchanged; documentation edits do not require repeating the entire suite.

To reproduce when relevant: `python -m pytest -q -rx` and `python -m evals --no-write`. Neither command enables live tests. Install `requirements.txt` first so lint and type checks are available. A saved result is evidence for its recorded revision, not every future revision.

A subsequent recovery review found that retrying a previously failed payment did not mark it in progress before calling the mock bank. An interruption could therefore leave it eligible for another payment. The retry now commits an atomic claim before the bank call; a regression test verifies that a restarted process holds the uncertain attempt. The updated Windows suite passed 441 offline tests with one live test deselected, including lint and type checks. Publication and CI must still be verified for the revision containing this fix.

The submission audit then added regression coverage for persistent human rejection, failed and unknown payments
after human approval, competing decisions and automatic retries, stale UI forms, and unresolved approval conditions.
Recovery now belongs to the common payment path, and review authorization is checked atomically before payment.
The same audit moved the input-size limit to shared file loading, excluded private local context from Docker,
and rejected amounts that round to zero. The historical 441-test result predates these changes; check CI on the
submitted revision for the current suite. This is evidence for defined scenarios, not proof of defect-free software.

The final local audit suite passed 457 offline tests with one live test deselected, including ruff, mypy, concurrent
review tests and localhost UI tests. Fresh offline evaluation matched 99/99 scored fields on the 20 supplied invoices
(one relative due date is ambiguous), caught 15/15 adversarial cases both together and in a later run, and held all
four unfamiliar layouts. Across samples plus six extra inputs, extraction was 119/127 (93.7%); the misses are on
the deliberately difficult email and truncated JSON examples. These results do not replace the live-evidence limits.

## Interpretation and limits

- The brief does not define an exclusive list of outcome labels. `SUPERSEDED` records why an otherwise valid original is not payable after a revision arrives; it is audited and never paid. Relabeling it is not an acceptance requirement.
- The critique and schema-retry loops are implemented and tested with offline/scripted inputs. No live critic objection or live schema-retry event has been observed. Those are unverified live behaviors, not fabricated demonstrations.
- Full live runs predate later policy changes. Their results, commit and later spot checks are distinguished in `docs/evals.md`. A fresh full live run would provide stronger evidence but requires explicit spending authorization.
- The web page replays saved runs. The executable system and human review UI run locally. No live upload backend or cloud deployment is required by this checklist.
- Sample accuracy is in-sample. The small adversarial and unseen sets do not prove universal fraud detection, and the offline parser deliberately holds unfamiliar layouts.
- Passing this checklist does not establish production readiness, actual business savings, or a guaranteed interview grade.
