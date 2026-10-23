# Presentation: 5 to 10 minute walkthrough

## 1. The problem (1 min)

Acme loses about $2M a year processing invoices by hand. 30% carry an error and payment takes 5 days. The work is retyping, checking against an inventory database nobody trusts, and chasing a VP over email. The 20 samples show why it is hard: six formats, OCR noise, duplicates across formats, a revision, a renamed vendor $25 under the approval limit, and an obvious fraud attempt.

## 2. What I built (2 min)

A LangGraph pipeline (ingest, validate, risk, approve, memo, then pay, reject or hold) with six Grok agents live: the extractor, the risk reviewer, the VP, the critic, the rejection reviewer (it can only escalate a hard-rule rejection to a person) and the memo writer. Offline, rules stand-ins take their place. Validation and payment are deterministic code, and a fail-closed guard means an error in any step can never reach the bank. One typed state object moves through it and every step is written to a JSONL trace.

Three design rules carry most of the weight:

- **Code owns the math.** Line sums, totals, FX and stock checks are deterministic. Grok reads every invoice next to the parser (a disagreement is a hold), reviews risk, argues the approval and writes the memo; it never sets an amount.
- **Blocking flags reject, no matter what the model says.** 12 of 20 samples are decided this way; live, Grok still reads them and writes their memo, but cannot change the outcome.
- **Everything is explainable.** Each flag has a code, a severity and evidence. Each decision has reasons and, where relevant, the VP and critic arguments.

## 3. Live demo (4 min)

Follow [demo_script.md](demo_script.md): one invoice with the exact brief command, the offline batch, 1012 (renamed vendor, hard hold), 1004 (revision: the original is rejected as superseded, R1 is paid offline), 1003 (fraud), 2004 (the critic loop on a clean $12,500 invoice), a chaos run, the review queue in the browser (`python main.py ui`), then the web replay.

## 4. Business impact (1 min)

Offline the system decided 19 of 20 samples without a person, in seconds, and every rejection names the failed check. With the assumptions stated in the README (70% of the $2M is touch work, 10% to 20% of invoices still go to a human), that is roughly $1.1M to $1.25M a year of manual work removed, before running costs. The numbers to replace with Acme's data are listed next to the estimate.

## 5. What I would do next (1 min)

Weeks 1 to 2: mailbox and ERP connectors, PO matching, shadow mode next to the AP team. Weeks 3 to 4: a production review UI with SSO (the local one is a prototype), approval limits by role, Postgres, an evaluation set from the shadow run in CI. Weeks 5 to 6: go live for low-risk known vendors under $10K, then widen as the override rate allows.

## Questions to expect

- **Why LangGraph?** Explicit nodes and edges make the flow auditable and easy to test, and conditional routing (pay, reject, hold) is a first-class edge.
- **How do you stop the model inventing amounts?** It never computes them. Totals and FX come from code; the model can only add reasons and raise a risk score.
- **Prompt injection?** Invoice text goes inside `<invoice_document>` tags as data. The rules flag instruction-like text, Grok's risk review has a structured `prompt_injection` field, and either one holds the invoice for a person whatever the score (invoices 2002, 3001, 3002; decision 8). Changed bank details are a hard hold too (decision 11, invoice 3008). The risk agent cannot lower the rule score.
- **Why do live and offline differ?** On the 20 samples Grok is more cautious than the rules: every difference in the committed demo runs is a hold where the rules would pay (1001, 1004 R1 and 1010 in the run of Oct 22, 8:29 PM CT); which invoices differ changes from run to run (see run_log.md). Hard rules run first, so Grok cannot pay what they block. On the extras, offline holds the email 2001 and the truncated JSON 2003 because it cannot read them (decision 14); live, Grok reads them but they are still held because its reading is not grounded in the file (decision 10). See run_log.md.
- **Is this overfit to the samples?** Partly, and the README says so: the parsers, the vendor master, the address watch list and the injection patterns were all written while looking at these files. The unseen-layout eval (4 invoices in layouts the parsers were never tuned on) and the adversarial set measure how far that carries.
