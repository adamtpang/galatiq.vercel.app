"""PDF text extraction: pdfplumber (layout mode) first, PyMuPDF as fallback."""
from __future__ import annotations

from pathlib import Path
from io import BytesIO

from ..file_io import read_invoice_bytes


class PdfTextError(RuntimeError):
    pass


def pdf_to_text(path: str | Path) -> tuple[str, str]:
    """Return (text, engine). Raises PdfTextError when no text layer exists (scans need OCR)."""
    data = read_invoice_bytes(path)
    errors = []
    try:
        import pdfplumber

        with pdfplumber.open(BytesIO(data)) as pdf:
            text = "\n".join((p.extract_text(layout=True) or "") for p in pdf.pages)
        if text.strip():
            return text, "pdfplumber"
    except Exception as e:  # pragma: no cover - depends on the file
        errors.append(f"pdfplumber: {e}")
    try:
        import pymupdf  # PyMuPDF (the old `fitz` import name prints a deprecation warning)

        with pymupdf.open(stream=data, filetype="pdf") as doc:
            text = "\n".join(page.get_text() for page in doc)
        if text.strip():
            return text, "pymupdf"
    except Exception as e:  # pragma: no cover
        errors.append(f"pymupdf: {e}")
    raise PdfTextError("No extractable text (scanned PDF needs OCR). " + "; ".join(errors))
