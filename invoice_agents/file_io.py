"""Bounded invoice input shared by parsing, PDF extraction and cache hashing."""
from pathlib import Path

MAX_BYTES = 10_000_000


def read_invoice_bytes(path: str | Path) -> bytes:
    p = Path(path)
    if p.stat().st_size > MAX_BYTES:
        raise OSError(f"file exceeds the {MAX_BYTES / 1e6:g} MB limit for one invoice")
    with p.open("rb") as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise OSError(f"file exceeds the {MAX_BYTES / 1e6:g} MB limit for one invoice")
    return data
