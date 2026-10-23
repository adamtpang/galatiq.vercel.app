"""Every sample file parses deterministically (offline) into the expected fields."""
from datetime import date

import pytest

from invoice_agents.normalize import fix_ocr_digits, normalize_sku, parse_date, parse_money
from invoice_agents.parsers import parse_file

from .conftest import INVOICES

# file: (number, revision, vendor, total, currency, n_items, due_date or raw due)
GOLDEN = {
    "invoice_1001.txt": ("INV-1001", None, "Widgets Inc.", 5000.00, "USD", 2, date(2026, 2, 1)),
    "invoice_1002.txt": ("INV-1002", None, "Gadgets Co.", 15000.00, "USD", 1, date(2026, 1, 30)),
    "invoice_1003.txt": ("INV-1003", None, "Fraudster LLC", 100000.00, "USD", 1, "yesterday"),
    "invoice_1004.json": ("INV-1004", None, "Precision Parts Ltd.", 1890.00, "USD", 2, date(2026, 2, 22)),
    "invoice_1004_revised.json": ("INV-1004", "R1", "Precision Parts Ltd.", 5940.00, "USD", 3, date(2026, 2, 22)),
    "invoice_1005.json": ("INV-1005", None, "Global Supply Chain Partners", 15225.00, "USD", 3, date(2026, 3, 18)),
    "invoice_1006.csv": ("INV-1006", None, "Acme Industrial Supplies", 2750.00, "USD", 2, date(2026, 2, 10)),
    "invoice_1007.csv": ("INV-1007", None, "MegaWidgets Corp", 15525.00, "USD", 3, date(2026, 2, 28)),
    "invoice_1008.txt": ("INV-1008", None, "NoProd Industries", 9900.00, "USD", 2, date(2026, 1, 20)),
    "invoice_1009.json": ("INV-1009", None, None, -250.00, "USD", 2, None),
    "invoice_1010.txt": ("INV-1010", None, "Consolidated Materials Group", 7185.00, "USD", 4, date(2026, 2, 26)),
    "invoice_1011.pdf": ("INV-1011", None, "Summit Manufacturing Co.", 3000.00, "USD", 2, date(2026, 2, 20)),
    "invoice_1011.txt": ("INV-1011", None, "Summit Manufacturing Co.", 3000.00, "USD", 2, date(2026, 2, 20)),
    "invoice_1012.pdf": ("INV-1012", None, "QuickShip Distributers", 9975.00, "USD", 3, date(2026, 2, 25)),
    "invoice_1012.txt": ("INV-1012", None, "QuickShip Distributers", 9975.00, "USD", 3, date(2026, 2, 25)),
    "invoice_1013.json": ("INV-1013", None, "Atlas Industrial Supply", 22562.80, "USD", 8, date(2026, 3, 24)),
    "invoice_1013.pdf": ("INV-1013", None, "Atlas Industrial Supply", 22562.80, "USD", 8, date(2026, 3, 24)),
    "invoice_1014.xml": ("INV-1014", None, "TechParts International", 4125.00, "EUR", 2, date(2026, 2, 26)),
    "invoice_1015.csv": ("INV-1015", None, "Reliable Components Inc.", 6500.00, "USD", 3, date(2026, 2, 28)),
    "invoice_1016.json": ("INV-1016", None, "Widgets Inc.", 3233.00, "USD", 3, date(2026, 2, 27)),
}


def test_golden_covers_every_sample():
    assert sorted(GOLDEN) == sorted(p.name for p in INVOICES.iterdir() if p.suffix != ".py")
    assert len(GOLDEN) == 20


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_parse_sample(name):
    number, revision, vendor, total, currency, n_items, due = GOLDEN[name]
    inv = parse_file(INVOICES / name)
    assert inv.number == number
    assert inv.revision == revision
    assert inv.vendor == vendor
    assert inv.total == pytest.approx(total)
    assert inv.currency == currency
    assert len(inv.items) == n_items
    if isinstance(due, str):
        assert inv.due_date is None and inv.due_date_raw == due
    else:
        assert inv.due_date == due
    assert all(li.unit_price is not None for li in inv.items)


