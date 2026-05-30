"""
chunking.py
-----------
Splits section content into overlapping chunks using a sliding window.

Design note: Fixed-size sliding window chunking is used over sentence-based
splitting because research paper text often has no clean sentence boundaries
after PDF extraction. Overlap preserves cross-boundary context.
"""

from typing import TypedDict


class Chunk(TypedDict):
    """A single text chunk with metadata for vector store storage."""
    chunk_id: str       # Unique identifier: "<section_title>__<index>"
    section: str        # Source section title
    text: str           # Chunk content


DEFAULT_CHUNK_SIZE = 800    # characters per chunk
DEFAULT_OVERLAP = 100       # characters of overlap between consecutive chunks


def chunk_sections(
    sections: list[dict],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """
    Chunk all sections using a character-level sliding window.

    Args:
        sections: List of Section dicts with 'title' and 'content' keys.
        chunk_size: Maximum characters per chunk.
        overlap: Number of characters to overlap between consecutive chunks.

    Returns:
        Flat list of Chunk TypedDicts across all sections.
    """
    all_chunks: list[Chunk] = []

    for section in sections:
        title = section["title"]
        content = section["content"]
        window_chunks = _sliding_window(content, chunk_size, overlap)

        for idx, chunk_text in enumerate(window_chunks):
            all_chunks.append(Chunk(
                chunk_id=f"{title}__{idx}",
                section=title,
                text=chunk_text.strip(),
            ))

    print(f"[chunking] Produced {len(all_chunks)} chunks from {len(sections)} sections.")
    return all_chunks


def _sliding_window(text: str, chunk_size: int, overlap: int) -> list[str]:
    """
    Apply sliding window to a single text string.

    Args:
        text: Source text to split.
        chunk_size: Max characters per window.
        overlap: Characters to retain from the previous window.

    Returns:
        List of text chunks.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    step = chunk_size - overlap  # advance by (chunk_size - overlap) each iteration

    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += step

    return chunks
