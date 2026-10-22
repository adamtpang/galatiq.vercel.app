"""One test per flag code with a minimal fixture, plus the expected codes for each sample."""
import sqlite3
from datetime import date

import pytest

from invoice_agents.agents.ingestion import ingest, resolve_skus
from invoice_agents.db import init_db
from invoice_agents.models import Invoice, InvoiceState, LineItem, Severity
from invoice_agents.pipeline import collect, run_files
from invoice_agents.validation import DuplicateRegistry, validate

from .conftest import INVOICES


def mk(**kw) -> Invoice:
    base = dict(number="INV-1", vendor="Widgets Inc.", date=date(2026, 1, 1), date_raw="2026-01-01",
                due_date=date(2026, 1, 31), due_date_raw="2026-01-31", terms="Net 30",
                items=[LineItem(sku_raw="WidgetA", qty=2, unit_price=250.0)], subtotal=500.0, tax=0.0, total=500.0)
    base.update(kw)
    return Invoice(**base)


def run(inv, inventory, policy, registry=None):
    resolve_skus(inv, inventory)
    st = validate(InvoiceState(source="t", invoice=inv), inventory, policy, registry)
    return {f.code: f for f in st.flags}, st


def test_clean_invoice_has_no_flags(inventory, policy):
    flags, st = run(mk(), inventory, policy)
    assert flags == {} and st.total_usd == 500.0


@pytest.mark.parametrize("kw,code,sev", [
    (dict(vendor=""), "MISSING_VENDOR", Severity.BLOCK),
    (dict(number=None), "MISSING_INVOICE_NUMBER", Severity.WARN),
    (dict(items=[], subtotal=None), "MISSING_ITEMS", Severity.BLOCK),
    (dict(total=None), "MISSING_TOTAL", Severity.BLOCK),
    (dict(due_date=None, due_date_raw=None), "MISSING_DUE_DATE", Severity.WARN),
    (dict(due_date=None, due_date_raw="yesterday"), "INVALID_DUE_DATE", Severity.BLOCK),
    (dict(due_date=date(2025, 12, 1), due_date_raw="2025-12-01", terms=None), "DUE_BEFORE_ISSUE", Severity.WARN),
    (dict(terms="Net 60"), "TERMS_MISMATCH", Severity.INFO),
])
def test_field_and_date_flags(inventory, policy, kw, code, sev):
    flags, _ = run(mk(**kw), inventory, policy)
    assert code in flags and flags[code].severity == sev


def test_unknown_item(inventory, policy):
    flags, _ = run(mk(items=[LineItem(sku_raw="WidgetC", qty=1, unit_price=350.0)], subtotal=350.0, total=350.0),
                   inventory, policy)
    assert flags["UNKNOWN_ITEM"].severity == Severity.BLOCK
    assert flags["UNKNOWN_ITEM"].evidence["item"] == "WidgetC"


def test_zero_stock(inventory, policy):
    flags, _ = run(mk(items=[LineItem(sku_raw="FakeItem", qty=1, unit_price=10.0)], subtotal=10.0, total=10.0),
                   inventory, policy)
    assert flags["ZERO_STOCK"].severity == Severity.BLOCK
    assert "STOCK_EXCEEDED" not in flags


def test_stock_exceeded_aggregates_lines(inventory, policy):
    items = [LineItem(sku_raw="GadgetX", qty=3, unit_price=750.0), LineItem(sku_raw="Gadget X", qty=3, unit_price=750.0)]
    flags, _ = run(mk(items=items, subtotal=4500.0, total=4500.0), inventory, policy)
    f = flags["STOCK_EXCEEDED"]
    assert f.severity == Severity.BLOCK          # DECISIONS.md #1: over-stock is a reject
    assert {k: f.evidence[k] for k in ("item", "requested", "stock")} == {"item": "GadgetX", "requested": 6, "stock": 5}


def test_within_stock_after_aggregation_is_info(inventory, policy):
    items = [LineItem(sku_raw="WidgetA", qty=8, unit_price=250.0), LineItem(sku_raw="WidgetA", qty=4, unit_price=250.0)]
    flags, _ = run(mk(items=items, subtotal=3000.0, total=3000.0), inventory, policy)
    assert "STOCK_EXCEEDED" not in flags and flags["LINES_AGGREGATED"].severity == Severity.INFO


