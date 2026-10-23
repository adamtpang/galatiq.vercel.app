"""Format router. Picks a parser by extension, then by sniffing content."""
from __future__ import annotations

from pathlib import Path

from ..models import Invoice
from ..file_io import read_invoice_bytes
from .pdf import PdfTextError, pdf_to_text
from .structured import parse_csv, parse_json, parse_xml
from .text import parse_text

SUPPORTED = {".txt", ".eml", ".csv", ".json", ".xml", ".pdf"}


class UnsupportedFormat(ValueError):
    pass


def read_source(path: str | Path) -> tuple[str, str]:
    """Return (raw_text, format)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        text, _engine = pdf_to_text(p)
        return text, "pdf"
    text = read_invoice_bytes(p).decode("utf-8", errors="replace")
    if ext in (".json", ".xml", ".csv"):
        return text, ext[1:]
    head = text.lstrip()[:1]
    if head in "{[":
        return text, "json"
    if head == "<":
        return text, "xml"
    return text, "txt"


def parse_raw(text: str, fmt: str, source: str | None = None) -> Invoice:
    if fmt == "json":
        return parse_json(text, source)
    if fmt == "csv":
        return parse_csv(text, source)
    if fmt == "xml":
        return parse_xml(text, source)
    if fmt in ("txt", "pdf"):
        return parse_text(text, source, fmt)
    raise UnsupportedFormat(fmt)


def parse_file(path: str | Path) -> Invoice:
    text, fmt = read_source(path)
    return parse_raw(text, fmt, str(path))


__all__ = ["parse_file", "parse_raw", "read_source", "PdfTextError", "UnsupportedFormat", "SUPPORTED"]
