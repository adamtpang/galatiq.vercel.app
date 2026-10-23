"""Boundary cases found while checking the final submission claims. No live APIs."""
import json
from datetime import date

import pytest

from invoice_agents import hitl
from invoice_agents.agents.approval import approve
from invoice_agents.agents.ingestion import compare_readings, ingest
from invoice_agents.agents.payment import PaymentAgent
from invoice_agents.graph import make_context, run_batch
from invoice_agents.llm import GrokClient
from invoice_agents.models import DecisionStatus
from invoice_agents.normalize import normalize_invoice_number, parse_money
from invoice_agents.parsers.structured import parse_json
from invoice_agents.validation import validate

from .test_agentic import FakeOpenAI, reply

BASE = {
    "invoice_number": "INV-8801", "vendor": "Widgets Inc.",
    "date": "2026-01-01", "due_date": "2026-01-16", "currency": "USD",
    "line_items": [{"item": "WidgetA", "quantity": 2, "unit_price": 250}],
    "subtotal": 500, "total": 500, "tax_amount": 0, "payment_terms": "Net 15",
}


@pytest.mark.parametrize("value", ["INV-2026-001", "INV-2026-002", "A001", "B001"])
def test_compound_and_supplier_identifiers_keep_their_identity(value):
    assert normalize_invoice_number(value) == value


def test_distinct_compound_identifiers_are_not_duplicate_invoices(tmp_path):
    paths = []
    for suffix, qty in [("001", 2), ("002", 3)]:
        path = tmp_path / (suffix + ".json")
        path.write_text(json.dumps(BASE | {"invoice_number": "INV-2026-" + suffix,
                        "line_items": [{"item": "WidgetA", "quantity": qty, "unit_price": 250}],
                        "subtotal": qty * 250, "total": qty * 250}), encoding="utf-8")
        paths.append(path)
    ctx = make_context(db=str(tmp_path / "audit.db"), runs_dir=None)
    try:
        states = run_batch(paths, ctx)
        assert [s.payment["status"] for s in states] == ["paid", "paid"]
        assert [s.invoice.number for s in states] == ["INV-2026-001", "INV-2026-002"]
    finally:
        ctx.conn.close()


@pytest.mark.parametrize("change", [
    {"line_items": [{"item": "WidgetA", "quantity": "(2)", "unit_price": 250}]},
    {"subtotal": "(500.00)", "total": "(500.00)"},
    {"line_items": [{"item": "WidgetA", "quantity": "2e2", "unit_price": 250}]},
    *[{field: "unknown"} for field in ("tax_amount", "shipping", "subtotal", "tax_rate")],
    {"line_items": [{"item": "WidgetA", "quantity": 2, "unit_price": 250, "amount": "unknown"}]},
])
def test_malformed_numeric_fields_never_silently_pay(tmp_path, change):
    path = tmp_path / "invoice.json"
    path.write_text(json.dumps(BASE | change), encoding="utf-8")
    ctx = make_context(db=str(tmp_path / "audit.db"), runs_dir=None)
    try:
        result, = run_batch([path], ctx)
        assert result.decision.status != DecisionStatus.APPROVED
        assert ctx.conn.execute("SELECT count(*) FROM payments").fetchone()[0] == 0
    finally:
        ctx.conn.close()


@pytest.mark.parametrize("value", ["2e2", "500 or 750", "1,2", "USD 500 EUR", "--500"])
def test_numeric_parser_does_not_take_an_arbitrary_substring(value):
    assert parse_money(value) is None


def test_accounting_negative_sign_is_preserved():
    assert parse_money("($500.00)") == -500
    assert parse_money("(2)") == -2


@pytest.mark.parametrize("suffix,body", [
    ("txt", "Vendor: Widgets Inc.\nInvoice Number: INV-8801\nDue Date: 2026-01-16\n"
     "WidgetA qty: 2 unit price: $250.00\nSubtotal: 500\nTax: unknown\nTotal: 500"),
    ("csv", "field,value\nvendor,Widgets Inc.\ninvoice_number,INV-8801\ndue_date,2026-01-16\n"
     "item,WidgetA\nquantity,2\nunit_price,250\nsubtotal,500\ntax,unknown\ntotal,500"),
    ("csv", "invoice number,vendor,due date,item,quantity,unit price\n"
     "INV-8801,Widgets Inc.,2026-01-16,WidgetA,2,250\nSubtotal:,500\nTax:,unknown\nTotal:,500"),
    ("xml", "<invoice><header><vendor>Widgets Inc.</vendor><invoice_number>INV-8801</invoice_number>"
     "<due_date>2026-01-16</due_date></header><line_items><item><name>WidgetA</name><quantity>2</quantity>"
     "<unit_price>250</unit_price></item></line_items><totals><subtotal>500</subtotal>"
     "<tax_amount>unknown</tax_amount><total>500</total></totals></invoice>"),
])
def test_unknown_tax_is_not_zero_in_any_parser(tmp_path, suffix, body):
    path = tmp_path / ("invoice." + suffix)
    path.write_text(body, encoding="utf-8")
    ctx = make_context(db=str(tmp_path / "audit.db"), runs_dir=None)
    try:
        result, = run_batch([path], ctx)
        assert any(f.code == "INVALID_FIELD_TYPE" for f in result.flags)
        assert ctx.conn.execute("SELECT count(*) FROM payments").fetchone()[0] == 0
    finally:
        ctx.conn.close()


