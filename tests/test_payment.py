import pytest

from invoice_agents.agents.payment import PaymentAgent, idempotency_key, log_rejection, mock_payment
from invoice_agents.db import connect, init_db
from invoice_agents.models import Decision, DecisionStatus, Invoice, InvoiceState, LineItem


@pytest.fixture
def conn(tmp_path):
    p = init_db(tmp_path / "pay.db")
    c = connect(p)
    yield c
    c.close()


def approved(status=DecisionStatus.APPROVED, number="INV-9", total=100.0):
    inv = Invoice(number=number, vendor="Widgets Inc.", total=total,
                  items=[LineItem(sku_raw="WidgetA", qty=1, unit_price=total)])
    return InvoiceState(source="t", invoice=inv, total_usd=total,
                        decision=Decision(status=status, reasons=["test"], decided_by="test"))


def test_mock_payment_is_the_case_function(capsys):
    assert mock_payment("V", 1) == {"status": "success"}
    assert capsys.readouterr().out == "Paid 1 to V\n"


def test_pays_once_then_idempotent(conn):
    calls = []
    agent = PaymentAgent(conn, bank=lambda v, a: calls.append((v, a)) or {"status": "success"})
    assert agent.pay(approved()).payment["status"] == "paid"
    assert agent.pay(approved()).payment["status"] == "already_paid"
    assert calls == [("Widgets Inc.", 100.0)]
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1


def test_key_changes_with_amount_and_revision():
    assert idempotency_key("INV-1", "V", 1.0, None) != idempotency_key("INV-1", "V", 2.0, None)
    assert idempotency_key("INV-1", "V", 1.0, None) != idempotency_key("INV-1", "V", 1.0, "R1")


def test_retries_with_backoff_under_chaos(conn):
    sleeps = []
    agent = PaymentAgent(conn, chaos=0.5, seed=3, sleep=sleeps.append, base_delay=0.1)
    st = agent.pay(approved())
    assert st.payment["status"] == "paid" and st.payment["attempts"] > 1
    assert sleeps == [0.1 * 2 ** i for i in range(len(sleeps))]


def test_gives_up_after_three_retries_and_can_resume(conn):
    sleeps = []
    st = PaymentAgent(conn, chaos=1.0, sleep=sleeps.append).pay(approved())
    assert st.payment["status"] == "failed" and st.payment["attempts"] == 4 and len(sleeps) == 3
    assert conn.execute("SELECT status FROM payments").fetchone()[0] == "failed"
    assert PaymentAgent(conn).pay(approved()).payment["status"] == "paid"   # same key, next run succeeds


@pytest.mark.parametrize("status", [DecisionStatus.REJECTED, DecisionStatus.PENDING_HUMAN])
def test_never_pays_unless_approved(conn, status):
    with pytest.raises(ValueError):
        PaymentAgent(conn).pay(approved(status))
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_rejection_is_logged(conn):
    st = log_rejection(conn, approved(DecisionStatus.REJECTED))
    assert st.payment["status"] == "not_paid"
    row = conn.execute("SELECT agent, event FROM audit_log").fetchone()
    assert tuple(row) == ("payment", "rejected")


def test_hitl_queue_roundtrip(conn):
    from invoice_agents import hitl

    st = approved(DecisionStatus.PENDING_HUMAN, number="INV-77")
    hitl.enqueue(conn, st)
    hitl.enqueue(conn, st)                     # re-run does not duplicate
    assert len(hitl.pending(conn)) == 1
    resolved = hitl.resolve(conn, hitl.find(conn, "INV 77"), approve=True, note="checked with vendor")
    assert resolved.decision.decided_by == "human"
    assert PaymentAgent(conn).pay(resolved).payment["status"] == "paid"
    assert hitl.pending(conn) == []
