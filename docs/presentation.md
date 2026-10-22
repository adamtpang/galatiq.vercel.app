# Presentation: 5 to 10 minute walkthrough

## 1. The problem (1 min)

Acme loses about $2M a year processing invoices by hand. 30% carry an error and payment takes 5 days. The work is retyping, checking against an inventory database nobody trusts, and chasing a VP over email. The 20 samples show why it is hard: six formats, OCR noise, duplicates across formats, a revision, a renamed vendor $25 under the approval limit, and an obvious fraud attempt.

## 2. What I built (2 min)

A LangGraph pipeline of five agents: ingest, validate, risk, approve, pay. One typed state object moves through it and every step is written to a JSONL trace.

Three design rules carry most of the weight:

- **Code owns the math.** Line sums, totals, FX and stock checks are deterministic. Grok extracts and reasons; it never sets an amount.
- **Blocking flags reject, no matter what the model says.** 12 of 20 samples are decided this way with no LLM call.
- **Everything is explainable.** Each flag has a code, a severity and evidence. Each decision has reasons and, where relevant, the VP and critic arguments.

## 3. Live demo (4 min)

Follow [demo_script.md](demo_script.md): one invoice with the exact brief command, the offline batch, 1012 (renamed vendor, hard hold), 1004 (revision), 1003 (fraud), a chaos run, the review queue, then the web replay.

## 4. Business impact (1 min)

Offline the system decided 18 of 20 samples without a person, in seconds, and every rejection names the failed check. With the assumptions stated in the README (70% of the $2M is touch work, 10% to 20% of invoices still go to a human), that is roughly $1.1M to $1.25M a year of manual work removed, before running costs. The numbers to replace with Acme's data are listed next to the estimate.

## 5. What I would do next (1 min)

Weeks 1 to 2: mailbox and ERP connectors, PO matching, shadow mode next to the AP team. Weeks 3 to 4: review UI, approval limits by role, Postgres, an evaluation set from the shadow run in CI. Weeks 5 to 6: go live for low-risk known vendors under $10K, then widen as the override rate allows.

## Questions to expect

- **Why LangGraph?** Explicit nodes and edges make the flow auditable and easy to test, and conditional routing (pay, reject, hold) is a first-class edge.
- **How do you stop the model inventing amounts?** It never computes them. Totals and FX come from code; the model can only add reasons and raise a risk score.
- **Prompt injection?** Invoice text goes inside `<invoice_document>` tags as data. The rules flag instruction-like text, Grok's risk review has a structured `prompt_injection` field, and either one holds the invoice for a person whatever the score (invoices 2002, 3001, 3002; decision 8). The risk agent cannot lower the rule score.
- **Why do live and offline differ?** On the 20 samples Grok is more cautious than the rules: every difference is a hold where the rules would pay. The extras differ for another reason: Grok can read files the parsers cannot. 2001 (an email) and 2003 (truncated JSON) are rejected offline; live, Grok rebuilds them and decision 10 holds both for a person, who sees the original next to Grok's reading. Nothing rebuilt by Grok is paid automatically. See run_log.md.
