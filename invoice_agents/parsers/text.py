"""Parser for plain-text invoices, email bodies and text extracted from PDFs.

Strategy: fix OCR digit artifacts, split each line into segments on runs of 3+ spaces,
read "label: value" segments using a synonym table that tolerates the typos in the
samples ("Vndr", "Dt", "Amt", "Pymnt Terms"), and read item rows with one regex that
covers the "qty: N unit price: $X", "qty N @ $X ea", "xN $X each" and table layouts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Invoice
from ..normalize import fix_ocr_digits
from .common import finish, item, number

LABELS: dict[str, list[str]] = {
    "vendor": ["vendor", "vndr", "supplier", "from", "seller", "remit to"],
    "number": ["invoice number", "invoice no", "invoice #", "inv #", "inv no", "inv number", "invoice"],
    "date": ["date", "dt", "invoice date", "issue date"],
    "due": ["due date", "due dt", "due", "payment due"],
    "subtotal": ["subtotal", "sub total", "sub-total"],
    "tax": ["tax", "sales tax", "vat"],
    "shipping": ["shipping", "freight", "delivery"],
    "total": ["total amount", "total", "grand total", "amount due", "amt", "total due", "balance due"],
    "terms": ["payment terms", "pymnt terms", "terms"],
    "notes": ["notes", "note", "memo"],
    "currency": ["currency"],
}
_LOOKUP = {syn: field for field, syns in LABELS.items() for syn in syns}

_LABEL_RE = re.compile(
    r"(?<!\S)(?P<label>" + "|".join(re.escape(x).replace(r"\ ", r"\s+") for x in sorted(_LOOKUP, key=len, reverse=True))
    + r")\s*(?:\((?P<paren>[^)]*)\))?\s*:",
    re.I,
)
_ROW = re.compile(
    r"^\s*(?:[-*\u2022]\s*)?"
    r"(?P<name>[A-Za-z][\w\-]*(?: [\w\-]+)*(?: \([^)]*\))?)"
    r"\s+(?:qty:?\s*|x(?=\d))?(?P<qty>-?\d+(?:\.\d+)?)"
    r"\s+(?:unit price:\s*|@\s*|rate:\s*)?(?P<price>-?\$\s?[\d,]+(?:\.\d+)?|-?[\d,]+\.\d{2})"
    r"(?:\s*(?:ea|each))?"
    r"(?:\s+(?P<amount>-?\$?\s?[\d,]+\.\d{2}))?"
    r"(?:\s+(?P<note>[A-Za-z][^$]*?))?\s*$",
    re.I,
)
_EMAIL = re.compile(r"\S+@\S+")


def _field_for(label: str) -> str | None:
    key = re.sub(r"\s+", " ", label.strip().lower())
    return _LOOKUP.get(key)


_TOTAL_LINE = re.compile(r"^\s*(sub ?total|total|tax|shipping|amt)\b", re.I)
_FORMER = re.compile(r"\(formerly\s+([^)]+)\)", re.I)
_NUMBER_FALLBACK = re.compile(r"\bINV(?:OICE)?\s*(?:#|NO\.?|NUMBER)?\s*[:#]?\s*(INV[- ]?\d{3,}|\d{3,})", re.I)


@dataclass
class _Scan:
    """What one pass over the lines collects."""
    found: dict[str, str] = field(default_factory=dict)   # field -> first value seen
    notes: list[str] = field(default_factory=list)
    tax_rate_raw: str | None = None
    pending: str | None = None      # label seen with its value on the next line
    notes_open: bool = False        # inside a multi-line "Notes:" block


def _item_row(line: str):
    """An item row ("WidgetA  qty: 10  unit price: $250.00", table rows, ...), or None.
    Total, tax and shipping lines look like rows but are not items."""
    row = _ROW.match(line)
    if row and not _TOTAL_LINE.match(line):
        name = re.sub(r"\s+qty$", "", row.group("name"), flags=re.I)
        return item(name, row.group("qty"), row.group("price"), row.group("amount"), row.group("note"))
    return None


def _read_labels(stripped: str, scan: _Scan) -> None:
    """Read every "label: value" segment on one line into scan.found (first value wins)."""
    matches = list(_LABEL_RE.finditer(stripped))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(stripped)
        name = _field_for(m.group("label"))
        if name is None:
            continue
        value = stripped[m.end():end].strip()
        if name == "tax" and m.group("paren"):
            scan.tax_rate_raw = m.group("paren")
        if name == "vendor" and _EMAIL.search(value or ""):
            continue  # "From: billing@x.biz" is a sender address, not the vendor name
        if name == "notes":
            scan.notes.append(value)
            scan.notes_open = True
            continue
        if value == "":
            scan.pending = name
        elif name not in scan.found:
            scan.found[name] = value


def _scan_line(line: str, inv: Invoice, scan: _Scan) -> None:
    stripped = line.strip()
    if not stripped:                       # a blank line ends a notes block and a pending label
        scan.notes_open = False
        scan.pending = None
        return
    it = _item_row(line)
    if it is not None:
        inv.items.append(it)
        scan.notes_open = False
        return
    if scan.notes_open and ":" not in stripped:   # continuation of a notes block
        scan.notes.append(stripped)
        return
    scan.notes_open = False
    m_former = _FORMER.search(stripped)
    if m_former:
        inv.vendor_former_name = m_former.group(1).strip()
    if scan.pending:                       # value of the label on the previous line
        scan.found.setdefault(scan.pending, stripped)
        scan.pending = None
        return
    _read_labels(stripped, scan)


def _apply_fields(inv: Invoice, scan: _Scan) -> None:
    found = scan.found
    inv.vendor = found.get("vendor")
    inv.subtotal = number(found.get("subtotal"), "subtotal", inv.type_errors)
    inv.tax = number(found.get("tax"), "tax", inv.type_errors)
    inv.shipping = number(found.get("shipping"), "shipping", inv.type_errors)
    inv.total = number(found.get("total"), "total", inv.type_errors)
    inv.terms = found.get("terms")
    if found.get("currency"):
        inv.currency = found["currency"].strip().upper()
    if scan.tax_rate_raw:
        r = number(scan.tax_rate_raw.replace("%", ""), "tax_rate", inv.type_errors)
        inv.tax_rate = r / 100 if r is not None else None
    inv.notes = " ".join(scan.notes) or None
    for k in ("vendor", "number", "date", "due", "total", "subtotal", "tax", "terms"):
        inv.field_confidence[k] = 1.0 if k in found else 0.0


def parse_text(text: str, source: str | None = None, fmt: str = "txt") -> Invoice:
    fixed, corrections = fix_ocr_digits(text)
    inv = Invoice(source_file=source, source_format=fmt, corrections=corrections)
    scan = _Scan()
    for line in fixed.splitlines():
        _scan_line(line, inv, scan)
    if "number" not in scan.found:         # "INVOICE #1009" style header without a label
        m = _NUMBER_FALLBACK.search(fixed)
        if m:
            scan.found["number"] = m.group(1)
    _apply_fields(inv, scan)
    f = scan.found
    return finish(inv, number=f.get("number"), date_raw=f.get("date"), due_raw=f.get("due"))
