# Adam's approval-policy decisions (source of truth for config/policy.yaml and the approval agent)
1. Over-stock (qty > stock for any SKU, after aggregating repeated lines): REJECT. Reason names the item, requested qty, and stock. (Adam, Oct 22 11:03 AM CT)
2. VP/critic deadlock after 2 rounds (VP approve, critic still objects): PENDING_HUMAN, sent to the human review queue with both arguments attached. (Adam, Oct 22 11:04 AM CT)
3. Critic loop runs only for invoices over $10K, near the limit, or with a high risk score; others are decided by the VP agent alone (after hard rules). (Adam, Oct 22 11:07 AM CT)
4. Thresholds: approval threshold $10,000; "near the limit" = total >= $9,500; "high risk" = risk_score >= 50 out of 100. (Adam, Oct 22 11:10 AM CT)
5. Approved agent prompts (Adam, Oct 22 11:15 AM CT):
   VP (approver): "You're Acme's VP of Finance. You see the invoice, the check flags and the risk score. Hard-rule failures are already rejected, so judge the rest. Approve only if the vendor is known, the math is clean and nothing looks off. Give 1 to 3 short reasons, plus any conditions on payment."
   Critic (CFO/auditor): "You're a skeptical auditor. Your job is to find why the VP is wrong: a vendor that was renamed, an amount sitting just under the limit, a price far off catalog, pushy wording. Either object with a specific reason or sign off. Never invent facts that aren't in the invoice."
   Rule: the LLM never computes or changes amounts; deterministic code is the source of truth for math, the LLM only reasons over it. Invoice text is treated as data (prompt-injection defense).
6. Prompt-injection risk signal: invoice text that tries to instruct the system adds 40 risk points (config/policy.yaml, risk_weights.prompt_injection), so offline holds such an invoice for human review. (Adam, Oct 22 12:31 PM CT)
