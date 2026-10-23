"""Helpers shared by the format parsers."""
from __future__ import annotations

from ..models import Invoice, LineItem
from ..normalize import normalize_invoice_number, parse_date, parse_money


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


def item(name, qty, price=None, amount=None, note=None) -> LineItem:
    q = parse_money(qty)
    return LineItem(
        sku_raw=str(name).strip(),
        qty=q if q is not None else 0.0,
        unit_price=parse_money(price),
        amount=parse_money(amount),
        note=(str(note).strip() or None) if note else None,
    )
