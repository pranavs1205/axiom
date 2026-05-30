"""
text_extractor.py
-----------------
Extracts and cleans raw text from a PDF.

Note: pdf_path is passed explicitly because BytesIO streams have no .name
attribute on Windows, which breaks pdfplumber's open() call.
"""

import re


def extract_text(reader, pdf_path: str = None) -> str:
    """
    Extract and clean text from a PDF.

    Tries pdfplumber first (better layout handling), falls back to pypdf.

    Args:
        reader: A loaded PdfReader instance (pypdf).
        pdf_path: Path to the PDF file. Required for pdfplumber.
                  If not provided, falls back to pypdf directly.

    Returns:
        Cleaned full document text as a single string.
    """
    raw_text = ""

    if pdf_path:
        try:
            import pdfplumber
            pages_text = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
                    pages_text.append(text)
            raw_text = "\n\n".join(pages_text)
            print(f"[text_extractor] pdfplumber extracted ~{len(raw_text)} chars from {len(pages_text)} pages.")
        except Exception as e:
            print(f"[text_extractor] pdfplumber failed ({type(e).__name__}: {e}), falling back to pypdf.")
            raw_text = ""

    if not raw_text:
        pages_text = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages_text.append(text.strip())
        raw_text = "\n\n".join(pages_text)
        print(f"[text_extractor] pypdf extracted ~{len(raw_text)} chars.")

    cleaned = _clean_text(raw_text)
    print(f"[text_extractor] After cleaning: ~{len(cleaned)} chars.")
    return cleaned


def _clean_text(text: str) -> str:
    """
    Clean extracted PDF text to remove common extraction artifacts.

    Removes:
      - Lines that are only digits/spaces (page numbers, equation labels)
      - Lines shorter than 3 characters (stray chars, column separators)
        Note: threshold is 3 (not 4) to preserve 2-char terms like AI, ML, GPU
      - Lines that are ONLY non-alphanumeric characters (true symbol-only garbage)
      - Runs of more than 2 consecutive blank lines
    """
    lines = text.splitlines()
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()

        # Skip pure digit/space lines (page numbers, equation labels like "6 7")
        if re.match(r"^[\d\s]+$", stripped) and len(stripped) <= 10:
            continue

        # Skip very short lines (stray chars, column artifacts) — 3 keeps "AI", "ML"
        if len(stripped) < 3:
            continue

        # Skip lines with zero alphanumeric characters (symbol/box-drawing garbage)
        # Uses \w which matches letters, digits, underscore — safe for equations
        if not re.search(r"\w", stripped):
            continue

        cleaned_lines.append(line)

    result = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines))
    return result.strip()
