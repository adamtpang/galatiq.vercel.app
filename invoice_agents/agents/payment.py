"""Payment agent: pays approved invoices once, logs everything else.

- `mock_payment` is the case's function, unchanged.
- Idempotency: a key over (invoice number, vendor, amount, revision) is checked in the
  `payments` table before calling the bank. A key already marked paid is never paid again.
- Retries: up to 3 retries with exponential backoff on bank errors.
- Chaos: `chaos=p` makes each bank call fail with probability p (to demo retries).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import random
import re
import sqlite3
import time
from typing import Callable

from ..models import Decision, DecisionStatus, InvoiceState, Severity, TraceEvent

AGENT = "payment"


def mock_payment(vendor, amount):
    print(f"Paid {amount} to {vendor}")
    return {"status": "success"}


class BankError(RuntimeError):
    pass


def idempotency_key(number: str | None, vendor: str | None, amount: float, revision: str | None) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())  # noqa: E731
    raw = f"{norm(number)}|{norm(vendor)}|{amount:.2f}|{revision or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class PaymentAgent:
    def __init__(self, conn: sqlite3.Connection, chaos: float = 0.0, retries: int = 3, base_delay: float = 0.2,
                 seed: int | None = None, sleep: Callable[[float], None] = time.sleep,
                 bank: Callable = mock_payment):
        self.conn, self.chaos, self.retries, self.base_delay = conn, chaos, retries, base_delay
        self.rng, self.sleep, self.bank = random.Random(seed), sleep, bank

    def _call_bank(self, vendor: str, amount: float) -> tuple[dict, str]:
        if self.chaos and self.rng.random() < self.chaos:
            raise BankError("chaos: injected bank timeout")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = self.bank(vendor, amount)
        if not isinstance(res, dict) or res.get("status") != "success":
            raise BankError(f"bank returned {res!r}")
        return res, buf.getvalue().strip()

    def _refuse(self, state: InvoiceState, amount) -> InvoiceState:
        d = state.decision
        d.status, d.decided_by = DecisionStatus.REJECTED, "payment_guard"
        d.reasons = [f"PAYMENT_GUARD: amount {amount!r} is not a finite number above zero; nothing was paid"] + d.reasons
        state.trace.append(TraceEvent(agent=AGENT, step="guard_refused", detail={"amount": repr(amount)}))
        return log_rejection(self.conn, state)

    def _hold(self, state: InvoiceState, why: str) -> InvoiceState:
        """Refuse to pay and send the invoice to a person instead (fail closed)."""
        from ..hitl import enqueue   # local import: hitl imports this module
        d = state.decision
        state.decision = Decision(status=DecisionStatus.PENDING_HUMAN, decided_by="payment_guard",
                                  risk_score=d.risk_score if d else None,
                                  reasons=[f"PAYMENT_GUARD: {why}; nothing was paid"] + (d.reasons if d else []),
                                  arguments={"decision_before_guard": d.model_dump(mode="json") if d else None})
        state.trace.append(TraceEvent(agent=AGENT, step="guard_refused", detail={"reason": why}))
        return enqueue(self.conn, state)

    def pay(self, state: InvoiceState) -> InvoiceState:
        d, inv = state.decision, state.invoice
        if d is None or d.status != DecisionStatus.APPROVED or inv is None:
            raise ValueError("pay() called for an invoice that is not APPROVED")
        errs = state.pipeline_errors()
        if errs:   # a step failed, so the checks may not have run: never pay
            return self._hold(state, f"the invoice has a recorded error ({errs[0]})")
        blocks = [f.code for f in state.flags if f.severity == Severity.BLOCK]
        if blocks and d.decided_by != "human":   # only a person may approve past a blocking flag (escalated rejection)
            return self._hold(state, f"the invoice has blocking flags ({', '.join(blocks)})")
        if state.total_usd is not None:
            raw_amount = state.total_usd
        elif (inv.currency or "USD") == "USD":
            raw_amount = inv.total
        else:   # never pay a foreign-currency amount as if it were dollars
            return self._refuse(state, f"{inv.total} {inv.currency} (no USD amount)")
        if not isinstance(raw_amount, (int, float)) or not math.isfinite(raw_amount) or raw_amount <= 0:
            return self._refuse(state, raw_amount)   # last guard: validation should have stopped this already
        amount = round(raw_amount, 2)
        key = idempotency_key(inv.number, inv.vendor, amount, inv.revision)
        row = self.conn.execute("SELECT status FROM payments WHERE idempotency_key=?", (key,)).fetchone()
        if row and row[0] == "paid":
            state.payment = {"status": "already_paid", "amount": amount, "idempotency_key": key, "attempts": 0}
            state.trace.append(TraceEvent(agent=AGENT, step="idempotency_skip", detail=state.payment))
            return state
        if row and row[0] == "in_progress":
            # an earlier run stopped between calling the bank and recording the result: the bank may have paid.
            # Paying again could pay twice, so a person checks the bank first (fail closed).
            return self._hold(state, "an earlier payment attempt for this invoice never recorded its result "
                                     "(status in_progress); check with the bank before paying again")
        self.conn.execute(
            "INSERT OR IGNORE INTO payments (invoice_number, vendor, amount, currency, idempotency_key, status) "
            "VALUES (?,?,?,?,?, 'in_progress')", (inv.number, inv.vendor, amount, "USD", key))
        self.conn.commit()
        errors = []
        for attempt in range(1, self.retries + 2):
            try:
                res, msg = self._call_bank(inv.vendor, amount)
                self.conn.execute("UPDATE payments SET status='paid' WHERE idempotency_key=?", (key,))
                self.conn.commit()
                state.payment = {"status": "paid", "amount": amount, "currency": "USD", "idempotency_key": key,
                                 "attempts": attempt, "bank": res, "bank_message": msg, "errors": errors}
                state.trace.append(TraceEvent(agent=AGENT, step="paid", detail=state.payment))
                return state
            except BankError as e:
                errors.append(f"attempt {attempt}: {e}")
                state.trace.append(TraceEvent(agent=AGENT, step="bank_error", detail={"attempt": attempt, "error": str(e)}))
                if attempt <= self.retries:
                    self.sleep(self.base_delay * 2 ** (attempt - 1))
        self.conn.execute("UPDATE payments SET status='failed' WHERE idempotency_key=?", (key,))
        self.conn.commit()
        state.payment = {"status": "failed", "amount": amount, "idempotency_key": key,
                         "attempts": self.retries + 1, "errors": errors}
        state.errors.append(f"payment failed after {self.retries + 1} attempts")
        state.trace.append(TraceEvent(agent=AGENT, step="failed", detail=state.payment))
        return state


def log_rejection(conn: sqlite3.Connection, state: InvoiceState) -> InvoiceState:
    """Rejected invoices are never paid; the reasons go to the audit log."""
    d = state.decision
    inv = state.invoice
    detail = {"source": state.source, "reasons": d.reasons if d else [], "decided_by": d.decided_by if d else None,
              "blocking_flags": [f.model_dump(mode="json") for f in state.flags if f.severity.value == "block"],
              "memo": (state.memo or {}).get("text")}
    conn.execute("INSERT INTO audit_log (invoice_number, agent, event, detail) VALUES (?,?,?,?)",
                 (inv.number if inv else None, AGENT, "rejected", json.dumps(detail, default=str)))
    conn.commit()
    state.payment = {"status": "not_paid", "reason": "rejected"}
    state.trace.append(TraceEvent(agent=AGENT, step="rejection_logged", detail={"reasons": detail["reasons"]}))
    return state
