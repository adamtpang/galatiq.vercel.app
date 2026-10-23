"""Helpers shared by the format parsers."""
from __future__ import annotations

from ..models import Invoice, LineItem
from ..normalize import foreign_currency_marker, normalize_invoice_number, parse_date, parse_money


def free_text(value) -> str | None:
    """Notes, terms and addresses as text whatever JSON type they arrive in: a list is joined, an object is
    written as "key: value" pairs, a number is written out. None and empty stay None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = [f"{k}: {free_text(v) or ''}".strip() for k, v in value.items()]
    elif isinstance(value, (list, tuple, set)):
        parts = [free_text(v) or "" for v in value]
    else:
        parts = [str(value)]
    out = " ".join(p for p in parts if p).strip()
    return out or None


def scalar(value, field: str, errors: list[str]):
    """A field that must be one number or one name (invoice number, vendor, date, quantity, price, total).
    A list, an object or true/false is recorded in `errors` (a blocking INVALID_FIELD_TYPE flag) and read as None."""
    if value is None or (isinstance(value, (str, int, float)) and not isinstance(value, bool)):
        return value
    errors.append(f"{field}: expected a number or text, got {type(value).__name__} {str(value)[:60]!r}")
    return None


def number(value, field: str, errors: list[str]) -> float | None:
    """Keep absent numeric fields distinct from present but unreadable values."""
    value = scalar(value, field, errors)
    parsed = parse_money(value)
    # A foreign amount (A$, EUR, ...) is not a type error: it stays unread, and validation routes the invoice.
    if value is not None and str(value).strip() and parsed is None and not foreign_currency_marker(value):
        errors.append(f"{field}: expected a number, got {str(value)[:40]!r}")
    return parsed


def finish(inv: Invoice, *, number=None, date_raw=None, due_raw=None) -> Invoice:
    """Normalize number and dates, fill line amounts. Never invents totals."""
    if number is not None:
        inv.number = normalize_invoice_number(number)
        if inv.number and str(number).strip() != inv.number:
            inv.corrections.append(f"invoice number '{str(number).strip()}' -> '{inv.number}'")
    d = parse_date(date_raw)
    inv.date, inv.date_raw = d.value, d.raw
    if d.corrected:
        inv.corrections.append(f"date '{d.raw}' -> '{d.corrected}'")
    dd = parse_date(due_raw)
    inv.due_date, inv.due_date_raw = dd.value, dd.raw
    if dd.corrected:
        inv.corrections.append(f"due date '{dd.raw}' -> '{dd.corrected}'")
    inv.currency = (inv.currency or "").strip().upper() or "USD"   # ' usd ' -> 'USD'
    if inv.vendor is not None:
        inv.vendor = inv.vendor.strip() or None
    if inv.terms is not None:
        inv.terms = inv.terms.strip() or None
    if inv.tax is None and inv.tax_rate is not None and inv.subtotal is not None:
        pass  # leave missing; validation reports what is actually printed
    return inv


def item(name, qty, price=None, amount=None, note=None, errors: list[str] | None = None, line: int | None = None) -> LineItem:
    errors = errors if errors is not None else []
    q = number(qty, f"line {line or '?'} quantity", errors)
    return LineItem(
        sku_raw=str(name).strip(),
        qty=q if q is not None else 0.0,
        unit_price=number(price, f"line {line or '?'} unit_price", errors),
        amount=number(amount, f"line {line or '?'} amount", errors),
        note=(str(note).strip() or None) if note else None,
    )
