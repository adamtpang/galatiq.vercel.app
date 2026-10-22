"""PDF text extraction: pdfplumber (layout mode) first, PyMuPDF as fallback."""
from __future__ import annotations

from pathlib import Path


class PdfTextError(RuntimeError):
    pass


def pdf_to_text(path: str | Path) -> tuple[str, str]:
    """Return (text, engine). Raises PdfTextError when no text layer exists (scans need OCR)."""
    errors = []
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            text = "\n".join((p.extract_text(layout=True) or "") for p in pdf.pages)
        if text.strip():
            return text, "pdfplumber"
    except Exception as e:  # pragma: no cover - depends on the file
        errors.append(f"pdfplumber: {e}")
    try:
        import fitz  # PyMuPDF

        with fitz.open(path) as doc:
            text = "\n".join(page.get_text() for page in doc)
        if text.strip():
            return text, "pymupdf"
    except Exception as e:  # pragma: no cover
        errors.append(f"pymupdf: {e}")
    raise PdfTextError("No extractable text (scanned PDF needs OCR). " + "; ".join(errors))
