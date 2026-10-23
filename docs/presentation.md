# Presentation: 5 to 10 minute walkthrough

## 1. The problem (1 min)

Acme loses about $2M a year processing invoices by hand. 30% carry an error and payment takes 5 days. The 20 samples show why: six formats, OCR noise, duplicates across formats, a revision, a renamed vendor $25 under the approval limit, and an obvious fraud attempt.

## 2. What I built (2 min)

A LangGraph pipeline (ingest, validate, risk, approve, memo, then pay, reject or hold) with six Grok agents live: extractor, risk reviewer, VP, critic, rejection reviewer (it can only escalate) and memo writer. Offline, rules stand-ins take their place. Validation and payment are code, and a fail-closed guard means an error in any step never reaches the bank.

- **Code owns the math.** Grok reads, reviews and argues; it never sets an amount.
- **Blocking flags reject, whatever the model says.** 11 of 20 samples are rejected this way.
- **Everything is explainable.** Each flag has a code, a severity and evidence; each decision has reasons.

## 3. Live demo (4 min)

Follow the demo section of [evals.md](evals.md#demo-what-to-run-and-what-to-point-at): the brief's exact command, the offline batch, 1012 (renamed vendor, hard hold), 1004 (the original is superseded and not paid, R1 is paid), 1003 (fraud), 2005 (the critic loop offline), a chaos run, the review queue in the browser, then the web replay.

## 4. Business impact (1 min)

Offline, 17 of the 20 samples finish without a person (5 paid, 11 rejected, 1 superseded original), in under a second, and every rejection names the failed check; 3 are held. With the assumptions stated in [docs/design.md, Business impact](design.md#business-impact) (70% of the $2M is touch work, 15% to 20% of invoices still go to a person), that is roughly $1.1M to $1.2M a year of manual work removed, before running costs.

## 5. What I would do next (1 min)

Weeks 1 to 2: mailbox and ERP connectors, PO matching, shadow mode. Weeks 3 to 4: a production review UI with SSO, role limits, Postgres, an eval set in CI. Weeks 5 to 6: go live for low-risk known vendors under $10K, then widen as the override rate allows.

## Questions to expect

- **Why LangGraph?** Explicit nodes and conditional edges (pay, reject, hold) make the flow auditable and testable.
- **How do you stop the model inventing amounts?** It never computes them; it can only add reasons and raise a risk score.
- **Prompt injection?** Invoice text is fenced as data; the rules and Grok's structured `prompt_injection` field each hold the invoice (decision 8). Bank-detail wording holds too (decisions 11 and 20).
- **Why do live and offline differ?** Grok is more cautious than the rules: the differences are holds where the rules would pay, plus 1014 (paid live before decision 22) and 1004 (REJECTED live before decision 24, SUPERSEDED now; neither pays it). Hard rules run first, so Grok cannot pay what they block.
- **Has the critic objected live?** No. It ran once live and signed off; on the five invoices written to make it object (2005 to 2009), the Grok VP held each one first.
- **Is this overfit?** Partly; the parsers, vendor master and patterns were written against these files. The adversarial and unseen sets measure how far that carries.
