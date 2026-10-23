"""Human-in-the-loop review queue, persisted in SQLite (table review_queue)."""
from __future__ import annotations

import math
import sqlite3

from .agents.payment import PaymentAgent, idempotency_key, log_rejection
from .db import log_audit
from .models import Decision, DecisionStatus, InvoiceState, TraceEvent
from .normalize import normalize_invoice_number
from .validation import document_id, fingerprint, local_stamp

MATH_FLAGS = ("LINE_AMOUNT_MISMATCH", "SUBTOTAL_MISMATCH", "TAX_MISMATCH", "TOTAL_MISMATCH")
CONFIRM_OVER = 10_000.00   # decision 21: a human approval above this needs a second, explicit confirmation


def computed_amount(st: InvoiceState) -> float | None:
    """Lines (amount, or qty x unit price) + tax + shipping: the figure a reviewer is shown first on a mismatch."""
    inv = st.invoice
    if inv is None or not inv.items or (inv.currency or "USD") != "USD":
        return None
    lines = sum((li.amount if li.amount is not None else li.qty * (li.unit_price or 0)) for li in inv.items)
    return round(lines + (inv.tax or 0) + (inv.shipping or 0), 2)


def amount_entry_reason(st: InvoiceState) -> str | None:
    """Why a person must type the amount to pay (decision 21), or None when the read total can be paid."""
    math_codes = [f.code for f in st.flags if f.code in MATH_FLAGS]
    if math_codes:
        return f"the invoice's numbers do not add up ({', '.join(math_codes)})"
    if st.invoice is not None and (st.invoice.currency or "USD") != "USD":
        return f"the invoice is in {st.invoice.currency}, so the USD amount must come from a person, not a fixed rate"
    return None


HUMAN = {"approved": DecisionStatus.APPROVED, "rejected": DecisionStatus.REJECTED}


def enqueue(conn: sqlite3.Connection, state: InvoiceState, *, payment_guard: bool = False) -> InvoiceState:
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        return _enqueue(conn, state, payment_guard=payment_guard)


def _enqueue(conn: sqlite3.Connection, state: InvoiceState, *, payment_guard: bool) -> InvoiceState:
    """Queue a held invoice for a person. If a person already decided this invoice in an earlier
    run, that decision stands (re-running a file is idempotent): nothing is queued again."""
    inv, d = state.invoice, state.decision
    fp = fingerprint(inv) if inv else state.source
    prev = conn.execute("SELECT *, datetime(decided_at, 'localtime') AS local_decided_at FROM review_queue "
                        "WHERE fingerprint=?", (fp,)).fetchone()
    if (prev is not None and prev["status"] == "pending" and (prev["reason"] or "").startswith("PAYMENT_")
            and (not payment_guard or prev["reason"].startswith("PAYMENT_UNCERTAIN:"))):
        # A rerun must not erase the settlement state or a reviewer's typed USD amount.
        saved = queued_state(prev)
        state.total_usd, state.payment = saved.total_usd, saved.payment
        state.decision = Decision(status=DecisionStatus.PENDING_HUMAN, decided_by="payment_guard",
                                  reasons=[prev["reason"]])
        return state
    if (prev is not None and prev["status"] in ("approved", "rejected", "paying", "paid_on_retry")
            and (prev["status"] == "rejected" or not payment_guard)):
        status, note, at = prev["status"], prev["reviewer_note"], prev["local_decided_at"]
        saved = queued_state(prev)
        human = status in HUMAN
        state.decision = Decision(
            status=HUMAN[status] if human else DecisionStatus.APPROVED,
            decided_by="human" if human else "payment_guard", risk_score=d.risk_score if d else None,
            reasons=[(f"Already {status} by a human reviewer on {local_stamp(at)}" if human else
                      "Previously authorized payment") + (f": {note}" if note else "")],
            arguments={"agents_decision": d.model_dump(mode="json") if d else None})
        state.total_usd = saved.total_usd
        payment = None
        if status != "rejected" and inv is not None and saved.total_usd is not None:
            key = idempotency_key(inv.number, inv.vendor, saved.total_usd, inv.revision)
            payment = conn.execute("SELECT status FROM payments WHERE idempotency_key=?", (key,)).fetchone()
        paid = payment is not None and payment["status"] == "paid"
        state.payment = ({"status": "already_paid", "amount": saved.total_usd} if paid
                         else {"status": "not_paid", "reason": f"{status} by a human reviewer"})
        if status != "rejected" and not paid:
            state.decision.status = DecisionStatus.PENDING_HUMAN
            state.payment = {"status": "unknown" if payment and payment["status"] != "failed" else "failed",
                             "amount": saved.total_usd, "attempts": 0, "errors": ["Approval has no confirmed payment"]}
            enqueue_failed_payment(conn, state)
        state.trace.append(TraceEvent(agent="hitl", step="already_reviewed",
                                      detail={"fingerprint": fp, "review": status, "note": note, "decided_at": at}))
        return state
    conn.execute(
        "INSERT INTO review_queue (invoice_number, vendor, source_file, fingerprint, reason, state_json) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET state_json=excluded.state_json, "
        "reason=excluded.reason, source_file=excluded.source_file, status='pending', "
        "version=review_queue.version+1, decided_at=NULL WHERE review_queue.status!='rejected'",
        (inv.number if inv else None, inv.vendor if inv else None, state.source, fp,
         "; ".join(d.reasons) if d else None,
         # decision 10: a rebuilt invoice keeps its raw text so the reviewer sees the original next to Grok's reading
         state.model_dump_json(exclude=None if (state.extraction_mode == "llm_repair" or any(
             f.code == "UNREADABLE_LAYOUT" for f in state.flags)) else {"raw_text"})))
    conn.commit()
    state.payment = {"status": "not_paid", "reason": "pending human review"}
    state.trace.append(TraceEvent(agent="hitl", step="queued", detail={"fingerprint": fp}))
    return state


