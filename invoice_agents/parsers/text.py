"""Parser for plain-text invoices, email bodies and text extracted from PDFs.

Strategy: fix OCR digit artifacts, split each line into segments on runs of 3+ spaces,
read "label: value" segments using a synonym table that tolerates the typos in the
samples ("Vndr", "Dt", "Amt", "Pymnt Terms"), and read item rows with one regex that
covers the "qty: N unit price: $X", "qty N @ $X ea", "xN $X each" and table layouts.
"""
from __future__ import annotations

import re

from ..models import Invoice
from ..normalize import fix_ocr_digits, parse_money
from .common import finish, item

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


def parse_text(text: str, source: str | None = None, fmt: str = "txt") -> Invoice:
    fixed, corrections = fix_ocr_digits(text)
    inv = Invoice(source_file=source, source_format=fmt, corrections=corrections)
    found: dict[str, str] = {}
    tax_rate_raw = None
    lines = fixed.splitlines()
    pending: str | None = None  # label seen with its value in the next segment
    notes_open = False
    notes: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            notes_open = False
            pending = None
            continue

        row = _ROW.match(line)
        if row and not re.match(r"^\s*(sub ?total|total|tax|shipping|amt)\b", line, re.I):
            name = re.sub(r"\s+qty$", "", row.group("name"), flags=re.I)
            note = row.group("note")
            inv.items.append(item(name, row.group("qty"), row.group("price"), row.group("amount"), note))
            notes_open = False
            continue

        if notes_open and ":" not in stripped:
            notes.append(stripped)
            continue
        notes_open = False

        m_former = re.search(r"\(formerly\s+([^)]+)\)", stripped, re.I)
        if m_former:
            inv.vendor_former_name = m_former.group(1).strip()

        if pending:
            found.setdefault(pending, stripped)
            pending = None
            continue
        matches = list(_LABEL_RE.finditer(stripped))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(stripped)
            field = _field_for(m.group("label"))
            value = stripped[m.end():end].strip()
            if field == "tax" and m.group("paren"):
                tax_rate_raw = m.group("paren")
            if field == "vendor" and _EMAIL.search(value or ""):
                continue  # "From: billing@x.biz" is a sender address, not the vendor name
            if field == "notes":
                notes.append(value)
                notes_open = True
                continue
            if value == "":
                pending = field
            elif field not in found:
                found[field] = value

    if "number" not in found:
        m = re.search(r"\bINV(?:OICE)?\s*(?:#|NO\.?|NUMBER)?\s*[:#]?\s*(INV[- ]?\d{3,}|\d{3,})", fixed, re.I)
        if m:
            found["number"] = m.group(1)

    inv.vendor = found.get("vendor")
    inv.subtotal = parse_money(found.get("subtotal"))
    inv.tax = parse_money(found.get("tax"))
    inv.shipping = parse_money(found.get("shipping"))
    inv.total = parse_money(found.get("total"))
    inv.terms = found.get("terms")
    if found.get("currency"):
        inv.currency = found["currency"].strip().upper()
    if tax_rate_raw:
        r = parse_money(tax_rate_raw.replace("%", ""))
        inv.tax_rate = r / 100 if r is not None else None
    inv.notes = " ".join(notes) or None
    for k in ("vendor", "number", "date", "due", "total", "subtotal", "tax", "terms"):
        inv.field_confidence[k] = 1.0 if k in found else 0.0
    return finish(inv, number=found.get("number"), date_raw=found.get("date"), due_raw=found.get("due"))
