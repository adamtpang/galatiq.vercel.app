"""Validation tools. Each tool is a pure function: (invoice, context) -> list[Flag].

Flag severities: block (cannot be paid as is), warn (needs a human look), info (context).
The approval agent decides what to do with them; these tools only report facts.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .db import Inventory
from .models import Flag, Invoice, InvoiceState, Severity, TraceEvent
from .normalize import terms_days

B, W, I = Severity.BLOCK, Severity.WARN, Severity.INFO


def _f(code: str, sev: Severity, msg: str, **ev: Any) -> Flag:
    return Flag(code=code, severity=sev, message=msg, evidence=ev)


def _money(x: float) -> str:
    return f"${x:,.2f}"


# --- required fields ----------------------------------------------------------------
def check_required_fields(inv: Invoice) -> list[Flag]:
    out = []
    if not inv.vendor:
        out.append(_f("MISSING_VENDOR", B, "Vendor name is missing"))
    if not inv.number:
        out.append(_f("MISSING_INVOICE_NUMBER", W, "Invoice number is missing"))
    if not inv.items:
        out.append(_f("MISSING_ITEMS", B, "No line items found"))
    if inv.total is None:
        out.append(_f("MISSING_TOTAL", B, "Total amount is missing"))
    if inv.due_date_raw is None:
        out.append(_f("MISSING_DUE_DATE", W, "Due date is missing"))
    return out


# --- quantities ---------------------------------------------------------------------
def check_quantities(inv: Invoice) -> list[Flag]:
    out = []
    for n, li in enumerate(inv.items, 1):
        if li.qty < 0:
            out.append(_f("NEGATIVE_QTY", B, f"Line {n} ({li.sku_raw}) has negative quantity {li.qty:g}",
                          line=n, item=li.sku_raw, qty=li.qty))
        elif li.qty == 0:
            out.append(_f("ZERO_QTY", W, f"Line {n} ({li.sku_raw}) has zero quantity", line=n, item=li.sku_raw))
        if li.unit_price is not None and li.unit_price < 0:
            out.append(_f("NEGATIVE_PRICE", B, f"Line {n} ({li.sku_raw}) has a negative unit price",
                          line=n, item=li.sku_raw, unit_price=li.unit_price))
    if inv.total is not None and inv.total < 0:
        out.append(_f("NEGATIVE_TOTAL", B, f"Invoice total is negative ({_money(inv.total)})", total=inv.total))
    return out


# --- inventory ----------------------------------------------------------------------
def check_inventory(inv: Invoice, inventory: Inventory, policy: dict) -> list[Flag]:
    out = []
    min_conf = policy.get("sku_matching", {}).get("min_confidence", 0.85)
    requested: dict[str, float] = defaultdict(float)
    lines: dict[str, list[int]] = defaultdict(list)
    for n, li in enumerate(inv.items, 1):
        if not li.sku or li.sku_confidence < min_conf:
            out.append(_f("UNKNOWN_ITEM", B, f"'{li.sku_raw}' is not in inventory", line=n, item=li.sku_raw))
            continue
        if li.sku != li.sku_raw:
            out.append(_f("SKU_NORMALIZED", I, f"'{li.sku_raw}' read as {li.sku}", line=n,
                          raw=li.sku_raw, sku=li.sku, confidence=li.sku_confidence))
        if li.qty > 0:
            requested[li.sku] += li.qty
            lines[li.sku].append(n)
    for sku, qty in requested.items():
        row = inventory.query_inventory(sku)
        if row is None:
            continue
        if row.stock == 0:
            out.append(_f("ZERO_STOCK", B, f"{sku} has zero stock (requested {qty:g})",
                          item=sku, requested=qty, stock=0))
        elif qty > row.stock:
            agg = f" across lines {lines[sku]}" if len(lines[sku]) > 1 else ""
            out.append(_f("STOCK_EXCEEDED", B, f"{sku}: requested {qty:g}{agg}, only {row.stock} in stock",
                          item=sku, requested=qty, stock=row.stock, lines=lines[sku]))
        elif len(lines[sku]) > 1:
            out.append(_f("LINES_AGGREGATED", I, f"{sku} appears on lines {lines[sku]}; {qty:g} total is within stock",
                          item=sku, requested=qty, stock=row.stock, lines=lines[sku]))
    return out


# --- arithmetic ---------------------------------------------------------------------
def check_math(inv: Invoice, policy: dict) -> list[Flag]:
    tol = policy.get("arithmetic", {}).get("tolerance", 0.01)
    out = []
    line_sum = 0.0
    for n, li in enumerate(inv.items, 1):
        if li.unit_price is None:
            continue
        calc = li.qty * li.unit_price
        if li.amount is not None and abs(li.amount - calc) > tol:
            out.append(_f("LINE_AMOUNT_MISMATCH", B, f"Line {n}: {li.qty:g} x {_money(li.unit_price)} = "
                          f"{_money(calc)}, invoice says {_money(li.amount)}", line=n, expected=calc, printed=li.amount))
        line_sum += li.amount if li.amount is not None else calc
    line_sum = round(line_sum, 2)
    if inv.subtotal is not None and abs(inv.subtotal - line_sum) > tol:
        out.append(_f("SUBTOTAL_MISMATCH", B, f"Lines sum to {_money(line_sum)}, subtotal says {_money(inv.subtotal)}",
                      lines_sum=line_sum, subtotal=inv.subtotal))
    base = inv.subtotal if inv.subtotal is not None else line_sum
    if inv.tax is not None and inv.tax_rate and abs(base * inv.tax_rate - inv.tax) > tol:
        out.append(_f("TAX_MISMATCH", W, f"Tax {_money(inv.tax)} is not {inv.tax_rate:.0%} of {_money(base)}",
                      tax=inv.tax, rate=inv.tax_rate, base=base))
    if inv.total is not None:
        expected = round(base + (inv.tax or 0) + (inv.shipping or 0), 2)
        if abs(expected - inv.total) > tol:
            out.append(_f("TOTAL_MISMATCH", B, f"Subtotal + tax + shipping = {_money(expected)}, "
                          f"total says {_money(inv.total)}", expected=expected, total=inv.total))
    return out


# --- dates and terms ----------------------------------------------------------------
def check_dates(inv: Invoice, policy: dict) -> list[Flag]:
    out = []
    if inv.due_date_raw is not None and inv.due_date is None:
        out.append(_f("INVALID_DUE_DATE", B, f"Due date '{inv.due_date_raw}' is not a calendar date",
                      raw=inv.due_date_raw))
    if inv.date_raw is not None and inv.date is None:
        out.append(_f("INVALID_DATE", W, f"Invoice date '{inv.date_raw}' is not a calendar date", raw=inv.date_raw))
    if inv.date and inv.due_date:
        gap = (inv.due_date - inv.date).days
        if gap < 0:
            out.append(_f("DUE_BEFORE_ISSUE", W, f"Due date {inv.due_date} is before issue date {inv.date}", days=gap))
        days = terms_days(inv.terms)
        tol = policy.get("payment_terms", {}).get("tolerance_days", 2)
        if days is not None and abs(gap - days) > tol:
            out.append(_f("TERMS_MISMATCH", I, f"Terms say {inv.terms} but due date is {gap} days after issue",
                          terms=inv.terms, days_between=gap))
    return out


# --- prices and currency ------------------------------------------------------------
def fx_rate(currency: str, policy: dict) -> float | None:
    return policy.get("fx_to_usd", {}).get((currency or "USD").upper())


def check_currency(inv: Invoice, policy: dict) -> tuple[list[Flag], float | None]:
    rate = fx_rate(inv.currency, policy)
    if rate is None:
        return [_f("UNSUPPORTED_CURRENCY", B, f"No FX rate for {inv.currency}", currency=inv.currency)], None
    total_usd = round(inv.total * rate, 2) if inv.total is not None else None
    if inv.currency != "USD":
        return [_f("CURRENCY_CONVERTED", W, f"Billed in {inv.currency}; {_money(inv.total or 0)} "
                   f"{inv.currency} = {_money(total_usd or 0)} USD at mock rate {rate}",
                   currency=inv.currency, rate=rate, total=inv.total, total_usd=total_usd)], total_usd
    return [], total_usd


def check_prices(inv: Invoice, inventory: Inventory, policy: dict) -> list[Flag]:
    pv = policy.get("price_variance", {})
    up, down = pv.get("warn_above_pct", 10), pv.get("info_below_pct", 10)
    rate = fx_rate(inv.currency, policy) or 1.0
    out = []
    for n, li in enumerate(inv.items, 1):
        row = inventory.query_inventory(li.sku) if li.sku else None
        if not row or row.unit_price is None or li.unit_price is None:
            continue
        price_usd = li.unit_price * rate
        pct = (price_usd - row.unit_price) / row.unit_price * 100
        ev = dict(line=n, item=li.sku, unit_price=li.unit_price, unit_price_usd=round(price_usd, 2),
                  catalog=row.unit_price, pct=round(pct, 1), note=li.note)
        if pct > up:
            out.append(_f("PRICE_VARIANCE", W, f"{li.sku} at {_money(price_usd)} is {pct:.0f}% above catalog "
                          f"{_money(row.unit_price)}", **ev))
        elif pct < -down:
            out.append(_f("PRICE_VARIANCE", I, f"{li.sku} at {_money(price_usd)} is {-pct:.0f}% below catalog "
                          f"{_money(row.unit_price)}", **ev))
    return out


def check_line_notes(inv: Invoice) -> list[Flag]:
    out = []
    for n, li in enumerate(inv.items, 1):
        if li.note and re.search(r"\bsample\b", li.note, re.I) and (li.unit_price or 0) > 0:
            out.append(_f("SAMPLE_CHARGED", W, f"Line {n} is marked '{li.note}' but is charged "
                          f"{_money(li.qty * li.unit_price)}", line=n, item=li.sku_raw, note=li.note))
    return out


# --- vendor -------------------------------------------------------------------------
def check_vendor(inv: Invoice, inventory: Inventory) -> list[Flag]:
    if not inv.vendor:
        return []
    out = []
    v = inventory.lookup_vendor(inv.vendor)
    if inv.vendor_former_name:
        old = inventory.lookup_vendor(inv.vendor_former_name)
        out.append(_f("VENDOR_RENAMED", W, f"Vendor says it was formerly '{inv.vendor_former_name}'"
                      + (" (on file); new name is not, so verify bank details" if old and not v else ""),
                      vendor=inv.vendor, former=inv.vendor_former_name, former_on_file=bool(old)))
    elif v is None:
        out.append(_f("UNKNOWN_VENDOR", W, f"'{inv.vendor}' is not in the vendor master", vendor=inv.vendor))
    if v is not None and not v.approved:
        out.append(_f("VENDOR_NOT_APPROVED", B, f"'{inv.vendor}' is not an approved vendor", vendor=inv.vendor))
    if re.search(r"\bacme\b", inv.vendor, re.I):
        out.append(_f("VENDOR_NAME_LOOKALIKE", I, f"Vendor name '{inv.vendor}' resembles the buyer (Acme)",
                      vendor=inv.vendor))
    return out


def check_amount_thresholds(total_usd: float | None, policy: dict) -> list[Flag]:
    if total_usd is None:
        return []
    ap = policy.get("approval", {})
    limit, near = ap.get("approval_threshold_usd", 10000), ap.get("near_limit_usd", 9500)
    if total_usd > limit:
        return [_f("OVER_APPROVAL_THRESHOLD", I, f"{_money(total_usd)} is over {_money(limit)}: extra scrutiny",
                   total_usd=total_usd, threshold=limit)]
    if total_usd >= near:
        return [_f("NEAR_APPROVAL_THRESHOLD", I, f"{_money(total_usd)} is just under the {_money(limit)} limit",
                   total_usd=total_usd, threshold=limit, near_limit=near)]
    return []


# --- duplicates and revisions -------------------------------------------------------
def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def fingerprint(inv: Invoice) -> str:
    key = f"{_norm(inv.number)}|{_norm(inv.vendor)}|{inv.total}|{inv.revision or ''}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


@dataclass
class DuplicateRegistry:
    """Invoices seen in this run, keyed by (number, vendor). Not persisted yet."""
    seen: dict[tuple[str, str], list[tuple[Invoice, InvoiceState]]] = field(default_factory=dict)

    def check_and_register(self, inv: Invoice, state: InvoiceState) -> list[Flag]:
        if not inv.number:
            return []
        key = (_norm(inv.number), _norm(inv.vendor))
        prior = self.seen.setdefault(key, [])
        out: list[Flag] = []
        for p_inv, p_state in prior:
            same = fingerprint(p_inv) == fingerprint(inv)
            if same:
                out.append(_f("DUPLICATE_INVOICE", B, f"Same invoice already received as {p_inv.source_file}",
                              first_seen=p_inv.source_file, fingerprint=fingerprint(inv)))
                break
            if inv.revision and inv.revision != p_inv.revision:
                delta = round((inv.total or 0) - (p_inv.total or 0), 2)
                out.append(_f("REVISION_SUPERSEDES", I, f"Revision {inv.revision} replaces {p_inv.source_file} "
                              f"(total {_money(p_inv.total or 0)} -> {_money(inv.total or 0)})",
                              supersedes=p_inv.source_file, previous_total=p_inv.total, delta=delta))
                p_state.flags.append(_f("SUPERSEDED_BY_REVISION", B, f"Replaced by revision {inv.revision} "
                                        f"in {inv.source_file}", superseded_by=inv.source_file))
            else:
                out.append(_f("DUPLICATE_NUMBER_CONFLICT", B, f"Invoice number reused with different content "
                              f"(see {p_inv.source_file})", other=p_inv.source_file,
                              other_total=p_inv.total, total=inv.total))
        prior.append((inv, state))
        return out


# --- orchestration ------------------------------------------------------------------
def validate(state: InvoiceState, inventory: Inventory, policy: dict,
             registry: DuplicateRegistry | None = None) -> InvoiceState:
    inv = state.invoice
    if inv is None:
        state.flags.append(_f("EXTRACTION_FAILED", B, "Could not extract invoice data", errors=state.errors))
        return state
    flags: list[Flag] = []
    flags += check_required_fields(inv)
    flags += check_quantities(inv)
    flags += check_inventory(inv, inventory, policy)
    flags += check_math(inv, policy)
    flags += check_dates(inv, policy)
    cur_flags, total_usd = check_currency(inv, policy)
    flags += cur_flags
    flags += check_prices(inv, inventory, policy)
    flags += check_line_notes(inv)
    flags += check_vendor(inv, inventory)
    flags += check_amount_thresholds(total_usd, policy)
    if any("OCR" in c for c in inv.corrections):
        flags.append(_f("OCR_CORRECTED", I, "Fixed OCR look-alike characters",
                        corrections=[c for c in inv.corrections if c.startswith("OCR")]))
    if registry is not None:
        flags += registry.check_and_register(inv, state)
    state.flags.extend(flags)
    state.total_usd = total_usd
    state.trace.append(TraceEvent(agent="validation", step="validate", detail={
        "flags": [f.code for f in flags], "blocking": [f.code for f in flags if f.severity == B]}))
    return state