def enqueue_failed_payment(conn: sqlite3.Connection, state: InvoiceState) -> None:
    """Persist failed or uncertain settlement from either the graph or human review."""
    inv, p = state.invoice, state.payment or {}
    fp = fingerprint(inv) if inv else state.source
    reason = (f"PAYMENT_FAILED: approved, but the bank call failed after {p.get('attempts')} attempts "
              f"({'; '.join(p.get('errors', [])[-1:])}); approve to retry the payment, or reject")
    if p.get("status") == "unknown":
        reason = "PAYMENT_UNCERTAIN: reconcile the outcome with the bank before any further payment"
    conn.execute(
        "INSERT INTO review_queue (invoice_number, vendor, source_file, fingerprint, reason, state_json) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET state_json=excluded.state_json, "
        "reason=excluded.reason, source_file=excluded.source_file, status='pending', decided_at=NULL, "
        "version=review_queue.version+1 WHERE review_queue.status!='rejected'",
        (inv.number if inv else None, inv.vendor if inv else None, state.source, fp, reason,
         state.model_dump_json(exclude={"raw_text"})))
    conn.commit()
    state.trace.append(TraceEvent(agent="hitl", step="queued_payment_failed", detail={"fingerprint": fp}))


def clear_failed_payment(conn: sqlite3.Connection, state: InvoiceState) -> None:
    """A paid invoice no longer needs its PAYMENT_FAILED queue entry."""
    if state.invoice is None:
        return
    conn.execute("UPDATE review_queue SET status='paid_on_retry', decided_at=datetime('now'), version=version+1 "
                       "WHERE fingerprint=? AND status IN ('pending', 'paying') "
                       "AND (reason LIKE 'PAYMENT_FAILED:%' OR reason LIKE 'PAYMENT_UNCERTAIN:%')",
                       (fingerprint(state.invoice),))
    conn.commit()


