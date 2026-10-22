"""Human-in-the-loop review queue, persisted in SQLite (table review_queue)."""
from __future__ import annotations

import sqlite3

from .models import Decision, DecisionStatus, InvoiceState, TraceEvent
from .validation import fingerprint


def enqueue(conn: sqlite3.Connection, state: InvoiceState) -> InvoiceState:
    inv, d = state.invoice, state.decision
    fp = fingerprint(inv) if inv else state.source
    conn.execute(
        "INSERT INTO review_queue (invoice_number, vendor, source_file, fingerprint, reason, state_json) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET state_json=excluded.state_json, "
        "reason=excluded.reason, source_file=excluded.source_file",
        (inv.number if inv else None, inv.vendor if inv else None, state.source, fp,
         "; ".join(d.reasons) if d else None, state.model_dump_json(exclude={"raw_text"})))
    conn.commit()
    state.payment = {"status": "not_paid", "reason": "pending human review"}
    state.trace.append(TraceEvent(agent="hitl", step="queued", detail={"fingerprint": fp}))
    return state


def pending(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM review_queue WHERE status='pending' ORDER BY id").fetchall()


def find(conn: sqlite3.Connection, invoice_number: str) -> sqlite3.Row | None:
    from .normalize import normalize_invoice_number

    num = normalize_invoice_number(invoice_number)
    return conn.execute("SELECT * FROM review_queue WHERE invoice_number=? AND status='pending' "
                        "ORDER BY id DESC LIMIT 1", (num,)).fetchone()


def resolve(conn: sqlite3.Connection, row: sqlite3.Row, approve: bool, note: str | None) -> InvoiceState:
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
    conn.commit()
    state.trace.append(TraceEvent(agent="hitl", step="resolved", detail={"approve": approve, "note": note}))
    return state