def test_negative_qty_and_total(inventory, policy):
    flags, _ = run(mk(items=[LineItem(sku_raw="WidgetA", qty=-1, unit_price=250.0)], subtotal=-250.0, total=-250.0),
                   inventory, policy)
    assert flags["NEGATIVE_QTY"].severity == Severity.BLOCK and flags["NEGATIVE_TOTAL"].severity == Severity.BLOCK


def test_zero_qty(inventory, policy):
    flags, _ = run(mk(items=[LineItem(sku_raw="WidgetA", qty=0, unit_price=250.0)], subtotal=0.0, total=0.0),
                   inventory, policy)
    assert flags["ZERO_QTY"].severity == Severity.WARN


def test_line_subtotal_total_tax_mismatch(inventory, policy):
    items = [LineItem(sku_raw="WidgetA", qty=2, unit_price=250.0, amount=600.0)]
    flags, _ = run(mk(items=items, subtotal=500.0, tax=10.0, tax_rate=0.05, total=520.0), inventory, policy)
    assert {"LINE_AMOUNT_MISMATCH", "SUBTOTAL_MISMATCH", "TAX_MISMATCH", "TOTAL_MISMATCH"} <= set(flags)


def test_math_tolerance(inventory, policy):
    flags, _ = run(mk(total=500.009), inventory, policy)
    assert "TOTAL_MISMATCH" not in flags


def test_price_variance(inventory, policy):
    flags, _ = run(mk(items=[LineItem(sku_raw="WidgetA", qty=1, unit_price=300.0)], subtotal=300.0, total=300.0),
                   inventory, policy)
    assert flags["PRICE_VARIANCE"].severity == Severity.WARN and flags["PRICE_VARIANCE"].evidence["pct"] == 20.0
    flags, _ = run(mk(items=[LineItem(sku_raw="WidgetA", qty=1, unit_price=200.0)], subtotal=200.0, total=200.0),
                   inventory, policy)
    assert flags["PRICE_VARIANCE"].severity == Severity.INFO


def test_currency(inventory, policy):
    flags, st = run(mk(currency="EUR"), inventory, policy)
    assert flags["CURRENCY_CONVERTED"].severity == Severity.WARN and st.total_usd == 540.0
    flags, _ = run(mk(currency="JPY"), inventory, policy)
    assert flags["UNSUPPORTED_CURRENCY"].severity == Severity.BLOCK


def test_currency_written_in_the_text(inventory, policy):
    """Amounts written with another currency get an accurate, blocking reason (not 'no line items')."""
    def flags_for(raw, **kw):
        inv = mk(**kw)
        resolve_skus(inv, inventory)
        st = validate(InvoiceState(source="t", invoice=inv, raw_text=raw), inventory, policy)
        return [f.code for f in st.flags], st
    codes, st = flags_for("WidgetA qty: 2 unit price: \u00a5250.00\nTotal: \u00a5500.00", items=[], total=None, subtotal=None)
    assert codes[0] == "UNSUPPORTED_CURRENCY" and "MISSING_ITEMS" in codes and st.total_usd is None
    assert "JPY (\u00a5)" in st.flags[0].message
    codes, _ = flags_for("Total: 500.00 EUR")                      # code next to an amount, invoice read as USD
    assert codes == ["UNSUPPORTED_CURRENCY"]
    codes, _ = flags_for("Total: 500.00 EUR", currency="EUR")      # consistent with the currency field: converted
    assert "CURRENCY_CONVERTED" in codes and "UNSUPPORTED_CURRENCY" not in codes
    codes, _ = flags_for("Total: $500.00\nCurrency: GBP", currency="GBP")
    assert "CURRENCY_CONVERTED" in codes and "UNSUPPORTED_CURRENCY" not in codes
    codes, _ = flags_for("Shipped from our Euro warehouse. Total: $500.00")
    assert codes == []


def test_past_due_is_a_warning_that_does_not_decide(inventory, policy, monkeypatch):
    from invoice_agents.agents import approval as ap
    from invoice_agents.agents.risk import assess
    monkeypatch.setenv("INVOICE_AS_OF", "2026-02-10")
    flags, st = run(mk(), inventory, policy)                        # due 2026-01-31
    assert flags["PAST_DUE"].severity == Severity.WARN and flags["PAST_DUE"].evidence["days_past_due"] == 10
    st = ap.approve(assess(st, policy, None), None, policy)
    assert st.decision.status.value == "APPROVED"                  # same outcome as without the flag
    assert "PAST_DUE" not in {f["code"] for f in ap.facts(st, policy)["flags"]}
    monkeypatch.setenv("INVOICE_AS_OF", "2026-01-31")
    flags, _ = run(mk(), inventory, policy)
    assert "PAST_DUE" not in flags                                 # due today is not past due


