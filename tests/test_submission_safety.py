"""Regressions for the submission audit, using only local databases and mock banks."""
from pathlib import Path

import pytest

from invoice_agents import ROOT, hitl
from invoice_agents.agents.approval import OfflineVP, VPOpinion
from invoice_agents.agents.payment import PaymentAgent
from invoice_agents.db import connect
from invoice_agents.graph import make_context, run_batch
from invoice_agents.models import DecisionStatus

INVOICES = ROOT / "data" / "invoices"


def context(tmp_path, **kwargs):
    return make_context(db=str(tmp_path / "audit.db"), runs_dir=None, base_delay=0, sleep=lambda _: None, **kwargs)


def test_human_rejection_survives_automatic_rerun(tmp_path):
    ctx = context(tmp_path, chaos=1)
    run_batch([INVOICES / "invoice_1001.txt"], ctx)
    hitl.decide(ctx.conn, hitl.pending(ctx.conn)[0], False, "Do not pay")
    ctx.conn.close()
    ctx = context(tmp_path)
    result, = run_batch([INVOICES / "invoice_1001.txt"], ctx)
    assert result.decision.status == DecisionStatus.REJECTED
    assert ctx.conn.execute("SELECT count(*) FROM payments WHERE status='paid'").fetchone()[0] == 0
    ctx.conn.close()


@pytest.mark.parametrize("outcome", ["failed", "unknown"])
def test_human_payment_failure_stays_visible(tmp_path, outcome):
    ctx = context(tmp_path)
    run_batch([INVOICES / "invoice_1010.txt"], ctx)

    def bank(vendor, amount):
        raise RuntimeError("response lost after submission")

    agent = PaymentAgent(ctx.conn, retries=0, chaos=1 if outcome == "failed" else 0, bank=bank)
    result = hitl.decide(ctx.conn, hitl.pending(ctx.conn)[0], True, "Checked PO", payments=agent)
    rows = hitl.pending(ctx.conn)
    assert result.payment["status"] == outcome
    assert len(rows) == 1
    assert hitl.queued_state(rows[0]).payment["status"] == outcome
    if outcome == "unknown":
        with pytest.raises(ValueError, match="reconcil|bank"):
            hitl.decide(ctx.conn, rows[0], True, "Try again")
    else:
        retried = hitl.decide(ctx.conn, rows[0], True, "Retry")
        assert retried.payment["status"] == "paid"
        assert not hitl.pending(ctx.conn)
    ctx.conn.close()


@pytest.mark.parametrize("first_approve", [True, False])
def test_stale_review_cannot_change_a_decision_or_pay_another_amount(tmp_path, first_approve):
    ctx = context(tmp_path)
    run_batch([INVOICES / "invoice_1014.xml"], ctx)
    first = hitl.pending(ctx.conn)[0]
    other = connect(tmp_path / "audit.db")
    stale = hitl.find_id(other, first["id"])
    hitl.decide(ctx.conn, first, first_approve, "Reviewer A", amount=1000, override_amount=True)
    with pytest.raises(ValueError, match="changed|stale|resolved"):
        hitl.decide(other, stale, True, "Reviewer B", amount=1100, override_amount=True)
    assert ctx.conn.execute("SELECT count(*) FROM payments WHERE status='paid'").fetchone()[0] == int(first_approve)
    other.close()
    ctx.conn.close()


def test_conditions_are_prerequisites_not_automatic_payment_authorization(tmp_path, monkeypatch):
    monkeypatch.setattr(OfflineVP, "propose", lambda *args: VPOpinion(
        decision="approve", reasons=["Only after verification"],
        conditions=["Do not pay until the purchase order is verified"]))
    ctx = context(tmp_path)
    result, = run_batch([INVOICES / "invoice_1001.txt"], ctx)
    assert result.decision.status == DecisionStatus.PENDING_HUMAN
    assert ctx.conn.execute("SELECT count(*) FROM payments").fetchone()[0] == 0
    assert hitl.pending(ctx.conn)
    result = hitl.decide(ctx.conn, hitl.pending(ctx.conn)[0], True, "Purchase order verified")
    assert result.payment["status"] == "paid"
    assert result.decision.conditions == []
    assert result.decision.arguments["resolved_conditions"]
    ctx.conn.close()


def test_uncertain_human_payment_survives_rerun_and_amount_changes(tmp_path):
    ctx = context(tmp_path)
    calls = []

    def bank(vendor, amount):
        calls.append(amount)
        raise RuntimeError("response lost")

    run_batch([INVOICES / "invoice_1014.xml"], ctx)
    hitl.decide(ctx.conn, hitl.pending(ctx.conn)[0], True, "Treasury checked", amount=1000,
                override_amount=True, payments=PaymentAgent(ctx.conn, bank=bank))
    ctx.conn.close()
    ctx = context(tmp_path)
    result, = run_batch([INVOICES / "invoice_1014.xml"], ctx)
    row = hitl.pending(ctx.conn)[0]
    assert row["reason"].startswith("PAYMENT_UNCERTAIN:")
    assert result.payment["status"] == "unknown" and result.total_usd == 1000
    with pytest.raises(ValueError, match="bank"):
        hitl.decide(ctx.conn, row, True, "Retry at new rate", amount=1100, override_amount=True)
    assert calls == [1000]
    ctx.conn.close()