@pytest.mark.parametrize("first_outcome", ["unknown", "in_progress", "paid"])
def test_revision_cannot_bypass_an_existing_bank_attempt(tmp_path, first_outcome):
    original = tmp_path / "original.json"
    revised = tmp_path / "revised.json"
    original.write_text(json.dumps(BASE), encoding="utf-8")
    revised.write_text(json.dumps(BASE | {"revision": "R1", "line_items": [
        {"item": "WidgetA", "quantity": 3, "unit_price": 250}], "subtotal": 750, "total": 750}), encoding="utf-8")
    db = str(tmp_path / "audit.db")
    calls = []

    def bank(vendor, amount):
        calls.append(amount)
        if first_outcome == "unknown":
            raise RuntimeError("accepted, reply lost")
        if first_outcome == "in_progress":
            raise KeyboardInterrupt("accepted, process stopped")
        return {"status": "success"}

    ctx = make_context(db=db, runs_dir=None)
    ctx.payments = PaymentAgent(ctx.conn, bank=bank)
    try:
        if first_outcome == "in_progress":
            with pytest.raises(KeyboardInterrupt):
                run_batch([original], ctx)
        else:
            run_batch([original], ctx)
    finally:
        ctx.conn.close()
    ctx = make_context(db=db, runs_dir=None)
    ctx.payments = PaymentAgent(ctx.conn, bank=lambda v, a: calls.append(a) or {"status": "success"})
    try:
        result, = run_batch([revised], ctx)
        assert result.decision.status == DecisionStatus.PENDING_HUMAN
        assert calls == [500]
        # Human review must use the same settlement guard, including after an earlier confirmed payment.
        row = hitl.find(ctx.conn, "INV-8801")
        try:
            hitl.decide(ctx.conn, row, True, "Review revision", payments=ctx.payments)
        except ValueError as exc:
            assert "bank" in str(exc)
        assert calls == [500]
    finally:
        ctx.conn.close()


@pytest.mark.parametrize("field,value", [("currency", "EUR"), ("due_date", "2027-01-16"),
                                         ("date", "2025-01-01"), ("revision", "R1")])
def test_extraction_disagreement_holds_before_payment(tmp_path, inventory, policy, field, value):
    path = tmp_path / "invoice.json"
    path.write_text(json.dumps(BASE), encoding="utf-8")
    reading = BASE | {"items": [{"name": "WidgetA", "qty": 2, "unit_price": 250}], field: value}
    fake = FakeOpenAI([reply(json.dumps(reading))])
    state = ingest(path, inventory, GrokClient(client=fake, sleep=lambda _: None))
    validate(state, inventory, policy)
    approve(state, None, policy)
    assert any(f.code == "EXTRACTION_DISAGREEMENT" for f in state.flags)
    assert state.decision.status == DecisionStatus.PENDING_HUMAN


def test_competing_revision_stops_while_original_is_at_the_bank(tmp_path):
    original, revised = tmp_path / "original.json", tmp_path / "revised.json"
    original.write_text(json.dumps(BASE), encoding="utf-8")
    revised.write_text(json.dumps(BASE | {"revision": "R1", "line_items": [
        {"item": "WidgetA", "quantity": 3, "unit_price": 250}], "subtotal": 750, "total": 750}), encoding="utf-8")
    db = str(tmp_path / "audit.db")
    first = make_context(db=db, runs_dir=None)
    second = make_context(db=db, runs_dir=None)
    calls, competing = [], []

    def bank(vendor, amount):
        calls.append(amount)
        competing.extend(run_batch([revised], second))
        return {"status": "success"}

    first.payments = PaymentAgent(first.conn, bank=bank)
    second.payments = PaymentAgent(second.conn, bank=lambda v, a: calls.append(a) or {"status": "success"})
    try:
        result, = run_batch([original], first)
        assert result.payment["status"] == "paid"
        assert competing[0].decision.status == DecisionStatus.PENDING_HUMAN
        assert calls == [500]
    finally:
        first.conn.close()
        second.conn.close()


def test_cross_check_accepts_equivalent_date_format_and_item_order():
    parsed = parse_json(json.dumps(BASE))
    other = parsed.model_copy(deep=True)
    other.due_date_raw = "Jan 16, 2026"
    other.due_date = date(2026, 1, 16)
    assert compare_readings(parsed, other) == []


def test_cross_check_detects_missing_price_without_sorting_none_against_float():
    parsed = parse_json(json.dumps(BASE | {"line_items": [
        {"item": "WidgetA", "quantity": 1, "unit_price": 250},
        {"item": "WidgetA", "quantity": 1, "unit_price": None}]}))
    other = parsed.model_copy(deep=True)
    other.items[1].unit_price = 250
    assert compare_readings(parsed, other)
