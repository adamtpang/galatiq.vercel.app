"""Validation tools. Each tool is a pure function: (invoice, context) -> list[Flag].

Flag severities: block (cannot be paid as is), warn (needs a human look), info (context).
The approval agent decides what to do with them; these tools only report facts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
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
# Flags shown to people but kept from the deciding agents (risk, VP, critic), so they cannot change a decision.
ADVISORY = {"PAST_DUE"}


def as_of_date(policy: dict) -> date:
    raw = os.environ.get("INVOICE_AS_OF") or (policy.get("due_dates") or {}).get("as_of")
    return date.fromisoformat(str(raw)) if raw else date.today()


def check_past_due(inv: Invoice, policy: dict) -> list[Flag]:
    if not (policy.get("due_dates") or {}).get("past_due_warning") or inv.due_date is None:
        return []
    today = as_of_date(policy)
    days = (today - inv.due_date).days
    if days <= 0:
        return []
    return [_f("PAST_DUE", W, f"Due date {inv.due_date} passed {days} day{'s' if days != 1 else ''} before this run "
               f"({today}); shown for information, it does not change the decision",
               due_date=str(inv.due_date), as_of=str(today), days_past_due=days)]


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


# Currency symbols and ISO codes written next to an amount. The parsers read "$" and plain amounts only.
CURRENCY_SYMBOLS = {"€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "₩": "KRW", "₽": "RUB", "₺": "TRY", "₱": "PHP"}
_SYMBOL_AMOUNT = re.compile(r"([€£¥₹₩₽₺₱])\s?\d|\d\s?([€£¥₹₩₽₺₱])")
_ISO = "EUR|GBP|JPY|CNY|CAD|AUD|CHF|INR|MXN|BRL|KRW|SEK|NOK|DKK|PLN|ZAR|SGD|HKD|NZD|RUB|TRY"
_CODE_AMOUNT = re.compile(rf"\b({_ISO})\s?\$?\d|\d[\d,.]*\s?({_ISO})\b")


def check_currency_text(raw: str | None, inv: Invoice) -> list[Flag]:
    """Amounts written in another currency (a symbol such as ¥ or a code such as JPY next to a number).
    The parsers only read dollar amounts, so such an invoice cannot be read correctly: block it with an
    accurate reason instead of letting it fail later as 'no line items' or, worse, be read as USD."""
    if not raw:
        return []
    symbols = {CURRENCY_SYMBOLS[a or b] for a, b in _SYMBOL_AMOUNT.findall(raw)}
    codes = {(a or b).upper() for a, b in _CODE_AMOUNT.findall(raw)}
    seen = sorted(symbols | codes)
    if not symbols and not (codes - {inv.currency}):
        return []
    sign = {v: k for k, v in CURRENCY_SYMBOLS.items()}
    shown = ", ".join(f"{c} ({sign[c]})" if c in symbols else c for c in seen)
    return [_f("UNSUPPORTED_CURRENCY", B, f"Amounts are written in {shown}; this system reads amounts in dollars only "
               f"(the invoice reads as {inv.currency}), so it cannot be paid. A person must enter it.",
               currencies=seen, invoice_currency=inv.currency)]


def check_currency(inv: Invoice, policy: dict) -> tuple[list[Flag], float | None]:
    rate = fx_rate(inv.currency, policy)
    if rate is None:
        return [_f("UNSUPPORTED_CURRENCY", B, f"Billed in {inv.currency}; there is no FX rate for {inv.currency} "
                   "(config/policy.yaml fx_to_usd), so it cannot be converted to USD or paid",
                   currency=inv.currency)], None
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
def closest_vendor(name: str, inventory: Inventory) -> tuple[str | None, float]:
    """Most similar vendor-master name or alias (normalized), with its similarity 0..1."""
    key, best, score = _norm(name), None, 0.0
    for v in inventory.vendors.values():
        for cand in (v.name, *v.aliases):
            r = SequenceMatcher(None, key, _norm(cand)).ratio()
            if r > score:
                best, score = v.name, r
    return best, score


def check_vendor(inv: Invoice, inventory: Inventory, policy: dict | None = None) -> list[Flag]:
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
        min_sim = ((policy or {}).get("vendor_lookalike") or {}).get("min_similarity")
        if min_sim:
            near, sim = closest_vendor(inv.vendor, inventory)
            if near and sim >= min_sim:
                out.append(_f("VENDOR_LOOKALIKE", W, f"'{inv.vendor}' is not on file but looks like vendor '{near}' "
                              f"(similarity {sim:.2f})", vendor=inv.vendor, lookalike_of=near, similarity=round(sim, 3)))
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


def content_key(inv: Invoice) -> tuple | None:
    """Vendor (normalized), line items with quantities, and total; the invoice number is left out."""
    if not inv.vendor or not inv.items or inv.total is None:
        return None
    lines = Counter((li.sku or _norm(li.sku_raw), float(li.qty)) for li in inv.items)
    return (_norm(inv.vendor), tuple(sorted(lines.items())), round(float(inv.total), 2))


def fingerprint(inv: Invoice) -> str:
    key = f"{_norm(inv.number)}|{_norm(inv.vendor)}|{inv.total}|{inv.revision or ''}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def document_id(inv: Invoice, source: str | Path) -> str:
    """One stored document: the invoice fingerprint plus its file name (the invoices.fingerprint column)."""
    return fingerprint(inv) + "|" + Path(source).name


def content_hash(inv: Invoice) -> str | None:
    k = content_key(inv)
    return None if k is None else hashlib.sha256(json.dumps(k).encode()).hexdigest()[:16]


def number_key(inv: Invoice) -> str | None:
    return f"{_norm(inv.number)}|{_norm(inv.vendor)}" if inv.number else None


@dataclass
class DuplicateRegistry:
    """Duplicate and revision detection, within this run and against stored history.

    Within a run: batch mode calls prescan() first with every file's parsed invoice, so an
    original is flagged SUPERSEDED_BY_REVISION before it can be approved, even though the
    revision comes later in the batch. Without a prescan it works sequentially.

    History: with a connection, check_history() also compares the invoice with every
    document stored in the `invoices` table by an earlier run (see check_history).
    """
    seen: dict[tuple[str, str], list[tuple[Invoice, InvoiceState | None]]] = field(default_factory=dict)
    order: dict[tuple[str, str], list[Invoice]] = field(default_factory=dict)
    by_content: dict[tuple, Invoice] = field(default_factory=dict)   # first invoice seen with this content
    conn: sqlite3.Connection | None = None   # stored history (invoices and payments tables)
    run_id: str = ""                         # rows first stored by this run are not history

    def _history(self, inv: Invoice) -> list[sqlite3.Row]:
        if self.conn is None:
            return []
        q = ("SELECT id, invoice_number, revision, vendor, total, currency, source_file, fingerprint, status, "
             "created_at, base_fp, number_key, content_key FROM invoices WHERE run_id IS NOT NULL AND run_id != ? "
             "AND (base_fp = ? OR number_key = ? OR content_key = ?) ORDER BY id")
        cur = self.conn.execute(q, (self.run_id, fingerprint(inv), number_key(inv), content_hash(inv)))
        cur.row_factory = sqlite3.Row
        return cur.fetchall()

    def _paid(self, r: sqlite3.Row) -> str:
        if self.conn is None:
            return ""
        p = self.conn.execute("SELECT amount, created_at FROM payments WHERE invoice_number IS ? AND vendor IS ? "
                              "AND status = 'paid' ORDER BY id LIMIT 1", (r["invoice_number"], r["vendor"])).fetchone()
        return f", paid {_money(p[0])} on {str(p[1])[:10]}" if p else ""

    STATUS_WORDS = {"APPROVED": "approved", "REJECTED": "rejected", "PENDING_HUMAN": "held for a person"}

    def _where(self, r: sqlite3.Row) -> str:
        return (f"{Path(r['source_file'] or '').name}, seen in an earlier run and "
                f"{self.STATUS_WORDS.get(r['status'] or '', 'not decided')}{self._paid(r)}")

    def check_history(self, inv: Invoice, source: str, have: set[str], match_content: bool) -> list[Flag]:
        """Compare with documents stored by earlier runs. For each kind of match only the EARLIEST
        stored document counts, so re-running the same file is idempotent: the original stays the
        original (payment then reports already_paid) and a copy stays a copy.

        - same fingerprint (number, vendor, total, revision), different file: DUPLICATE_INVOICE
        - same number and vendor, different fingerprint: revision of it (REVISION_SUPERSEDES, plus
          REVISION_AFTER_PAYMENT if the original was paid), replaced by it (SUPERSEDED_BY_REVISION),
          or reused with different content (DUPLICATE_NUMBER_CONFLICT)
        - same content under another number (decision 7): DUPLICATE_INVOICE, match=content
        Codes in `have` (already raised within this run) are not repeated."""
        rows = self._history(inv)
        if not rows:
            return []
        fp, me, ck = fingerprint(inv), document_id(inv, source), content_hash(inv)
        out: list[Flag] = []
        same = [r for r in rows if r["base_fp"] == fp]
        if same and same[0]["fingerprint"] != me and "DUPLICATE_INVOICE" not in have:
            r = same[0]
            out.append(_f("DUPLICATE_INVOICE", B, f"Same invoice already received as {self._where(r)}",
                          match="history", first_seen=r["source_file"], original_invoice=r["invoice_number"],
                          original_status=r["status"], fingerprint=fp))
        if not out:   # an original re-run still learns about a revision or a conflict stored since
            for r in (r for r in rows if inv.number and r["number_key"] == number_key(inv) and r["base_fp"] != fp):
                if inv.revision and r["revision"] != inv.revision:
                    out.append(_f("REVISION_SUPERSEDES", I, f"Revision {inv.revision} replaces {self._where(r)} "
                                  f"(total {_money(r['total'] or 0)} -> {_money(inv.total or 0)})",
                                  supersedes=r["source_file"], previous_total=r["total"],
                                  delta=round((inv.total or 0) - (r["total"] or 0), 2)))
                    if r["status"] == "APPROVED":
                        out.append(_f("REVISION_AFTER_PAYMENT", W, f"The invoice it revises was already approved "
                                      f"({self._where(r)}); paying the revision would pay twice",
                                      original=r["source_file"], original_total=r["total"]))
                elif r["revision"] and r["revision"] != inv.revision:
                    out.append(_f("SUPERSEDED_BY_REVISION", B, f"Replaced by revision {r['revision']} "
                                  f"in {self._where(r)}", superseded_by=r["source_file"]))
                else:
                    out.append(_f("DUPLICATE_NUMBER_CONFLICT", B, f"Invoice number reused with different content "
                                  f"(see {self._where(r)})", other=r["source_file"], other_total=r["total"],
                                  total=inv.total))
                break   # the earliest stored document with this number decides
        if match_content and ck and not any(f.code == "DUPLICATE_INVOICE" for f in out) \
                and "DUPLICATE_INVOICE" not in have:
            first = next((r for r in rows if r["content_key"] == ck), None)
            if first is not None and _norm(first["invoice_number"]) != _norm(inv.number):
                out.append(_f("DUPLICATE_INVOICE", B, f"Same vendor, line items, quantities and total as "
                              f"{first['invoice_number']} ({self._where(first)}) under a different number "
                              f"({inv.number})", match="content", original_invoice=first["invoice_number"],
                              first_seen=first["source_file"], original_status=first["status"]))
        return [f for f in out if f.code not in have]

    def check_content(self, inv: Invoice) -> list[Flag]:
        """Same vendor, items, quantities and total as an earlier invoice under a different number.
        Same-number copies are handled by check_and_register (DUPLICATE_INVOICE by fingerprint)."""
        k = content_key(inv)
        if k is None:
            return []
        first = self.by_content.get(k)
        if first is None:
            self.by_content[k] = inv
            return []
        if _norm(first.number) == _norm(inv.number):
            return []
        return [_f("DUPLICATE_INVOICE", B, f"Same vendor, line items, quantities and total as {first.number} "
                   f"({Path(first.source_file or '').name}) under a different number ({inv.number})",
                   match="content", original_invoice=first.number, first_seen=first.source_file)]

    @staticmethod
    def key(inv: Invoice) -> tuple[str, str]:
        return (_norm(inv.number), _norm(inv.vendor))

    def prescan(self, invoices: list[Invoice]) -> None:
        for inv in invoices:
            if inv.number:
                self.order.setdefault(self.key(inv), []).append(inv)

    def _compare(self, inv: Invoice, earlier: list[Invoice]) -> list[Flag]:
        for p_inv in earlier:
            if fingerprint(p_inv) == fingerprint(inv):
                return [_f("DUPLICATE_INVOICE", B, f"Same invoice already received as {Path(p_inv.source_file or '').name}",
                           first_seen=p_inv.source_file, fingerprint=fingerprint(inv))]
        out = []
        for p_inv in earlier:
            if inv.revision and inv.revision != p_inv.revision:
                delta = round((inv.total or 0) - (p_inv.total or 0), 2)
                out.append(_f("REVISION_SUPERSEDES", I, f"Revision {inv.revision} replaces {Path(p_inv.source_file or '').name} "
                              f"(total {_money(p_inv.total or 0)} -> {_money(inv.total or 0)})",
                              supersedes=p_inv.source_file, previous_total=p_inv.total, delta=delta))
            elif not (p_inv.revision and p_inv.revision != inv.revision):
                out.append(_f("DUPLICATE_NUMBER_CONFLICT", B, f"Invoice number reused with different content "
                              f"(see {Path(p_inv.source_file or '').name})", other=p_inv.source_file,
                              other_total=p_inv.total, total=inv.total))
        return out

    def check_and_register(self, inv: Invoice, state: InvoiceState) -> list[Flag]:
        if not inv.number:
            return []
        k = self.key(inv)
        planned = self.order.get(k, [])
        idx = next((i for i, x in enumerate(planned) if x.source_file == inv.source_file), None)
        if idx is not None:
            out = self._compare(inv, planned[:idx])
            for later in planned[idx + 1:]:
                if later.revision and later.revision != inv.revision and fingerprint(later) != fingerprint(inv):
                    out.append(_f("SUPERSEDED_BY_REVISION", B, f"Replaced by revision {later.revision} "
                                  f"in {Path(later.source_file or '').name}", superseded_by=later.source_file))
                    break
            return out
        prior = self.seen.setdefault(k, [])
        out = self._compare(inv, [p for p, _ in prior])
        if inv.revision:
            for p_inv, p_state in prior:
                if p_inv.revision != inv.revision and fingerprint(p_inv) != fingerprint(inv) and p_state is not None:
                    p_state.flags.append(_f("SUPERSEDED_BY_REVISION", B, f"Replaced by revision {inv.revision} "
                                            f"in {Path(inv.source_file or '').name}", superseded_by=inv.source_file))
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
    flags += check_past_due(inv, policy)
    cur_flags, total_usd = check_currency(inv, policy)
    if not cur_flags or cur_flags[0].code != "UNSUPPORTED_CURRENCY":
        cur_flags = check_currency_text(state.raw_text, inv) + cur_flags
    if any(f.code == "UNSUPPORTED_CURRENCY" for f in cur_flags):
        total_usd = None
    flags += cur_flags
    flags += check_prices(inv, inventory, policy)
    flags += check_line_notes(inv)
    flags += check_vendor(inv, inventory, policy)
    flags += check_amount_thresholds(total_usd, policy)
    if any("OCR" in c for c in inv.corrections):
        flags.append(_f("OCR_CORRECTED", I, "Fixed OCR look-alike characters",
                        corrections=[c for c in inv.corrections if c.startswith("OCR")]))
    if registry is not None:
        match_content = bool((policy.get("duplicates") or {}).get("match_content"))
        dup = registry.check_and_register(inv, state)
        if match_content and not any(f.code == "DUPLICATE_INVOICE" for f in dup):
            dup += registry.check_content(inv)
        dup += registry.check_history(inv, state.source, {f.code for f in dup}, match_content)
        flags += dup
    # the currency problem is the root cause of any missing items or totals, so it leads the reasons
    flags.sort(key=lambda f: f.code != "UNSUPPORTED_CURRENCY")
    state.flags.extend(flags)
    state.total_usd = total_usd
    state.trace.append(TraceEvent(agent="validation", step="validate", detail={
        "flags": [f.model_dump(mode="json") for f in flags], "blocking": [f.code for f in flags if f.severity == B],
        "total_usd": total_usd}))
    return state