def pending(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM review_queue WHERE status='pending' ORDER BY id").fetchall()


def queued_state(row: sqlite3.Row) -> InvoiceState:
    return InvoiceState.model_validate_json(row["state_json"])


def find_id(conn: sqlite3.Connection, row_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM review_queue WHERE id=? AND status='pending'", (row_id,)).fetchone()


def find(conn: sqlite3.Connection, invoice_number: str) -> sqlite3.Row | None:
    num = normalize_invoice_number(invoice_number)
    return conn.execute("SELECT * FROM review_queue WHERE invoice_number=? AND status='pending' "
                        "ORDER BY id DESC LIMIT 1", (num,)).fetchone()


def resolve(conn: sqlite3.Connection, row: sqlite3.Row, approve: bool, note: str | None,
            pay_amount: float | None = None) -> InvoiceState:
    """Record a person's decision on a queued invoice: review_queue, the invoices history and the audit log.
    The caller pays (approve) or logs the rejection."""
    state = InvoiceState.model_validate_json(row["state_json"])
    if approve and (row["reason"] or "").startswith("PAYMENT_UNCERTAIN:"):
        raise ValueError("The bank outcome is uncertain; reconcile it before any further payment")
    prior = state.decision
    state.decision = Decision(
        status=DecisionStatus.APPROVED if approve else DecisionStatus.REJECTED,
        reasons=[note or ("Approved by human reviewer" if approve else "Rejected by human reviewer")],
        conditions=[],  # a human approval resolves the listed prerequisites; preserve them in the audit arguments
        risk_score=prior.risk_score if prior else None,
        critique_rounds=prior.critique_rounds if prior else 0,
        decided_by="human", arguments={"queued_reason": row["reason"], "review_id": row["id"],
                                       "review_version": row["version"] + 1,
                                       "resolved_conditions": prior.conditions if prior and approve else []})
    if approve and pay_amount is not None:
        state.total_usd = pay_amount
    changed = conn.execute(
        "UPDATE review_queue SET status=?, reviewer_note=?, decided_at=datetime('now'), "
        "version=version+1, state_json=? WHERE id=? AND status='pending' AND version=?",
        ("approved" if approve else "rejected", note, state.model_dump_json(), row["id"], row["version"]))
    if changed.rowcount != 1:
        conn.rollback()
        raise ValueError("This review changed or was already resolved; reload it before deciding")
    if state.invoice is not None:
        conn.execute("UPDATE invoices SET status=? WHERE fingerprint=?",
                     (state.decision.status.value, document_id(state.invoice, state.source)))
    conn.commit()
    log_audit(conn, state.invoice.number if state.invoice else None, "hitl",
              "human_approved" if approve else "human_rejected",
              {"source": state.source, "note": note, "queued_reason": row["reason"],
               "amount": state.total_usd, "review_version": row["version"] + 1,
               "resolved_conditions": state.decision.arguments["resolved_conditions"]})
    state.trace.append(TraceEvent(agent="hitl", step="resolved", detail={"approve": approve, "note": note}))
    return state


def decide(conn: sqlite3.Connection, row: sqlite3.Row, approve: bool, note: str | None,
           chaos: float = 0.0, payments: PaymentAgent | None = None, amount: float | None = None,
           confirm_large: bool = False, override_amount: bool = False) -> InvoiceState:
    """A person's decision, end to end: record it, then pay (approve) or log the rejection. Used by the
    `review` command and the local review UI (`python main.py ui`), so both write the same tables.

    Decision 21, enforced here and not only in the UI: when the numbers do not add up (or the currency is not
    USD) the person must type the amount to pay. It must equal the computed line sum or the printed total, to the
    cent, unless override_amount is set (recorded in the audit log); a non-USD amount always needs override_amount.
    Any approval paying over $10,000 needs confirm_large too."""
    pay_amount = None
    if approve:
        st = InvoiceState.model_validate_json(row["state_json"])
        if (row["reason"] or "").startswith("PAYMENT_UNCERTAIN:"):
            raise ValueError("The bank outcome is uncertain; reconcile it before any further payment")
        amt = st.total_usd if st.total_usd is not None else (st.invoice.total if st.invoice else None)
        if st.invoice is None or not st.invoice.items or not amt or amt <= 0:
            raise ValueError("No payable amount was read from this file, so it cannot be approved and paid as read; "
                             "reject it, or enter the invoice by hand")
        errs = st.pipeline_errors()
        if errs:
            raise ValueError(f"A step failed on this invoice ({errs[0]}), so its checks are incomplete; it cannot be "
                             "approved and paid. Re-run the file after the fix, or reject it")
        need = amount_entry_reason(st)
        if amount is not None and (not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0):
            raise ValueError(f"The amount to pay must be a number above zero, not {amount!r}")
        if need and amount is None:
            calc = computed_amount(st)
            raise ValueError(f"Not paid: {need}. Type the amount to pay"
                             + (f" (the lines add up to ${calc:,.2f})" if calc else "") + " and approve again")
        if need and amount is not None and not override_amount:
            inv = st.invoice
            if (inv.currency or "USD") != "USD":
                raise ValueError(f"Not paid: the invoice is in {inv.currency}; a typed USD amount needs the override "
                                 "amount flag (tick 'override amount', or pass --override-amount)")
            allowed = [x for x in (computed_amount(st), inv.total) if x is not None]
            if not any(abs(amount - x) < 0.005 for x in allowed):
                raise ValueError(f"Not paid: the amount typed (${amount:,.2f}) is neither the line sum nor the printed "
                                 "total (" + " or ".join(f"${x:,.2f}" for x in allowed) + "); to pay a different "
                                 "amount, tick 'override amount' (or pass --override-amount)")
        if not need and amount is not None and abs(amount - amt) > 0.005:
            raise ValueError(f"Not paid: the amount typed (${amount:,.2f}) is not the invoice total (${amt:,.2f})")
        pay_amount = round(amount if amount is not None else amt, 2)
        if not math.isfinite(pay_amount) or pay_amount <= 0:
            raise ValueError("The amount to pay must be at least one cent")
        if pay_amount > CONFIRM_OVER and not confirm_large:
            raise ValueError(f"Not paid: ${pay_amount:,.2f} is over ${CONFIRM_OVER:,.0f}, so it needs a second, "
                             "explicit confirmation (tick the confirm box, or pass --confirm-large)")
    state = resolve(conn, row, approve, note, pay_amount=pay_amount)
    if state.decision is not None and state.decision.status == DecisionStatus.APPROVED:
        if pay_amount is not None and amount is not None:
            state.total_usd = pay_amount
            state.decision.reasons.append(f"Amount to pay typed by the reviewer: ${pay_amount:,.2f}")
            log_audit(conn, state.invoice.number if state.invoice else None, "hitl",
                      "amount_override" if override_amount else "amount_entered",
                      {"amount": pay_amount, "printed_total": state.invoice.total if state.invoice else None,
                       "currency": state.invoice.currency if state.invoice else None,
                       "computed": computed_amount(state), "override_amount": override_amount})
        return (payments or PaymentAgent(conn, chaos=chaos)).pay(state)
    return log_rejection(conn, state)
