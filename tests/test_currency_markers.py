"""Currency markers and trailing notes on amounts: USD markers are read, foreign markers are never read as dollars
and the invoice is held for a person, and a note such as "(exempt)" does not hide the number."""
from pathlib import Path

import pytest

from invoice_agents.models import DecisionStatus
from invoice_agents.normalize import foreign_currency_marker, parse_money
from invoice_agents.db import init_db
from invoice_agents.graph import make_context, run_batch

from .conftest import INVOICES

BASE = (INVOICES / "invoice_1001.txt").read_text()


@pytest.mark.parametrize("text, value", [
    ("$5,000.00 USD", 5000.0), ("USD 5,000.00", 5000.0), ("US$ 5,000.00", 5000.0), ("5,000.00 usd", 5000.0),
    ("$0.00 (exempt)", 0.0), ("(500.00)", -500.0), ("($500.00)", -500.0), ("-$250.00", -250.0)])
def test_usd_markers_and_notes_are_read(text, value):
    assert parse_money(text) == value and foreign_currency_marker(text) is None


@pytest.mark.parametrize("text", ["A$500.00", "CA$500.00", "R$500.00", "€500.00", "EUR 4,125.00", "500.00 GBP"])
def test_foreign_markers_are_never_read_as_dollars(text):
    assert parse_money(text) is None and foreign_currency_marker(text)


@pytest.mark.parametrize("text", ["2e2", "1,234.56*", "USD", "(exempt)"])
def test_strictness_is_kept(text):
    assert parse_money(text) is None


def _run(tmp_path: Path, name: str, text: str):
    f = tmp_path / name
    f.write_text(text)
    ctx = make_context(db=str(init_db(tmp_path / "t.db")), runs_dir=None, cache=False, base_delay=0,
                       sleep=lambda s: None)
    (state,) = run_batch([f], ctx)
    return state


@pytest.mark.parametrize("old, new", [
    ("Total Amount: $5,000.00", "Total Amount: $5,000.00 USD"),
    ("Total Amount: $5,000.00", "Total Amount: USD 5,000.00"),
    ("Tax (0%): $0.00", "Tax (0%): $0.00 (exempt)")])
def test_copies_of_1001_with_usd_markers_are_paid(tmp_path, old, new):
    assert old in BASE
    st = _run(tmp_path, "invoice_7001.txt", BASE.replace(old, new).replace("INV-1001", "INV-7001"))
    assert st.decision.status == DecisionStatus.APPROVED and st.payment["status"] == "paid"
    assert st.payment["amount"] == 5000.0


FOREIGN = """INVOICE

Invoice Number: INV-C{n}
Vendor: Summit Manufacturing Co.
Date: 2026-01-20
Due Date: 2026-02-20

Item                Qty     Unit Price      Amount
--------------------------------------------------
WidgetA              2       {m}250.00       {m}500.00
--------------------------------------------------
                              Total:       {m}500.00

Payment Terms: Net 30
"""


@pytest.mark.parametrize("n, marker", [(4124, "A$"), (434124, "CA$"), (5224, "R$")])
def test_dollar_variants_are_held_not_rejected(tmp_path, n, marker):
    st = _run(tmp_path, f"n_cur_{n}.txt", FOREIGN.format(n=n, m=marker))
    assert st.decision.status == DecisionStatus.PENDING_HUMAN and st.payment["status"] == "not_paid"
    assert "FOREIGN_CURRENCY_MARKER" in {f.code for f in st.flags}


def test_dollar_variant_holds_even_when_a_usd_total_is_read(tmp_path):
    text = BASE.replace("unit price: $250.00", "unit price: A$250.00").replace("INV-1001", "INV-7011")
    st = _run(tmp_path, "invoice_7011.txt", text)
    assert st.decision.status != DecisionStatus.APPROVED and st.payment["status"] == "not_paid"
