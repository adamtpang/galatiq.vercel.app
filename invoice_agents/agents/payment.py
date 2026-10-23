"""Payment agent: pays approved invoices once, logs everything else.

- `mock_payment` is the case's function, unchanged.
- Idempotency: atomically claim a key over (invoice number, vendor, amount, revision)
  before calling the bank. Paid or uncertain attempts cannot be claimed again.
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
from ..validation import fingerprint

AGENT = "payment"


def mock_payment(vendor, amount):
    print(f"Paid {amount} to {vendor}")
    return {"status": "success"}


class BankError(RuntimeError):
    pass


def payment_identity(number: str | None, vendor: str | None) -> tuple[str, str]:
    num, supplier = (re.sub(r"[^a-z0-9]", "", (s or "").lower()) for s in (number, vendor))
    return num, supplier


def idempotency_key(number: str | None, vendor: str | None, amount: float, revision: str | None) -> str:
    num, supplier = payment_identity(number, vendor)
    raw = f"{num}|{supplier}|{amount:.2f}|{revision or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class PaymentAgent:
    def __init__(self, conn: sqlite3.Connection, chaos: float = 0.0, retries: int = 3, base_delay: float = 0.2,
                 seed: int | None = None, sleep: Callable[[float], None] = time.sleep,
                 bank: Callable | None = None):
        self.conn, self.chaos, self.retries, self.base_delay = conn, chaos, retries, base_delay
        # looked up at call time, so a patched or replaced mock_payment is the one called
        self.rng, self.sleep, self.bank = random.Random(seed), sleep, bank or (lambda v, a: mock_payment(v, a))

    def _call_bank(self, vendor: str | None, amount: float) -> tuple[dict, str]:
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
        assert d is not None, "_refuse is only called from pay(), which has checked the decision"
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
                                  reasons=[f"PAYMENT_GUARD: {why}; payment stopped"] + (d.reasons if d else []),
                                  arguments={"decision_before_guard": d.model_dump(mode="json") if d else None})
        state.trace.append(TraceEvent(agent=AGENT, step="guard_refused", detail={"reason": why}))
        return enqueue(self.conn, state, payment_guard=True)

    def pay(self, state: InvoiceState) -> InvoiceState:
        """Common settlement and recovery path for automatic and human approvals."""
        from ..hitl import clear_failed_payment, enqueue_failed_payment
        if state.decision is None or state.decision.status != DecisionStatus.APPROVED or state.invoice is None:
            raise ValueError("pay() called for an invoice that is not APPROVED")
        try:
            result = self._pay(state)
        except Exception as exc:  # storage/claim failures also stay visible for human callers
            self.conn.rollback()
            state.errors.append(f"payment: {type(exc).__name__}: {exc}")
            result = self._hold(state, f"the payment step raised {type(exc).__name__} ({str(exc)[:120]})")
        status = (result.payment or {}).get("status")
        if status in ("failed", "unknown"):
            enqueue_failed_payment(self.conn, result)
        elif status in ("paid", "already_paid"):
            clear_failed_payment(self.conn, result)
        if result.decision is not None and result.decision.status == DecisionStatus.REJECTED:
            # A persisted human rejection may have stopped an otherwise automatic approval.
            if result.decision.decided_by == "human":
                return log_rejection(self.conn, result)
        return result

    def _review_gate(self, state: InvoiceState, amount: float) -> bool:
        """Check persistent authority while holding the same write lock as the payment claim."""
        assert state.invoice is not None and state.decision is not None
        row = self.conn.execute("SELECT * FROM review_queue WHERE fingerprint=?",
                                (fingerprint(state.invoice),)).fetchone()
        if row is None:
            return True
        if row["status"] == "rejected":
            state.decision = Decision(status=DecisionStatus.REJECTED, decided_by="human",
                                      reasons=[row["reviewer_note"] or "Rejected by human reviewer"])
            state.payment = {"status": "not_paid", "reason": "rejected by human reviewer"}
            return False
        stored = InvoiceState.model_validate_json(row["state_json"])
        allowed = row["status"] in ("approved", "paid_on_retry", "paying") or (
            row["status"] == "pending" and (row["reason"] or "").startswith("PAYMENT_FAILED:"))
        authorization = state.decision.arguments.get("review_version")
        if authorization is not None and authorization != row["version"]:
            allowed = False
        if stored.total_usd is not None and round(stored.total_usd, 2) != amount:
            allowed = False
        if allowed:
            if row["status"] == "pending":
                # Claim the review as well as the payment key. A concurrent reviewer must not
                # authorize a different amount while this automatic retry is at the bank.
                self.conn.execute("UPDATE review_queue SET status='paying', version=version+1 WHERE id=?",
                                  (row["id"],))
            return True
        state.decision = Decision(status=DecisionStatus.PENDING_HUMAN, decided_by="payment_guard",
                                  reasons=["The stored review does not authorize this payment; reload the review. "
                                           + (row["reason"] or "")])
        state.payment = {"status": "not_paid", "reason": "review authorization required"}
        return False

    def _other_payment(self, state: InvoiceState, key: str) -> sqlite3.Row | None:
        """Called under the write lock: a revision or changed amount cannot bypass settlement history."""
        assert state.invoice is not None
        identity = payment_identity(state.invoice.number, state.invoice.vendor)
        rows = self.conn.execute(
            "SELECT invoice_number, vendor, idempotency_key, status FROM payments "
            "WHERE status IN ('paid', 'in_progress', 'unknown') AND idempotency_key != ?", (key,))
        return next((r for r in rows if payment_identity(r["invoice_number"], r["vendor"]) == identity), None)

    def _pay(self, state: InvoiceState) -> InvoiceState:
        d, inv = state.decision, state.invoice
        assert d is not None and inv is not None
        errs = state.pipeline_errors()
        if errs:   # a step failed, so the checks may not have run: never pay
            return self._hold(state, f"the invoice has a recorded error ({errs[0]})")
        blocks = [f.code for f in state.flags if f.severity == Severity.BLOCK]
        if blocks and d.decided_by != "human":   # only a person may approve past a blocking flag (escalated rejection)
            return self._hold(state, f"the invoice has blocking flags ({', '.join(blocks)})")
        if d.conditions:
            return self._hold(state, "payment prerequisites require human confirmation: " + "; ".join(d.conditions))
        raw_amount: float | None
        if state.total_usd is not None:
            raw_amount = state.total_usd
        elif (inv.currency or "USD") == "USD":
            raw_amount = inv.total
        else:   # never pay a foreign-currency amount as if it were dollars
            return self._refuse(state, f"{inv.total} {inv.currency} (no USD amount)")
        if not isinstance(raw_amount, (int, float)) or not math.isfinite(raw_amount) or raw_amount <= 0:
            return self._refuse(state, raw_amount)   # last guard: validation should have stopped this already
        amount = round(raw_amount, 2)
        if amount <= 0:
            return self._refuse(state, amount)
        key = idempotency_key(inv.number, inv.vendor, amount, inv.revision)
        # Commit the claim before every bank attempt, including a retry of a failed payment.
        # One SQL statement prevents two connections from both claiming the same key.
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            if not self._review_gate(state, amount):
                return state
            other = self._other_payment(state, key)
            if other is None:
                claim = self.conn.execute(
                    "INSERT INTO payments (invoice_number, vendor, amount, currency, idempotency_key, status) "
                    "VALUES (?,?,?,?,?, 'in_progress') "
                    "ON CONFLICT(idempotency_key) DO UPDATE SET status='in_progress' WHERE payments.status='failed'",
                    (inv.number, inv.vendor, amount, "USD", key))
        if other is not None:
            why = f"another amount or revision of this invoice has bank status {other['status']}; reconcile it with the bank"
            held = self._hold(state, why)
            held.payment = {"status": "unknown", "amount": amount, "idempotency_key": key, "attempts": 0,
                            "conflicting_payment_key": other["idempotency_key"], "errors": [why]}
            return held
        if claim.rowcount != 1:
            row = self.conn.execute("SELECT status FROM payments WHERE idempotency_key=?", (key,)).fetchone()
            if row and row[0] == "paid":
                state.payment = {"status": "already_paid", "amount": amount, "idempotency_key": key, "attempts": 0}
                state.trace.append(TraceEvent(agent=AGENT, step="idempotency_skip", detail=state.payment))
                return state
            # The owner may still be running or may have stopped after money moved.
            status = row[0] if row else "unknown"
            held = self._hold(state, "another payment attempt for this invoice is not confirmed safe to retry "
                                    f"(status {status}); check with the bank before paying again")
            held.payment = {"status": "unknown", "amount": amount, "idempotency_key": key, "attempts": 0}
            return held
        errors: list[str] = []
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
            except Exception as e:  # noqa: BLE001 - review 3: an unexpected bank error; the money may have moved
                self.conn.execute("UPDATE payments SET status='unknown' WHERE idempotency_key=?", (key,))
                self.conn.commit()
                state.errors.append(f"payment: the bank call raised {type(e).__name__}: {e}")
                state.trace.append(TraceEvent(agent=AGENT, step="bank_exception", detail={"error": str(e)}))
                held = self._hold(state, f"the bank call raised {type(e).__name__} ({str(e)[:120]}), so it is not "
                                         "known whether money moved; check with the bank before paying")
                held.payment = {"status": "unknown", "amount": amount, "idempotency_key": key, "attempts": attempt,
                                "errors": errors + [f"attempt {attempt}: {type(e).__name__}: {e}"]}
                return held
        self.conn.execute("UPDATE payments SET status='failed' WHERE idempotency_key=?", (key,))
        self.conn.commit()
        state.payment = {"status": "failed", "amount": amount, "idempotency_key": key,
                         "attempts": self.retries + 1, "errors": errors}
        state.errors.append(f"payment failed after {self.retries + 1} attempts")
        state.trace.append(TraceEvent(agent=AGENT, step="failed", detail=state.payment))
        return state


def log_rejection(conn: sqlite3.Connection, state: InvoiceState) -> InvoiceState:
    """Rejected and superseded invoices are never paid; the reasons go to the audit log."""
    d = state.decision
    inv = state.invoice
    sup = d is not None and d.status == DecisionStatus.SUPERSEDED
    detail = {"source": state.source, "status": d.status.value if d else None, "reasons": d.reasons if d else [], "decided_by": d.decided_by if d else None,
              "blocking_flags": [f.model_dump(mode="json") for f in state.flags if f.severity.value == "block"],
              "memo": (state.memo or {}).get("text")}
    conn.execute("INSERT INTO audit_log (invoice_number, agent, event, detail) VALUES (?,?,?,?)",
                 (inv.number if inv else None, AGENT, "superseded" if sup else "rejected",
                  json.dumps(detail, default=str)))
    conn.commit()
    state.payment = {"status": "not_paid", "reason": "superseded by a revision" if sup else "rejected"}
    state.trace.append(TraceEvent(agent=AGENT, step="rejection_logged", detail={"reasons": detail["reasons"]}))
    return state