def test_sample_charged(inventory, policy):
    flags, _ = run(mk(items=[LineItem(sku_raw="WidgetA", qty=2, unit_price=250.0, note="Sample")]), inventory, policy)
    assert flags["SAMPLE_CHARGED"].severity == Severity.WARN


def test_vendor_flags(inventory, policy):
    assert "UNKNOWN_VENDOR" in run(mk(vendor="Nobody LLC"), inventory, policy)[0]
    assert "VENDOR_NAME_LOOKALIKE" in run(mk(vendor="Acme Industrial Supplies"), inventory, policy)[0]
    f = run(mk(vendor="QuickShip", vendor_former_name="FastShip Ltd."), inventory, policy)[0]["VENDOR_RENAMED"]
    assert f.evidence["former_on_file"] is True


def test_vendor_not_approved(tmp_path, policy):
    from invoice_agents.db import Inventory, connect
    p = init_db(tmp_path / "x.db")
    with sqlite3.connect(p) as c:
        c.execute("UPDATE vendors SET approved=0 WHERE name='Widgets Inc.'")
    with connect(p) as c:
        inv = Inventory(c)
    assert run(mk(), inv, policy)[0]["VENDOR_NOT_APPROVED"].severity == Severity.BLOCK


def test_thresholds(inventory, policy):
    big = [LineItem(sku_raw="WidgetA", qty=1, unit_price=12000.0)]
    assert "OVER_APPROVAL_THRESHOLD" in run(mk(items=big, subtotal=12000.0, total=12000.0), inventory, policy)[0]
    near = [LineItem(sku_raw="WidgetA", qty=1, unit_price=9600.0)]
    assert "NEAR_APPROVAL_THRESHOLD" in run(mk(items=near, subtotal=9600.0, total=9600.0), inventory, policy)[0]


def test_duplicates_and_revisions(inventory, policy):
    reg = DuplicateRegistry()
    a, st_a = run(mk(source_file="a.txt"), inventory, policy, reg)
    b, _ = run(mk(source_file="b.pdf"), inventory, policy, reg)
    assert "DUPLICATE_INVOICE" in b
    c, _ = run(mk(source_file="c.json", revision="R1", total=700.0, subtotal=700.0,
                  items=[LineItem(sku_raw="WidgetA", qty=2, unit_price=350.0)]), inventory, policy, reg)
    assert c["REVISION_SUPERSEDES"].evidence["delta"] == 200.0
    assert any(f.code == "SUPERSEDED_BY_REVISION" for f in st_a.flags)
    d, _ = run(mk(source_file="d.json", total=999.0), inventory, policy, reg)
    assert "DUPLICATE_NUMBER_CONFLICT" in d


def test_content_duplicate_under_new_number(inventory, policy):
    # decision 7: same vendor, items, quantities and total as an earlier invoice, different number
    reg = DuplicateRegistry()
    run(mk(source_file="a.txt"), inventory, policy, reg)
    b, _ = run(mk(source_file="b.txt", number="INV-9999"), inventory, policy, reg)
    f = b["DUPLICATE_INVOICE"]
    assert f.severity.value == "block" and f.evidence["match"] == "content" and f.evidence["original_invoice"]
    c, _ = run(mk(source_file="c.txt", number="INV-9998", total=999.0), inventory, policy, reg)
    assert "DUPLICATE_INVOICE" not in c                       # different total: not a duplicate
    d, _ = run(mk(source_file="d.txt", number="INV-9997", vendor="Gadgets Co."), inventory, policy, reg)
    assert "DUPLICATE_INVOICE" not in d                       # different vendor: not a duplicate


def test_content_duplicate_can_be_turned_off(inventory, policy):
    pol = dict(policy, duplicates={"match_content": False})
    reg = DuplicateRegistry()
    run(mk(source_file="a.txt"), inventory, pol, reg)
    b, _ = run(mk(source_file="b.txt", number="INV-9999"), inventory, pol, reg)
    assert "DUPLICATE_INVOICE" not in b


