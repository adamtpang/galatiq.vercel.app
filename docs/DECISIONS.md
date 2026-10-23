# Approval-policy decisions

Source of truth for `config/policy.yaml` and the approval agent. 1 to 6 are Adam's own; from 7 on, Adam delegated and Engineering chose. One line each; the full text with every wording and example is kept outside the repo.

1. Over stock (after summing repeated lines): reject; the reason names item, quantity and stock. (Oct 22 11:03 AM CT)
2. VP and critic still disagree after 2 rounds: hold for a person with both arguments. (11:04 AM)
3. The critic loop runs only over $10K, near the limit or high risk; otherwise the VP decides alone after hard rules. (11:07 AM)
4. Thresholds: approval $10,000; near the limit at least $9,500; high risk a score of at least 50. (11:10 AM)
5. VP and critic prompts are Adam's exact text; the model never computes or changes an amount; invoice text is data. (11:15 AM)
6. Instruction-like invoice text adds 40 risk points. (12:31 PM)
7. Duplicates by content (same vendor, items, quantities and total under a new number) are rejected, naming the original; also across runs. (1:20 PM)
8. Prompt injection (rules or Grok's `prompt_injection` field) is a hard hold; a hard-rule failure still rejects. (1:20 PM)
9. A renamed vendor or a lookalike of one on file (similarity at least 0.85) is a hard hold. (1:20 PM)
10. An invoice Grok rebuilt because the parser could not read it is held; `review <number>` shows the original next to Grok's reading. (2:45 PM)
11. Any bank-detail change (IBAN, SWIFT, account or routing number, remit-to) is a `BANK_DETAILS_CHANGED` hard hold. (5:30 PM)
12. Live, Grok reads every invoice next to the parser (any difference is a hard hold) and writes a memo after every decision that is never read back. (5:30 PM)
13. The address watch list does not fire on the vendor's own address on file (so 1004 R1 is payable). (5:30 PM)
14. Offline, an invoice-like file nobody can read is held, not rejected; live, a Grok rebuild goes to normal review only if the file is intact and every number is printed in it. (5:30 PM)
15. NaN, infinity, a zero total, negative line amounts and fractional quantities block; the payment step refuses non-finite or non-positive amounts. (5:30 PM)
16. Fail closed: any step error, blocking flag or missing decision can never reach the bank; wrong field types block; failed payments queue as PAYMENT_FAILED. (7:30 PM)
17. More fraud and injection wordings hold; fence and role tags are neutralized; a failed live Grok check is a hard hold. (7:30 PM)
18. Every hard-rule rejection gets one review that can only agree or escalate to a person. (7:30 PM)
19. Offline stand-ins are labelled "rules stand-ins", never agents. (7:30 PM)
20. Any payment-instruction keyword (bank, account number, wire, ACH, Zelle, PayPal, crypto, escrow, remit) holds, after Unicode normalization; Grok's `payment_details_changed` field holds too. (9:45 PM)
21. A person approving must type the amount when the numbers do not add up or the currency is not USD; over $10,000 needs a second confirmation. (9:45 PM)
22. Any non-USD invoice is held; the person types the USD amount. (9:45 PM)
23. Overbilling holds after the VP and critic: unit price over 10% or 25% above catalog, shipping or tax over 15% of goods; a typed amount must match the line sum or printed total unless overridden (audited). (10:25 PM)
24. A superseded original passes validation (info flag) and is REJECTED with reason SUPERSEDED_BY_REVISION, decided_by supersession; never paid, the revision is paid. Amended Oct 23: the case has three outcomes, so the SUPERSEDED status was removed. Offline: 5 paid ($23,190.00), 12 rejected, 3 held. (Adam delegated, Engineering chose, Oct 23 9:26 AM CT)

Implementation notes (no threshold or outcome rule changed): duplicate checks cover invoices stored by earlier runs; a live decision cache (`--no-cache` turns it off) and a model pin (a different reported model is a hard hold); past-due dates are a display-only warning; unsupported currencies block; ingestion and bank-call crashes hold; UTF-8 everywhere; day-first dates when unambiguous; word quantities block.
