"""
extraction/parse_pdf.py — Extract plain text from a PDF contract file.

Uses pdfplumber for reliable text extraction from standard PDF documents.
The extracted text is passed directly to extract_contract.py's Groq call —
no changes to the LLM pipeline are needed.

Usage:
    from extraction.parse_pdf import extract_text_from_pdf
    text = extract_text_from_pdf("contracts/vendor_msa.pdf")
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber


def extract_text_from_pdf(path: str | Path) -> str:
    """
    Extract all text from a PDF file, page by page.

    Args:
        path: Path to the PDF file.

    Returns:
        Full extracted text as a single string with pages separated by newlines.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the file is not a PDF or yields no text.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file, got: {path.suffix}")

    pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)

    if not pages:
        raise ValueError(f"No text could be extracted from {path.name}. "
                         "The PDF may be scanned/image-only.")

    return "\n\n".join(pages)