def test_extraction_failed(tmp_path, inventory, policy):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json")
    st = validate(ingest(bad, inventory), inventory, policy)
    assert st.flags[0].code == "EXTRACTION_FAILED" and st.extraction_mode == "failed"


def test_init_db_is_idempotent(tmp_path):
    p = tmp_path / "i.db"
    init_db(p)
    init_db(p)
    with sqlite3.connect(p) as c:
        assert dict(c.execute("SELECT item, stock FROM inventory")) == {"WidgetA": 15, "WidgetB": 10, "GadgetX": 5, "FakeItem": 0}
        assert c.execute("SELECT COUNT(*) FROM vendors").fetchone()[0] == 11
        with pytest.raises(sqlite3.IntegrityError):
            c.executemany("INSERT INTO payments (invoice_number, vendor, amount, idempotency_key, status) "
                          "VALUES ('x','v',1,'k','paid')", [(), ()])


# Expected codes per sample when the whole folder runs as one batch (sorted order).
EXPECTED = {
    "invoice_1001.txt": {"TERMS_MISMATCH"},
    "invoice_1002.txt": {"STOCK_EXCEEDED", "TERMS_MISMATCH", "OVER_APPROVAL_THRESHOLD"},
    "invoice_1003.txt": {"ZERO_STOCK", "INVALID_DUE_DATE", "UNKNOWN_VENDOR", "OVER_APPROVAL_THRESHOLD"},
    "invoice_1004.json": {"SUPERSEDED_BY_REVISION"},
    "invoice_1004_revised.json": {"REVISION_SUPERSEDES"},
    "invoice_1005.json": {"STOCK_EXCEEDED", "UNKNOWN_VENDOR", "OVER_APPROVAL_THRESHOLD"},
    "invoice_1006.csv": {"VENDOR_NAME_LOOKALIKE"},
    "invoice_1007.csv": {"STOCK_EXCEEDED", "TOTAL_MISMATCH", "OVER_APPROVAL_THRESHOLD"},
    "invoice_1008.txt": {"UNKNOWN_ITEM", "UNKNOWN_VENDOR", "NEAR_APPROVAL_THRESHOLD"},
    "invoice_1009.json": {"MISSING_VENDOR", "MISSING_DUE_DATE", "NEGATIVE_QTY", "NEGATIVE_TOTAL",
                          "SUBTOTAL_MISMATCH", "TOTAL_MISMATCH"},
    "invoice_1010.txt": {"SKU_NORMALIZED", "LINES_AGGREGATED", "PRICE_VARIANCE"},
    "invoice_1011.pdf": set(),
    "invoice_1011.txt": {"DUPLICATE_INVOICE"},
    "invoice_1012.pdf": {"SKU_NORMALIZED", "VENDOR_RENAMED", "NEAR_APPROVAL_THRESHOLD", "OCR_CORRECTED"},
    "invoice_1012.txt": {"SKU_NORMALIZED", "VENDOR_RENAMED", "NEAR_APPROVAL_THRESHOLD", "OCR_CORRECTED",
                         "DUPLICATE_INVOICE"},
    "invoice_1013.json": {"STOCK_EXCEEDED", "TOTAL_MISMATCH", "SAMPLE_CHARGED", "OVER_APPROVAL_THRESHOLD"},
    "invoice_1013.pdf": {"STOCK_EXCEEDED", "TOTAL_MISMATCH", "SAMPLE_CHARGED", "OVER_APPROVAL_THRESHOLD",
                         "DUPLICATE_INVOICE"},
    "invoice_1014.xml": {"CURRENCY_CONVERTED"},
    "invoice_1015.csv": set(),
    "invoice_1016.json": {"UNKNOWN_ITEM"},
}


@pytest.fixture(scope="module")
def batch(db_file):
    return {s.source.split("/")[-1]: s for s in run_files(collect(INVOICES), db=str(db_file))}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_sample_flags(batch, name):
    assert {f.code for f in batch[name].flags} == EXPECTED[name]


def test_stock_exceeded_evidence_1013(batch):
    ev = {f.evidence["item"]: (f.evidence["requested"], f.evidence["stock"])
          for f in batch["invoice_1013.json"].flags if f.code == "STOCK_EXCEEDED"}
    assert ev == {"WidgetA": (22, 15), "WidgetB": (18, 10), "GadgetX": (9, 5)}


def test_1014_converted_to_usd(batch):
    assert batch["invoice_1014.xml"].total_usd == pytest.approx(4455.0)
