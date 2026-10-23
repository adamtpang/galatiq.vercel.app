"""Human-in-the-loop review queue, persisted in SQLite (table review_queue)."""
from __future__ import annotations

import sqlite3

from .agents.payment import PaymentAgent, log_rejection
from .db import log_audit
from .models import Decision, DecisionStatus, InvoiceState, TraceEvent
from .normalize import normalize_invoice_number
from .validation import document_id, fingerprint, local_stamp

HUMAN = {"approved": DecisionStatus.APPROVED, "rejected": DecisionStatus.REJECTED}


def enqueue(conn: sqlite3.Connection, state: InvoiceState) -> InvoiceState:
    """Queue a held invoice for a person. If a person already decided this invoice in an earlier
    run, that decision stands (re-running a file is idempotent): nothing is queued again."""
    inv, d = state.invoice, state.decision
    fp = fingerprint(inv) if inv else state.source
    prev = conn.execute("SELECT status, reviewer_note, datetime(decided_at, 'localtime') FROM review_queue "
                        "WHERE fingerprint=?", (fp,)).fetchone()
    if prev is not None and prev[0] in HUMAN:
        status, note, at = prev[0], prev[1], prev[2]
        state.decision = Decision(
            status=HUMAN[status], decided_by="human", risk_score=d.risk_score if d else None,
            reasons=[f"Already {status} by a human reviewer on {local_stamp(at)}" + (f": {note}" if note else "")],
            arguments={"agents_decision": d.model_dump(mode="json") if d else None})
        paid = status == "approved" and conn.execute(
            "SELECT 1 FROM payments WHERE invoice_number IS ? AND vendor IS ? AND status='paid'",
            (inv.number if inv else None, inv.vendor if inv else None)).fetchone()
        state.payment = ({"status": "already_paid", "amount": state.total_usd} if paid
                         else {"status": "not_paid", "reason": f"{status} by a human reviewer"})
        state.trace.append(TraceEvent(agent="hitl", step="already_reviewed",
                                      detail={"fingerprint": fp, "review": status, "note": note, "decided_at": at}))
        return state
    conn.execute(
        "INSERT INTO review_queue (invoice_number, vendor, source_file, fingerprint, reason, state_json) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET state_json=excluded.state_json, "
        "reason=excluded.reason, source_file=excluded.source_file",
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
    """An approved invoice whose payment failed after every retry goes to the review queue (PAYMENT_FAILED), so a
    person sees it; approving it there retries the payment (idempotent). A later successful run clears it."""
    inv, p = state.invoice, state.payment or {}
    fp = fingerprint(inv) if inv else state.source
    reason = (f"PAYMENT_FAILED: approved, but the bank call failed after {p.get('attempts')} attempts "
              f"({'; '.join(p.get('errors', [])[-1:])}); approve to retry the payment, or reject")
    conn.execute(
        "INSERT INTO review_queue (invoice_number, vendor, source_file, fingerprint, reason, state_json) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET state_json=excluded.state_json, "
        "reason=excluded.reason, source_file=excluded.source_file, status='pending', decided_at=NULL",
        (inv.number if inv else None, inv.vendor if inv else None, state.source, fp, reason,
         state.model_dump_json(exclude={"raw_text"})))
    conn.commit()
    state.trace.append(TraceEvent(agent="hitl", step="queued_payment_failed", detail={"fingerprint": fp}))


def clear_failed_payment(conn: sqlite3.Connection, state: InvoiceState) -> None:
    """A paid invoice no longer needs its PAYMENT_FAILED queue entry."""
    if state.invoice is None:
        return
    cur = conn.execute("UPDATE review_queue SET status='paid_on_retry', decided_at=datetime('now') "
                       "WHERE fingerprint=? AND status='pending' AND reason LIKE 'PAYMENT_FAILED:%'",
                       (fingerprint(state.invoice),))
    if cur.rowcount:
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


def resolve(conn: sqlite3.Connection, row: sqlite3.Row, approve: bool, note: str | None) -> InvoiceState:
    """Record a person's decision on a queued invoice: review_queue, the invoices history and the audit log.
    The caller pays (approve) or logs the rejection."""
    state = InvoiceState.model_validate_json(row["state_json"])
    prior = state.decision
    state.decision = Decision(
        status=DecisionStatus.APPROVED if approve else DecisionStatus.REJECTED,
        reasons=[note or ("Approved by human reviewer" if approve else "Rejected by human reviewer")],
        conditions=prior.conditions if (prior and approve) else [],
        risk_score=prior.risk_score if prior else None,
        critique_rounds=prior.critique_rounds if prior else 0,
        decided_by="human", arguments={"queued_reason": row["reason"]})
    conn.execute("UPDATE review_queue SET status=?, reviewer_note=?, decided_at=datetime('now') WHERE id=?",
                 ("approved" if approve else "rejected", note, row["id"]))
    if state.invoice is not None:
        conn.execute("UPDATE invoices SET status=? WHERE fingerprint=?",
                     (state.decision.status.value, document_id(state.invoice, state.source)))
    conn.commit()
    log_audit(conn, state.invoice.number if state.invoice else None, "hitl",
              "human_approved" if approve else "human_rejected",
              {"source": state.source, "note": note, "queued_reason": row["reason"]})
    state.trace.append(TraceEvent(agent="hitl", step="resolved", detail={"approve": approve, "note": note}))
    return state


def decide(conn: sqlite3.Connection, row: sqlite3.Row, approve: bool, note: str | None,
           chaos: float = 0.0, payments: PaymentAgent | None = None) -> InvoiceState:
    """A person's decision, end to end: record it, then pay (approve) or log the rejection. Used by the
    `review` command and the local review UI (`python main.py ui`), so both write the same tables."""
    if approve:
        st = InvoiceState.model_validate_json(row["state_json"])
        amt = st.total_usd if st.total_usd is not None else (st.invoice.total if st.invoice else None)
        if st.invoice is None or not st.invoice.items or not amt or amt <= 0:
            raise ValueError("No payable amount was read from this file, so it cannot be approved and paid as read; "
                             "reject it, or enter the invoice by hand")
        errs = st.pipeline_errors()
        if errs:
            raise ValueError(f"A step failed on this invoice ({errs[0]}), so its checks are incomplete; it cannot be "
                             "approved and paid. Re-run the file after the fix, or reject it")
    state = resolve(conn, row, approve, note)
    if state.decision.status == DecisionStatus.APPROVED:
        return (payments or PaymentAgent(conn, chaos=chaos)).pay(state)
    return log_rejection(conn, state)
