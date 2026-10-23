"""Deterministic normalizers: OCR artifacts, money, dates, invoice numbers, SKUs."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from difflib import get_close_matches

# --- OCR artifacts -----------------------------------------------------------------
# Inside a token that is clearly numeric (digits plus at most a couple of look-alike
# letters), map letters that OCR confuses with digits.
_OCR_MAP = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1"})
_NUMERIC_TOKEN = re.compile(r"(?<![A-Za-z])[\d$][\d,.$OolI]*[\dOolI](?![A-Za-z])")

_FOLD = str.maketrans("01l", "oii")   # look-alike characters folded before comparing SKUs


def fix_ocr_digits(text: str) -> tuple[str, list[str]]:
    """Replace O->0, l/I->1 inside numeric-looking tokens. Returns (text, corrections)."""
    corrections: list[str] = []

    def repl(m: re.Match) -> str:
        tok = m.group(0)
        digits = sum(ch.isdigit() for ch in tok)
        letters = sum(ch in "OolI" for ch in tok)
        if letters and digits >= 2 and letters <= 2:
            fixed = tok.translate(_OCR_MAP)
            corrections.append(f"OCR: '{tok}' -> '{fixed}'")
            return fixed
        return tok

    return _NUMERIC_TOKEN.sub(repl, text), corrections


# --- money --------------------------------------------------------------------------
_MONEY = re.compile(r"(?P<sign>[+-]?)\s*\$?\s*(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)")
# Currency markers written before or after an amount. USD markers are read; any other marker is recognized only
# so the amount is never read as dollars (validation routes the invoice to a person or rejects it).
_ISO_CODES = ("EUR|GBP|JPY|CNY|CAD|AUD|CHF|INR|MXN|BRL|KRW|SEK|NOK|DKK|PLN|ZAR|SGD|HKD|NZD|RUB|TRY")
_USD_MARKER = r"USD|US\$|U\.S\.\s?\$"
_FOREIGN_MARKER = rf"{_ISO_CODES}|(?:AU|CA|NZ|HK|MX|A|C|R|S)\$|[€£¥₹₩₽₺₱]"
_LEADING = re.compile(rf"^(?P<m>{_USD_MARKER}|{_FOREIGN_MARKER})\s*(?P<rest>.*)$", re.I)
_TRAILING = re.compile(rf"^(?P<rest>.*?)\s*(?<![A-Za-z])(?P<m>{_USD_MARKER}|{_ISO_CODES}|[€£¥₹₩₽₺₱])$", re.I)
_NOTE = re.compile(r"\s*\((?=[^()]*[A-Za-z])[^()]*\)$")   # a trailing note such as "(exempt)", never "(500)"


def split_currency(text: str) -> tuple[str | None, str]:
    """Return (marker currency or None, the amount without its marker and any trailing note in brackets)."""
    s = text.strip()
    if not (s.startswith("(") and s.endswith(")") and not re.search(r"[A-Za-z]", s)):
        s = _NOTE.sub("", s).strip()
    for rx in (_LEADING, _TRAILING):
        m = rx.match(s)
        if m and m.group("rest").strip():
            mark = m.group("m").upper().replace(" ", "")
            code = "USD" if re.fullmatch(_USD_MARKER, mark, re.I) else mark
            return code, m.group("rest").strip()
    return None, s


def foreign_currency_marker(value) -> str | None:
    """The non-USD currency marker on a money string ('A$500.00' -> 'A$'), else None."""
    if not isinstance(value, str):
        return None
    code, _ = split_currency(value)
    return code if code not in (None, "USD") else None


def parse_money(value) -> float | None:
    if value is None or isinstance(value, (bool, list, tuple, dict, set)):
        return None   # true is not 1 and ["8"] is not 8: only numbers and strings are amounts
    if isinstance(value, (int, float)):
        return float(value)
    code, s = split_currency(str(value))
    if code not in (None, "USD"):
        return None   # a foreign amount is never read as dollars
    s, _ = fix_ocr_digits(s)
    # Accounting parentheses mean negative. Never read an arbitrary numeric substring:
    # '(500)' is not +500, '2e2' is not 2, and an unknown tax is not zero.
    accounting = s.startswith("(") and s.endswith(")")
    if accounting:
        s = s[1:-1].strip()
    m = _MONEY.fullmatch(s)
    if not m:
        return None
    if accounting and m.group("sign"):
        return None
    try:
        v = float(m.group("number").replace(",", ""))
    except ValueError:
        return None
    return -v if accounting or m.group("sign") == "-" else v


# --- dates --------------------------------------------------------------------------
RELATIVE_DATE_WORDS = {"yesterday", "today", "tomorrow", "asap", "immediately", "now"}
# "%d/%m/%Y" comes after "%m/%d/%Y", so it is only used when the first number cannot be a month (20/02/2026);
# an ambiguous 05/04/2026 stays month-first, as before.
_DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d %Y", "%b %d, %Y", "%B %d %Y", "%B %d, %Y",
    "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y", "%Y/%m/%d",
]


@dataclass
class DateResult:
    value: date | None
    raw: str | None
    status: str  # ok | missing | relative | invalid
    corrected: str | None = None


def parse_date(raw) -> DateResult:
    if raw is None or str(raw).strip() == "":
        return DateResult(None, None if raw is None else str(raw), "missing")
    s = str(raw).strip()
    if s.lower() in RELATIVE_DATE_WORDS:
        return DateResult(None, s, "relative")
    fixed, corr = fix_ocr_digits(s)
    for fmt in _DATE_FORMATS:
        try:
            return DateResult(datetime.strptime(fixed, fmt).date(), s, "ok", fixed if corr else None)
        except ValueError:
            continue
    return DateResult(None, s, "invalid")


# --- invoice numbers ----------------------------------------------------------------
def normalize_invoice_number(raw) -> str | None:
    if raw is None:
        return None
    s, _ = fix_ocr_digits(str(raw).strip())
    # Canonicalize the case's simple invoice labels, preserving compound and supplier-specific IDs.
    # Taking only the first digit group merges INV-2026-001 with INV-2026-002.
    m = re.fullmatch(r"(?:INV(?:OICE)?(?:\s*(?:NO\.?|NUMBER))?[\s:#.-]*)?(\d+)", s, re.I)
    if not m:
        return s or None
    return f"INV-{m.group(1)}"


# --- payment terms ------------------------------------------------------------------
def terms_days(terms: str | None) -> int | None:
    if not terms:
        return None
    m = re.search(r"net\s*(\d+)", terms, re.I)
    if m:
        return int(m.group(1))
    if re.search(r"immediate|due on receipt", terms, re.I):
        return 0
    return None


# --- SKUs ---------------------------------------------------------------------------
@dataclass
class SkuMatch:
    sku: str | None
    confidence: float
    method: str
    note: str | None = None
    suggestion: str | None = None


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def normalize_sku(raw: str, catalog: list[str]) -> SkuMatch:
    """Map a printed item name to a catalog SKU using only safe transformations.

    Exact 1.0 > case/spacing/punctuation 0.95 > parenthetical note stripped 0.9 >
    OCR look-alike characters 0.85. Edit-distance is never used to accept a match
    (WidgetC must not become WidgetA); it is only offered as a suggestion.
    """
    raw = raw.strip()
    if raw in catalog:
        return SkuMatch(raw, 1.0, "exact")
    keys = {_key(c): c for c in catalog}
    if _key(raw) in keys:
        return SkuMatch(keys[_key(raw)], 0.95, "case_spacing")
    note = None
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", raw)
    if m:
        base, note = m.group(1), m.group(2).strip()
        if _key(base) in keys:
            return SkuMatch(keys[_key(base)], 0.9, "stripped_note", note=note)
        raw_base = base
    else:
        raw_base = raw
    def fold(k: str) -> str:
        return k.translate(_FOLD)

    ocr = fold(_key(raw_base))
    for k, c in keys.items():
        if fold(k) == ocr:
            return SkuMatch(c, 0.85, "ocr_lookalike", note=note)
    close = get_close_matches(_key(raw_base), list(keys), n=1, cutoff=0.7)
    return SkuMatch(None, 0.0, "unknown", note=note, suggestion=keys[close[0]] if close else None)


_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_SPACED = re.compile(r"\b(?:\w[ \t]){2,}\w\b")


def match_text(text: str | None) -> str:
    """Text prepared for pattern matching only (never for numbers): Unicode NFKC (fullwidth < becomes <),
    zero-width characters removed, lower case, and spaced-out letters joined ("i g n o r e" becomes "ignore").
    Line breaks are kept so patterns anchored at a line start still work."""
    t = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", str(text or ""))).lower()
    return _SPACED.sub(lambda m: re.sub(r"[ \t]", "", m.group(0)), t)
