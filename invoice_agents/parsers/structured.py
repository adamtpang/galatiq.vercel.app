"""Parsers for JSON, CSV (key-value and tabular shapes) and XML invoices."""
from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET

from ..models import Invoice
from ..normalize import parse_money
from .common import finish, free_text, item, scalar


def _first(d: dict, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def parse_json(text: str, source: str | None = None) -> Invoice:
    """JSON invoice. Every value is type-checked before it is used: notes, terms and addresses become text
    whatever their JSON type; a list, object or true/false where a number or name belongs is a type error
    (blocking INVALID_FIELD_TYPE in validation), never silently read as something else."""
    d = json.loads(text)
    if not isinstance(d, dict):
        raise ValueError(f"expected a JSON object, got {type(d).__name__}")
    errs: list[str] = []
    inv = Invoice(source_file=source, source_format="json")
    vendor = d.get("vendor")
    if isinstance(vendor, dict):
        inv.vendor = _name(scalar(vendor.get("name"), "vendor.name", errs))
        inv.vendor_address = free_text(vendor.get("address"))
    else:
        inv.vendor = _name(scalar(vendor, "vendor", errs))
    inv.revision = _name(scalar(d.get("revision"), "revision", errs))
    inv.currency = (_name(scalar(d.get("currency"), "currency", errs)) or "USD").upper()
    lines = d.get("line_items") or d.get("items") or []
    if not isinstance(lines, list):
        errs.append(f"line_items: expected a list, got {type(lines).__name__}")
        lines = []
    for n, li in enumerate(lines, 1):
        if not isinstance(li, dict):
            errs.append(f"line {n}: expected an object, got {type(li).__name__}")
            continue
        name = _first(li, "item", "name", "sku", "description")
        inv.items.append(item(_name(scalar(name, f"line {n} item", errs)) or "",
                              scalar(_first(li, "quantity", "qty"), f"line {n} quantity", errs),
                              scalar(_first(li, "unit_price", "price", "rate"), f"line {n} unit_price", errs),
                              scalar(li.get("amount"), f"line {n} amount", errs), free_text(li.get("note")),
                              errs, n))
    inv.subtotal = parse_money(scalar(d.get("subtotal"), "subtotal", errs))
    inv.tax = parse_money(scalar(_first(d, "tax_amount", "tax"), "tax", errs))
    inv.tax_rate = parse_money(scalar(d.get("tax_rate"), "tax_rate", errs))
    inv.shipping = parse_money(scalar(d.get("shipping"), "shipping", errs))
    total = scalar(d.get("total"), "total", errs)
    inv.total = parse_money(total)
    inv.terms = free_text(d.get("payment_terms") or d.get("terms"))
    inv.notes = free_text(d.get("notes"))
    number = scalar(_first(d, "invoice_number", "number", "id"), "invoice_number", errs)
    date_raw = _name(scalar(d.get("date"), "date", errs))
    due_raw = _name(scalar(d.get("due_date"), "due_date", errs))
    for k, v in {"vendor": inv.vendor, "number": number, "due": due_raw, "total": total}.items():
        inv.field_confidence[k] = 1.0 if v not in (None, "") else 0.0
    inv.type_errors = errs
    return finish(inv, number=number, date_raw=date_raw, due_raw=due_raw)


def _name(v) -> str | None:
    """A scalar that passed `scalar` as text (an invoice number or vendor printed as a bare number is fine)."""
    return None if v is None else str(v)


def parse_csv(text: str, source: str | None = None) -> Invoice:
    rows = [r for r in csv.reader(io.StringIO(text.strip())) if any(c.strip() for c in r)]
    header = [h.strip().lower() for h in rows[0]]
    if header[:2] == ["field", "value"]:
        return _csv_key_value(rows[1:], source)
    return _csv_table(header, rows[1:], source)


def _csv_key_value(rows, source) -> Invoice:
    """field,value pairs; line items repeat as item/quantity/unit_price groups."""
    inv = Invoice(source_file=source, source_format="csv")
    kv: dict[str, str] = {}
    cur: dict[str, str] = {}
    for r in rows:
        k, v = r[0].strip().lower(), (r[1].strip() if len(r) > 1 else "")
        if k in ("item", "name", "sku"):
            if cur:
                inv.items.append(item(cur.get("item", ""), cur.get("quantity"), cur.get("unit_price"), cur.get("amount")))
            cur = {"item": v}
        elif k in ("quantity", "qty", "unit_price", "price", "amount") and cur is not None and "item" in cur:
            cur[{"qty": "quantity", "price": "unit_price"}.get(k, k)] = v
        else:
            kv.setdefault(k, v)
    if cur:
        inv.items.append(item(cur.get("item", ""), cur.get("quantity"), cur.get("unit_price"), cur.get("amount")))
    inv.vendor = kv.get("vendor")
    inv.subtotal, inv.tax = parse_money(kv.get("subtotal")), parse_money(kv.get("tax"))
    inv.shipping, inv.total = parse_money(kv.get("shipping")), parse_money(kv.get("total"))
    inv.terms = kv.get("payment_terms")
    inv.currency = (kv.get("currency") or "USD").upper()
    return finish(inv, number=kv.get("invoice_number"), date_raw=kv.get("date"), due_raw=kv.get("due_date"))


def _csv_table(header, rows, source) -> Invoice:
    """One row per line item; trailing rows carry "Subtotal:", "Tax (6%):", "Total:" labels."""
    inv = Invoice(source_file=source, source_format="csv")
    col = {h: i for i, h in enumerate(header)}

    def get(r, *names):
        for n in names:
            if n in col and col[n] < len(r) and r[col[n]].strip():
                return r[col[n]].strip()
        return None

    meta: dict[str, str] = {}
    errs: list[str] = []
    for r in rows:
        name = get(r, "item", "description", "sku")
        if name:
            for k in ("invoice number", "vendor", "date", "due date", "currency", "payment terms"):
                if get(r, k) and k not in meta:
                    meta[k] = get(r, k)
            inv.items.append(item(name, get(r, "qty", "quantity"), get(r, "unit price", "price"),
                                  get(r, "line total", "amount"), errors=errs, line=len(inv.items) + 1))
            continue
        cells = [c.strip() for c in r if c.strip()]
        if len(cells) >= 2:
            label, value = cells[-2].rstrip(":").lower(), cells[-1]
            if label.startswith("subtotal"):
                inv.subtotal = parse_money(value)
            elif label.startswith("tax"):
                inv.tax = parse_money(value)
                if "(" in label:
                    rate = parse_money(label.split("(")[1].replace("%", "").rstrip(")"))
                    inv.tax_rate = rate / 100 if rate is not None else None
            elif label.startswith("shipping"):
                inv.shipping = parse_money(value)
            elif "total" in label:
                inv.total = parse_money(value)
    inv.vendor = meta.get("vendor")
    inv.terms = meta.get("payment terms")
    inv.currency = (meta.get("currency") or "USD").upper()
    inv.type_errors = errs
    return finish(inv, number=meta.get("invoice number"), date_raw=meta.get("date"), due_raw=meta.get("due date"))


def parse_xml(text: str, source: str | None = None) -> Invoice:
    root = ET.fromstring(text)

    def t(path):
        el = root.find(path)
        return el.text.strip() if el is not None and el.text else None

    inv = Invoice(source_file=source, source_format="xml")
    inv.vendor = t("header/vendor") or t("vendor")
    inv.currency = (t("header/currency") or t("currency") or "USD").upper()
    errs: list[str] = []
    for n, el in enumerate(root.findall("line_items/item"), 1):
        inv.items.append(item(el.findtext("name") or el.findtext("sku") or "", el.findtext("quantity"),
                              el.findtext("unit_price"), el.findtext("amount"), errors=errs, line=n))
    inv.type_errors = errs
    inv.subtotal = parse_money(t("totals/subtotal"))
    inv.tax_rate = parse_money(t("totals/tax_rate"))
    inv.tax = parse_money(t("totals/tax_amount"))
    inv.shipping = parse_money(t("totals/shipping"))
    inv.total = parse_money(t("totals/total"))
    inv.terms = t("payment_terms") or t("header/payment_terms")
    return finish(inv, number=t("header/invoice_number") or t("invoice_number"),
                  date_raw=t("header/date"), due_raw=t("header/due_date"))
