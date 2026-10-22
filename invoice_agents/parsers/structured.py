"""Parsers for JSON, CSV (key-value and tabular shapes) and XML invoices."""
from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET

from ..models import Invoice
from ..normalize import parse_money
from .common import finish, item


def _first(d: dict, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def parse_json(text: str, source: str | None = None) -> Invoice:
    d = json.loads(text)
    vendor = d.get("vendor")
    inv = Invoice(source_file=source, source_format="json")
    if isinstance(vendor, dict):
        inv.vendor, inv.vendor_address = vendor.get("name"), vendor.get("address")
    else:
        inv.vendor = vendor
    inv.revision = d.get("revision")
    inv.currency = (d.get("currency") or "USD").upper()
    for li in d.get("line_items") or d.get("items") or []:
        inv.items.append(item(_first(li, "item", "name", "sku", "description") or "",
                              _first(li, "quantity", "qty"), _first(li, "unit_price", "price", "rate"),
                              li.get("amount"), li.get("note")))
    inv.subtotal = parse_money(d.get("subtotal"))
    inv.tax = parse_money(_first(d, "tax_amount", "tax"))
    inv.tax_rate = parse_money(d.get("tax_rate"))
    inv.shipping = parse_money(d.get("shipping"))
    inv.total = parse_money(d.get("total"))
    inv.terms = d.get("payment_terms") or d.get("terms")
    inv.notes = d.get("notes")
    for k, v in {"vendor": inv.vendor, "number": d.get("invoice_number"), "due": d.get("due_date"),
                 "total": d.get("total")}.items():
        inv.field_confidence[k] = 1.0 if v not in (None, "") else 0.0
    return finish(inv, number=_first(d, "invoice_number", "number", "id"),
                  date_raw=d.get("date"), due_raw=d.get("due_date"))


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
    for r in rows:
        name = get(r, "item", "description", "sku")
        if name:
            for k in ("invoice number", "vendor", "date", "due date", "currency", "payment terms"):
                if get(r, k) and k not in meta:
                    meta[k] = get(r, k)
            inv.items.append(item(name, get(r, "qty", "quantity"), get(r, "unit price", "price"),
                                  get(r, "line total", "amount")))
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
    return finish(inv, number=meta.get("invoice number"), date_raw=meta.get("date"), due_raw=meta.get("due date"))


def parse_xml(text: str, source: str | None = None) -> Invoice:
    root = ET.fromstring(text)

    def t(path):
        el = root.find(path)
        return el.text.strip() if el is not None and el.text else None

    inv = Invoice(source_file=source, source_format="xml")
    inv.vendor = t("header/vendor") or t("vendor")
    inv.currency = (t("header/currency") or t("currency") or "USD").upper()
    for el in root.findall("line_items/item"):
        inv.items.append(item(el.findtext("name") or el.findtext("sku") or "", el.findtext("quantity"),
                              el.findtext("unit_price"), el.findtext("amount")))
    inv.subtotal = parse_money(t("totals/subtotal"))
    inv.tax_rate = parse_money(t("totals/tax_rate"))
    inv.tax = parse_money(t("totals/tax_amount"))
    inv.shipping = parse_money(t("totals/shipping"))
    inv.total = parse_money(t("totals/total"))
    inv.terms = t("payment_terms") or t("header/payment_terms")
    return finish(inv, number=t("header/invoice_number") or t("invoice_number"),
                  date_raw=t("header/date"), due_raw=t("header/due_date"))
