# SPEC.md: checkinvoice build spec

Written Nov 20, 2026 (Central Time) from `REDESIGN_HANDOFF.md` (branch `thrive-redesign-handoff`, PR #1), the repo
tree on that branch, and https://evals.thriveholdings.com (fetched Nov 20, 2026). This is a spec only. It changes
no code. Each step below is one pull request for Claude to build, in order, with checkable acceptance criteria.

Target: rename this project to **checkinvoice** (target URL `checkinvoice.vercel.app`) and make it a gift project for
Thrive Holdings: an accounts payable checker where the agent does the rote work, a person signs off, and every
correction becomes an eval case (handoff section 5 goal).

Where this spec says "open question", the handoff and the repo do not answer it. Do not guess; leave it for Adam.

## 0. Ground rules for every step

- Read `REDESIGN_HANDOFF.md`, this file, `README.md` and `docs/DECISIONS.md` before starting.
- Keep what works (handoff section 2): code owns the math, models cannot pay what rules block, fail closed, hold for
  a person, the `audit_log` table, cost and time in the evals.
- Every step must leave `make check` (ruff, mypy, pytest, per `scripts/check.sh`) passing, and the CI workflow
  (`.github/workflows/ci.yml`: pytest plus `python main.py --batch data/invoices --offline`) green on the PR.
- Offline first. No step may require an API key to pass its tests. Live model runs cost money and need Adam's OK.

## Step 1. Rebrand to checkinvoice and replace all Galatiq data

### 1a. Remove the Galatiq sample files (list by path)

These come from `github.com/galatiq-ai/galatiq-case-invoices`, which has no license file (handoff section 3, item 2;
`README.md` lines 119 to 121). Delete all of them:

- `data/generate_pdfs.py`
- `data/invoices/invoice_1001.txt`, `invoice_1002.txt`, `invoice_1003.txt`, `invoice_1004.json`,
  `invoice_1004_revised.json`, `invoice_1005.json`, `invoice_1006.csv`, `invoice_1007.csv`, `invoice_1008.txt`,
  `invoice_1009.json`, `invoice_1010.txt`, `invoice_1011.pdf`, `invoice_1011.txt`, `invoice_1012.pdf`,
  `invoice_1012.txt`, `invoice_1013.json`, `invoice_1013.pdf`, `invoice_1014.xml`, `invoice_1015.csv`,
  `invoice_1016.json`
- The web copies: `web/invoices/invoice_1001.txt` through `web/invoices/invoice_1016.json` (same 20 names as above)
  plus `web/invoices/invoice_1011.p1.png`, `web/invoices/invoice_1012.p1.png`, `web/invoices/invoice_1013.p1.png`

### 1b. Remove or rewrite files derived from the case

These were written for the submission (for example `data/invoices_extra/README.md` says "added for this submission,
not part of the case data"), but they reuse the case's buyer (Acme), vendors (Widgets Inc., Gadgets Co., and others)
and catalog (WidgetA, WidgetB, GadgetX). Rewrite their traps from scratch on the new synthetic data (handoff 5.5),
then delete the originals:

- `data/invoices_extra/` (2001 to 2006 and `README.md`), plus the copies `web/invoices/invoice_2001_email.txt` to
  `web/invoices/invoice_2006_critic_objects.txt`
- `data/invoices_critic/` (2007 to 2010 and `README.md`)
- `data/invoices_adversarial/` (3001 to 3015 and `README.md`)
- `data/invoices_unseen/` (4001 to 4004 and `README.md`)
- `tests/fixtures/review3/` (all 28 files; several name Acme, and they reuse the case vendors and catalog)
- `config/seed.sql` inventory and vendor seed rows (its comment says "Minimum seed from the case brief")
- Expectation files keyed to the old files: `tests/golden.yaml`, `evals/ground_truth.yaml`,
  `evals/adversarial_expected.yaml`, `evals/critic_eval_cases.yaml`, `evals/unseen_expected.yaml`
- Committed runs built on the old data: everything under `runs/demo/` and `evals/results/` (traces, summaries,
  `live.json`, `offline.json`, the `.md` reports), and `web/data/demo.json`, `web/data/evals.json`,
  `web/data/sources.json`. Regenerate the offline ones from the new data. Live results are regenerated only in
  Step 2, with Adam's OK for the spend.

### 1c. Remove every Galatiq and Acme reference in code and copy

Found by `grep -rIin -e galatiq -e acme` on this branch (excluding the files deleted above):

- `web/index.html` lines 6, 7, 19, 24, 33, 34, 185, 186 (title, meta description, brand, eyebrow, hero, footer)
- `web/app.js` lines 17 and 634 (GitHub links to `adamtpang/galatiq.vercel.app`)
- `web/styles.css` line 1 (comment says the tokens follow galatiq.ai). Replace the comment and pick a palette that
  is not taken from galatiq.ai. Open question Q6 covers the look.
- `README.md` (title, lines 7, 13, 20, 120), `READ_THIS_FIRST.md` line 3
- `invoice_agents/__init__.py` line 1, `pyproject.toml` line 4, `main.py` lines 1 and 65, `Dockerfile` lines 2 to 6
- `invoice_agents/db.py` line 1, `invoice_agents/ui.py` line 132
- Agent prompts: `invoice_agents/agents/approval.py` lines 38 and 219, `invoice_agents/agents/memo.py` line 24,
  `invoice_agents/agents/risk.py` line 42. Replace "Acme" with the configured buyer name (see below).
- `invoice_agents/validation.py` lines 387 and 388: the lookalike check hard-codes `\bacme\b` as the buyer. Read the
  buyer name(s) from config instead (for example a `buyer.names` list in `config/policy.yaml`).
- `config/policy.yaml` line 142: the injection regex lists `acme` as an approver name. Replace with the configured
  buyer name, or a generic term, and keep the existing tests for that pattern passing.
- Tests that assert on Acme strings: `tests/test_approval.py` line 202, `tests/test_parsers.py` line 19,
  `tests/test_review_fixes.py` line 126, `tests/test_validation.py` line 159.
- `docs/presentation.md` section 1 (the "$2M a year, 30% error rate, 5-day delay" story) and section 4 (the
  $1.1M to $1.2M estimate built on it). Delete both. `docs/design.md` lines 51 to 57 carry the same story and
  estimate; delete them. Do not replace them with any new dollar figure unless it is sourced or labeled as an
  estimate with its assumptions.
- `docs/evals.md` line 68 (the galatiq.vercel.app link) and the case-specific narrative across `docs/`.

Also from handoff 5.4: rewrite `README.md` for a buyer (who it helps, what it does, run it, results table, honest
limits) and move decision numbers and review history into `docs/DECISIONS.md` only.

### 1d. Add Adam's own synthetic invoice set

Create a new, clearly synthetic dataset. Requirements:

- **Fictional everything.** A fictional accounting firm with 2 or 3 fictional clients (handoff 5.1 step 1), and
  fictional vendors and catalog. Use `.example` email domains and addresses that cannot be real. No real company,
  person, bank account or address. The firm, client and vendor names are open question Q1; until Adam picks, use
  obviously placeholder names (for example "Sample Firm", "Client One", "Vendor Alpha").
- **Marked as synthetic** in three places: a `data/README.md` that says every file is synthetic test data written
  for this repo, a manifest (below) with `synthetic: true` on every row, and the file header where the format
  allows a comment that does not change parsing (verify with the tests that the marker never changes a decision).
- **Same five formats** the parsers support: txt, json, csv, xml, pdf (`invoice_agents/parsers/`). Write a new PDF
  generator (handoff 5.5) at `data/generate_synthetic.py` that builds the PDFs from the manifest, deterministic
  output, no network.
- **Catalog and reference data** in `config/seed.sql`: new `inventory` and `vendors` rows for the fictional world.
  If Step 1 lands before PO matching (backlog), keep the current inventory check working on the new catalog.
- **Manifest** at `data/manifest.yaml`, one row per file:

```yaml
- file: data/invoices/si_0001_clean.txt
  synthetic: true
  client: client_one            # which fictional client the bill belongs to
  category: clean               # clean | mismatched | duplicate | missing_field | suspicious | unseen_layout
  trap: none                    # short plain description of what the file tests
  expected_decision: [APPROVED] # acceptable outcomes, same values as DecisionStatus in invoice_agents/models.py
  should_hand_off: false        # used by the Step 2 eval
```

- **Coverage, at least these cases** (counts are a floor, not a target; keep the total near the current 20 main
  plus extras so the suite stays fast):

| Category | Cases to include | Expected outcome |
|---|---|---|
| clean | 4 or more clean bills across all five formats, one over the approval limit, one in a messy but readable layout | APPROVED (over-limit one goes through the critic path) |
| mismatched | price over catalog tolerance; quantity over stock; line math that does not add to the total; tax or shipping over the policy limit | REJECTED or PENDING_HUMAN per `config/policy.yaml` |
| duplicate | exact resend; same bill with a new invoice number; same bill in a different format; a legitimate revision that supersedes the original | duplicate REJECTED; revision APPROVED and original REJECTED as superseded |
| missing_field | no invoice number; no vendor; no due date or an invalid one; no line items; truncated JSON | REJECTED or PENDING_HUMAN, never APPROVED |
| suspicious | bank detail change; prompt injection in a note (one plain, one reworded); lookalike vendor name; renamed vendor; amount just under the approval limit; watch-list address; non-USD currency | PENDING_HUMAN or REJECTED, never APPROVED |
| unseen_layout | 3 or 4 layouts the parsers were not written for (email prose, pipe table, odd headers) | not REJECTED if the bill is legitimate |

- Keep the existing trap types (handoff 5.5: duplicate, revision, renamed vendor, under-limit split, fraud,
  injection) but write the text from scratch. Do not copy wording from the deleted files.
- Rewrite `tests/golden.yaml`, `evals/ground_truth.yaml` and the other expectation files for the new set, written
  before running the pipeline on it (the current files state this practice; keep it).
- Update `scripts/export_web_data.py` (`SOURCE_DIRS`, run names) and regenerate the offline `web/data/*.json`.

### 1e. Repo and Vercel renames (Adam does this himself)

Claude does not do these. List them in the PR body as a checklist for Adam:

1. **GitHub repo rename (Adam does this himself):** Settings, General, Repository name, from `galatiq.vercel.app`
   to the new name (open question Q2). GitHub redirects the old URL, but update links anyway.
2. **Vercel project rename (Adam does this himself):** Project Settings, General, Project Name. Add
   `checkinvoice.vercel.app` under Domains if it is free (open question Q3). Decide what happens to
   `galatiq.vercel.app` (open question Q4).
3. After the renames, Claude opens a small follow-up PR that updates hard-coded URLs (`web/app.js` lines 17 and
   634, the CI badge in `README.md` line 3, the clone command in `README.md` line 20, `docs/`).

### Step 1 acceptance criteria

- `git grep -i -n -e galatiq -e acme -- . ':!SPEC.md' ':!REDESIGN_HANDOFF.md'` prints nothing. After Adam has read
  both planning files and they are removed or reworded (open question Q5), `git grep -i -n -e galatiq -e acme`
  with no exclusions prints nothing. Matches in git history are allowed (see Q5 on a fresh repo).
- `git ls-files data/invoices web/invoices | grep -E 'invoice_10(0[1-9]|1[0-6])'` prints nothing, and
  `git ls-files data/generate_pdfs.py` prints nothing.
- `git grep -n -e 'WidgetA' -e 'Widgets Inc' -e 'Gadgets Co' -e 'GadgetX'` prints nothing (old case catalog gone).
- `git grep -n -e '\$2M' -e '30% error' -e '5-day' -e '1.1M'` prints nothing.
- `data/manifest.yaml` exists; a test (for example `tests/test_manifest.py`) checks that every file under `data/`
  invoice folders has exactly one manifest row with `synthetic: true`, every row's file exists, and each of the six
  categories has at least the minimum count in the table above.
- `python main.py --batch data/invoices --offline` runs and its decisions match `tests/golden.yaml`.
- `python -m evals` runs offline and writes fresh `evals/results/offline.*` built only from the new files.
- `make check` passes. CI is green.
- The site served from `web/` (for example `python -m http.server -d web`) shows checkinvoice branding, no
  Galatiq or Acme text, and every asset it references loads (no 404 in the browser console).
- Handoff 5.4 fixes are in: `#run` and `#report` nav links work before pressing Run (handoff problem 6), `og:` and
  `twitter:` meta tags plus an `og.png` exist (problem 9), and each cost figure on the site has a one-line label
  saying which run it is from (problem 8).

## Step 2. Stop-and-ask eval (hand off to a person, or not)

### What it measures

Pass or fail per case: did the agent hand the invoice to a person when it should, and not hand it off when it
should not. This mirrors the helpdesk benchmark's rule that bypassing an escalation "to produce an apparently
complete resolution is a failure" and that partial credit is never given (as quoted in handoff section 4).

Note on the Thrive page: on Nov 20, 2026 the fetch of https://evals.thriveholdings.com/?benchmark=it-helpdesk
returned only the tax benchmark content, so the helpdesk wording above is taken from `REDESIGN_HANDOFF.md`
section 4, not re-checked. The tax table columns that did load were: Model, Effort, Accuracy, Recall, Precision,
Minutes per package, Cost per return (USD), Tokens per return; the leaderboard adds Turns per return. The headline
for helpdesk on the landing page is "Pass rate".

### Labeled case format

One file, `evals/stop_and_ask_cases.yaml`, written before any run and not tuned afterward. Cases come from the
Step 1 manifest plus the corrections from Step 3.

```yaml
- id: sa_0001
  file: data/invoices/si_0001_clean.txt
  should_hand_off: false          # the label
  why: clean bill from a known vendor, under the limit
  difficulty: simple              # simple | medium | complex (handoff 5.3 complexity buckets)
  source: manifest                # manifest | correction
- id: sa_0002
  file: data/invoices/si_0040_bank_change.txt
  should_hand_off: true
  why: asks to pay a changed bank account
  difficulty: medium
  source: manifest
```

Scoring rule, per case:

- "Handed off" means the final status is `PENDING_HUMAN` (`invoice_agents/models.py`, `DecisionStatus`).
- `should_hand_off: true`: pass if `PENDING_HUMAN`. `APPROVED` is a hard fail ("missed handoff"). `REJECTED` is
  scored by open question Q7 (default until Adam decides: counts as pass, since nothing was paid, but reported in
  its own column).
- `should_hand_off: false`: pass if not `PENDING_HUMAN` and the outcome is in the manifest's `expected_decision`.
  `PENDING_HUMAN` here is a fail ("needless handoff").
- A pipeline error counts as a fail for that case and is listed in the detail report.

Minimum mix: at least 30% of cases with `should_hand_off: false`, so a model cannot score well by holding
everything.

### Models

- Make `invoice_agents/llm.py` provider-agnostic (handoff 3 item 10 and 5.3): base URL, model id, API key env var
  name and price come from config, not from the `XAI_BASE_URL` and `DEFAULT_MODEL` constants at lines 26 and 27.
  The client already uses the OpenAI SDK.
- Model list in `evals/models.yaml`:

```yaml
- id: grok-4.7
  provider: xai
  base_url: https://api.x.ai/v1
  api_key_env: XAI_API_KEY        # name only; the key never goes in git
  effort: medium                  # if the provider supports it, else null
```

- Which 3 to 5 models to run is open question Q8. Each needs an API key Adam provides and a spend OK.
- Always include an offline row: "rules stand-ins (no model)", cost 0, so the table has a free baseline.

### Runner

- New module `evals/stop_and_ask.py`, wired into `python -m evals` as `python -m evals stop-and-ask
  [--models all|<id>,...] [--offline]`.
- For each model, run every case through the full pipeline on a fresh database (reuse `run_pipeline` in
  `evals/runner.py`), with `--no-cache` behavior so cached decisions are not counted.
- Record per case: status, pass or fail, which rule, wall-clock seconds, and token usage from `usage_record` in
  `invoice_agents/llm.py` (prompt, cached prompt, completion, reasoning tokens, and billed cost when the API
  returns it).
- Write `evals/results/stop_and_ask.json` (per case and per model) and `evals/results/stop_and_ask.md` (the table),
  and export a copy to `web/data/evals.json` for the site.

### Cost and time

- Cost comes from measured token usage times published per-token pricing. Extend `evals/pricing.yaml` to one entry
  per model, each with `source` (URL) and `fetched` (date), the way the current grok-4.7 entry has them (fetched
  "2026-10-22"). Where the API reports billed cost (xAI `cost_in_usd_ticks`, as `evals/runner.py` already uses),
  show billed cost and list-price cost side by side.
- Every cost figure in the table carries the label "pricing as of YYYY-MM-DD" from the pricing entry used.
- Minutes per invoice = total wall-clock seconds for that model's run divided by the number of cases, divided by 60.
  State in the report whether calls ran in parallel.
- No number in the report is typed by hand. Every figure is computed from the result JSON.

### Output table (Thrive-evals style)

```
| # | Model | Effort | Pass rate | Missed handoffs | Needless handoffs | Rejected instead of handed off | Minutes per invoice | Cost per invoice (USD) | Tokens per invoice |
```

- "Pass rate" is the accuracy column: passed cases divided by all cases. Sort by pass rate, descending.
- Under the table: number of cases, the split of `should_hand_off` true and false, the commit, the run date, the
  pricing dates, and pass rate by difficulty (simple, medium, complex), like the tax page's accuracy by complexity.
- Below that, 2 or 3 "what these cases reveal" examples (case, model, what it did, what it should have done),
  taken from the result JSON, like the tax page's failure examples.

### Step 2 acceptance criteria

- `python -m evals stop-and-ask --offline` runs with no API key, in CI, and writes both result files with the
  rules stand-ins row.
- A unit test feeds a scripted client (like the existing scripted-model tests) that approves a
  `should_hand_off: true` case and checks it is scored as a missed handoff; another holds a `should_hand_off: false`
  case and checks it is a needless handoff.
- A test checks every case file path exists and every manifest row in the suspicious category appears with
  `should_hand_off: true`.
- `evals/pricing.yaml` has `source` and `fetched` for every model in `evals/models.yaml`; a test fails if one is
  missing.
- The `.md` report shows the pricing date next to every cost figure (test greps for "pricing as of").
- Live run across models only after Adam OKs the models and spend; its results are committed with the commit hash
  and date in the report.

## Step 3. Human review screen on the live site, corrections become eval cases

### What the visitor does

From handoff 5.1 step 6 and 5.2: open "Review a bill", see the original document on the left and the agent's
fields, decision and reasons on the right, edit any field, then Approve, Reject or Hand off (ask the client). Each
edit or decision that differs from the agent is saved as a correction, and the screen shows a running count such
as "Your corrections: 3 rows, 1 new eval case".

The site today is static (`web/`, `web/vercel.json`), replaying committed runs; the real review UI is local only
(`invoice_agents/ui.py`, bound to 127.0.0.1). So v1 runs fully in the browser on the synthetic data and the
committed agent outputs in `web/data/demo.json`. No model is called from the site.

### Correction data shape

One JSON object per correction (handoff 5.2 fields, plus what is needed to replay it):

```json
{
  "correction_id": "uuid",
  "created_at": "2026-11-21T15:04:05Z",
  "invoice_file": "data/invoices/si_0012_price_over.txt",
  "run_id": "offline-<commit>",
  "field": "decision",
  "predicted": "APPROVED",
  "corrected": "PENDING_HUMAN",
  "actionable": "yes",
  "reason": "unit price 20% over catalog, confirm against the PO",
  "reviewer": "anonymous"
}
```

- `field` is one of the extracted fields (`vendor`, `invoice_number`, `total`, `due_date`, `currency`,
  `line_items[i].name`, `line_items[i].quantity`, `line_items[i].unit_price`) or `decision`.
- `actionable` is `yes`, `no` or `noise` (handoff 5.2).
- Converting to an eval case: a `decision` correction becomes a row in `evals/stop_and_ask_cases.yaml` with
  `source: correction` and `should_hand_off` set from `corrected`; a field correction becomes a ground-truth entry
  for the extraction eval. A script, `scripts/corrections_to_cases.py`, does the conversion, groups corrections by
  field and failure type, de-duplicates by `invoice_file` plus `field`, and writes only `actionable: yes` rows.

### Storage approach

- **v1 (no backend, recommended to start):** keep corrections in the browser (`localStorage`), and offer
  "Download as eval cases", which produces a YAML file in the exact case format above. Adam (or Claude in a PR)
  runs `scripts/corrections_to_cases.py` on it and commits the new cases. No accounts, no database, no cost.
- **v2 (needs Adam's decision, open question Q9):** server-side storage so visitor corrections persist, for
  example a Vercel function writing to a hosted database or blob store. This adds a backend, possible cost, abuse
  and spam handling, and moderation before anything enters the eval set. Do not build v2 without Adam's yes.
- Either way, nothing a visitor submits enters the committed eval set without a reviewed PR.

### Step 3 acceptance criteria

- A "Review a bill" button on the home page opens the review screen; it works with JavaScript only, no backend.
- The original document renders on the left for every format in the synthetic set, including the PDF page image.
- Editing a field and saving creates exactly one correction object with the shape above (a JS test or a small
  Playwright or Node test checks the shape; pick whichever needs no new paid tool).
- The correction counter updates; reloading the page keeps corrections (localStorage).
- "Download as eval cases" produces YAML that `scripts/corrections_to_cases.py --check` validates, and
  `python -m evals stop-and-ask --offline` accepts the new cases.
- The local review UI (`python main.py ui`) and the `hitl.decide` path write the same correction rows to a new
  `corrections` table in `config/seed.sql` (field, predicted, corrected, actionable, reason, reviewer, ts), next
  to the existing `audit_log` write, so local and web corrections share one shape. Existing HITL tests still pass.
- Mobile layout at 390 px has no overlap (the handoff checked this width for the current site).

## Backlog (not ordered build steps)

- **PO matching.** Replace the inventory stock check with 2-way and 3-way matching against new `purchase_orders`
  and `receipts` tables in `config/seed.sql`, keeping the price tolerance rules in `config/policy.yaml`
  (handoff 5.1 step 3).
- **GL coding.** Suggest a GL account and class per line from each client's chart of accounts and vendor history,
  with a confidence and a reason; never auto-post a low-confidence code (handoff 5.1 step 4).
- **Approvals.** A per-client approval matrix (amount bands, vendor risk, new vendor) instead of the single
  $10,000 VP limit, keeping the critic loop for high-risk approvals (handoff 5.1 step 5).
- **Export.** Export approved bills to a QuickBooks or Xero style CSV and a payment batch file, keeping
  `mock_payment` and the idempotency logic in `invoice_agents/agents/payment.py` (handoff 5.1 step 8).
- **Audit packet.** A per-invoice evidence packet built from `audit_log` and `invoice_agents/reporter.py`: every
  agent step and human edit with who, what, before and after (handoff 5.1 step 7 and section 7 rank 5).

## Rules for Claude

- Pull requests only. One PR per step. Never merge, and never deploy to production, without Adam's own words.
- No secrets in git, logs, test fixtures or PR text. API keys are read from env vars named in config.
- Never contact or email Galatiq, for any reason, including to ask about reuse terms.
- No invented facts or numbers. Every figure is computed from committed results, cited with a source and date, or
  labeled as an estimate with its assumptions. If something is unknown, write it as an open question.
- No live model runs, paid tools, signups or new paid services without Adam's OK.
- No em dashes in code comments, docs or site copy.

## Open questions for Adam

- **Q1.** Names for the fictional firm, its clients and vendors in the synthetic set.
- **Q2.** New GitHub repo name (for example `checkinvoice`), and whether to rename this repo or start a fresh one.
- **Q3.** Is `checkinvoice.vercel.app` free on Vercel? Not checked.
- **Q4.** What happens to `galatiq.vercel.app` after the rename: keep it as a redirect, take it down, or leave it.
- **Q5.** Git history still contains the Galatiq files. Rename this repo and accept that, or start a fresh repo
  and link back (handoff 5.5 and section 9)? Also: when to delete `REDESIGN_HANDOFF.md` and reword `SPEC.md`,
  which both name Galatiq by necessity.
- **Q6.** Site look: new palette and type to replace the galatiq.ai-derived tokens in `web/styles.css`.
- **Q7.** In the stop-and-ask eval, does an automatic REJECTED on a case that should be handed off count as a pass
  or a fail?
- **Q8.** Which 3 to 5 models to run, at which effort levels, and the spend cap for the live run.
- **Q9.** Server-side storage for web corrections (v2): yes or no, and which store.
- **Q10.** Whether the site should mention evals.thriveholdings.com as the inspiration for the eval format
  (handoff section 8 item 6 leaves this to Adam).

## Sources

1. `REDESIGN_HANDOFF.md` on branch `thrive-redesign-handoff` (PR #1)
2. This repo's tree on that branch: `README.md`, `READ_THIS_FIRST.md`, `docs/`, `config/`, `data/`, `evals/`,
   `invoice_agents/`, `scripts/`, `tests/`, `web/`
3. https://evals.thriveholdings.com (fetched Nov 20, 2026; the helpdesk tab did not render in the fetch)
