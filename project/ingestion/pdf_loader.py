"""
pdf_loader.py
-------------
Handles raw PDF loading and basic validation.
Keeps file I/O concerns separate from text extraction logic.
"""

from pathlib import Path
from pypdf import PdfReader


def load_pdf(pdf_path: str) -> PdfReader:
    """
    Load a PDF file and return a PdfReader object.

    Args:
        pdf_path: Absolute or relative path to the PDF file.

    Returns:
        PdfReader instance ready for page iteration.

    Raises:
        FileNotFoundError: If the PDF does not exist at the given path.
        ValueError: If the file is not a valid PDF.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file, got: {path.suffix}")

    reader = PdfReader(str(path))
    print(f"[pdf_loader] Loaded '{path.name}' — {len(reader.pages)} pages.")
    return reader