def test_stale_review_cannot_claim_reopened_failed_payment(tmp_path):
    ctx = context(tmp_path)
    run_batch([INVOICES / "invoice_1014.xml"], ctx)
    stale = hitl.pending(ctx.conn)[0]
    hitl.decide(ctx.conn, stale, True, "First", amount=1000, override_amount=True,
                payments=PaymentAgent(ctx.conn, chaos=1, retries=0))
    current = hitl.pending(ctx.conn)[0]
    assert current["version"] > stale["version"]
    assert hitl.queued_state(current).total_usd == 1000
    with pytest.raises(ValueError, match="changed"):
        hitl.decide(ctx.conn, stale, True, "Stale", amount=1100, override_amount=True)
    assert not ctx.conn.execute("SELECT 1 FROM payments WHERE status='paid'").fetchone()
    ctx.conn.close()


def test_subcent_amount_cannot_be_paid(tmp_path):
    from tests.test_payment import approved
    ctx = context(tmp_path)
    calls = []
    result = PaymentAgent(ctx.conn, bank=lambda v, a: calls.append(a)).pay(approved(total=0.004))
    assert calls == []
    assert result.decision.status == DecisionStatus.REJECTED
    ctx.conn.close()


@pytest.mark.parametrize("suffix", [".txt", ".pdf"])
def test_oversize_input_is_not_read_by_prescan_or_cache(tmp_path, monkeypatch, suffix):
    from invoice_agents import cache
    from invoice_agents import file_io
    monkeypatch.setattr(file_io, "MAX_BYTES", 10)
    source = tmp_path / ("large" + suffix)
    source.write_text("INVOICE " * 5)
    original = Path.open

    def guarded_open(path, *args, **kwargs):
        if path == source:
            pytest.fail("oversize input was opened")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(OSError, match="limit"):
        cache.normalized_content(source)
    ctx = context(tmp_path)
    result, = run_batch([source], ctx)
    assert result.decision.status != DecisionStatus.APPROVED
    assert any("limit" in err for err in result.errors)
    ctx.conn.close()


def test_concurrent_reviewers_claim_only_one_amount(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    ctx = context(tmp_path)
    run_batch([INVOICES / "invoice_1014.xml"], ctx)
    other = connect(tmp_path / "audit.db")
    rows = [hitl.pending(conn)[0] for conn in (ctx.conn, other)]
    barrier = Barrier(2)
    calls = []

    def decide(conn, row, amount):
        barrier.wait(timeout=10)
        try:
            agent = PaymentAgent(conn, bank=lambda v, a: calls.append(a) or {"status": "success"})
            return hitl.decide(conn, row, True, "Checked", amount=amount, override_amount=True,
                               payments=agent).payment["status"]
        except ValueError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(decide, ctx.conn, rows[0], 1000)
        second = pool.submit(decide, other, rows[1], 1100)
        assert sorted([first.result(timeout=15), second.result(timeout=15)]) == ["paid", "stale"]
    assert len(calls) == 1
    other.close()
    ctx.conn.close()


def test_review_migration_preserves_pending_invoice(tmp_path):
    ctx = context(tmp_path)
    run_batch([INVOICES / "invoice_1014.xml"], ctx)
    ctx.conn.execute("ALTER TABLE review_queue DROP COLUMN version")
    ctx.conn.commit()
    ctx.conn.close()
    conn = connect(tmp_path / "audit.db")
    row = hitl.pending(conn)[0]
    assert row["version"] == 0 and row["invoice_number"] == "INV-1014"
    result = hitl.decide(conn, row, True, "Checked", amount=1000, override_amount=True)
    assert result.payment["status"] == "paid"
    conn.close()


def test_automatic_retry_claim_prevents_competing_human_amount(tmp_path):
    from tests.test_payment import approved
    ctx = context(tmp_path)
    state = approved()
    state.invoice.currency = "EUR"  # a human override would otherwise allow a different USD amount
    PaymentAgent(ctx.conn, chaos=1, retries=0).pay(state)
    other = connect(tmp_path / "audit.db")
    stale = hitl.pending(other)[0]

    def bank(vendor, amount):
        with pytest.raises(ValueError, match="changed"):
            hitl.decide(other, stale, True, "Competing review", amount=110, override_amount=True)
        return {"status": "success"}

    result = PaymentAgent(ctx.conn, bank=bank).pay(approved().model_copy(update={"invoice": state.invoice}))
    assert result.payment["status"] == "paid"
    assert ctx.conn.execute("SELECT count(*) FROM payments WHERE status='paid'").fetchone()[0] == 1
    other.close()
    ctx.conn.close()