def test_text_and_pdf_copies_agree():
    for n in ("1011", "1012"):
        a, b = parse_file(INVOICES / f"invoice_{n}.txt"), parse_file(INVOICES / f"invoice_{n}.pdf")
        assert [(i.sku_raw, i.qty, i.unit_price) for i in a.items] == [(i.sku_raw, i.qty, i.unit_price) for i in b.items]
    j, p = parse_file(INVOICES / "invoice_1013.json"), parse_file(INVOICES / "invoice_1013.pdf")
    assert [(i.sku_raw, i.qty, i.unit_price, i.note) for i in j.items] == [(i.sku_raw, i.qty, i.unit_price, i.note) for i in p.items]


def test_typo_labels_1002():
    inv = parse_file(INVOICES / "invoice_1002.txt")
    assert inv.terms == "Net 30" and inv.date == date(2026, 1, 30)
    assert inv.items[0].sku_raw == "GadgetX" and inv.items[0].qty == 20


def test_email_sender_is_not_vendor_1008():
    assert parse_file(INVOICES / "invoice_1008.txt").vendor == "NoProd Industries"


def test_ocr_and_rename_1012():
    inv = parse_file(INVOICES / "invoice_1012.txt")
    assert inv.date == date(2026, 1, 26)          # "26-Jan-2O26"
    assert inv.items[1].amount == 3500.00          # "$3,500.O0"
    assert inv.vendor_former_name == "FastShip Ltd."
    assert inv.tax_rate == pytest.approx(0.05)


def test_csv_footer_rows_1007():
    inv = parse_file(INVOICES / "invoice_1007.csv")
    assert (inv.subtotal, inv.tax, inv.tax_rate) == (14750.0, 885.0, 0.06)


def test_tax_and_shipping_1010():
    inv = parse_file(INVOICES / "invoice_1010.txt")
    assert (inv.subtotal, inv.tax, inv.shipping) == (6700.0, 335.0, 150.0)
    assert inv.items[3].sku_raw == "WidgetA (rush order)"


@pytest.mark.parametrize("raw,expected", [
    ("2026-01-15", date(2026, 1, 15)), ("Jan 30 2026", date(2026, 1, 30)),
    ("January 27, 2026", date(2026, 1, 27)), ("26-Jan-2O26", date(2026, 1, 26)),
    ("01/28/2026", date(2026, 1, 28)),
])
def test_parse_date(raw, expected):
    assert parse_date(raw).value == expected


def test_relative_date_is_not_a_date():
    r = parse_date("yesterday")
    assert r.value is None and r.status == "relative"


def test_money_and_ocr():
    assert parse_money("$3,500.O0") == 3500.0
    assert parse_money("-250.00") == -250.0
    assert fix_ocr_digits("Ltd. Office")[0] == "Ltd. Office"   # words are left alone


@pytest.mark.parametrize("raw,sku,method", [
    ("WidgetA", "WidgetA", "exact"), ("Widget A", "WidgetA", "case_spacing"),
    ("Gadget X", "GadgetX", "case_spacing"), ("WidgetA (rush order)", "WidgetA", "stripped_note"),
    ("W1dgetA", "WidgetA", "ocr_lookalike"), ("WidgetC", None, "unknown"), ("SuperGizmo", None, "unknown"),
])
def test_sku_normalizer(raw, sku, method):
    m = normalize_sku(raw, ["WidgetA", "WidgetB", "GadgetX", "FakeItem"])
    assert (m.sku, m.method) == (sku, method)


def test_edge_files_are_rejected_not_crashing(tmp_path, inventory, policy):
    from invoice_agents.agents.ingestion import ingest
    from invoice_agents.file_io import MAX_BYTES
    from invoice_agents.validation import validate
    (tmp_path / "empty.txt").write_text("")
    (tmp_path / "lunch.txt").write_text("Lunch is at noon on Friday.\n")
    (tmp_path / "broken.pdf").write_text("%PDF-1.4 garbage")
    with open(tmp_path / "huge.txt", "wb") as fh:
        fh.truncate(MAX_BYTES + 1)
    for name, code in (("empty.txt", "EXTRACTION_FAILED"), ("lunch.txt", "MISSING_ITEMS"),
                       ("broken.pdf", "EXTRACTION_FAILED"), ("huge.txt", "EXTRACTION_FAILED")):
        st = validate(ingest(tmp_path / name, inventory), inventory, policy)
        assert code in {f.code for f in st.flags} and st.has_blocking(), name
