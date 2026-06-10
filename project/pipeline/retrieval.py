"""
retrieval.py
------------
Retrieves relevant chunks from the FAISS vector store given a query.

Two retrieval modes:
  - General: top-k semantically similar chunks from any section.
  - Methodology-only: same search, but filtered to methodology-related sections.

Note: query vectors are L2-normalized before search to match the cosine
similarity index built in vector_store.py.
"""

import numpy as np
import faiss
from pipeline.vector_store import VectorStore


# Section title keywords that identify methodology-related content
METHODOLOGY_KEYWORDS = {
    "method", "methods", "methodology", "approach", "model", "models",
    "framework", "architecture", "implementation", "implementation details",
    "system", "system design", "system overview", "algorithm", "algorithms",
    "design", "proposed", "proposed method", "our approach", "formulation",
    "problem formulation", "objective", "training", "inference",
    "optimization", "preliminaries", "overview", "technique", "techniques",
}


def retrieve(query: str, store: VectorStore, top_k: int = 5) -> list[dict]:
    """
    Retrieve the top-k most relevant chunks for a given query using cosine similarity.

    Args:
        query: Natural language query string.
        store: Loaded VectorStore with FAISS index and metadata.
        top_k: Number of results to return.

    Returns:
        List of metadata dicts for the top-k most similar chunks.
    """
    query_vec = np.array(list(store["model"].embed([query])), dtype=np.float32)
    faiss.normalize_L2(query_vec)  # Must normalize to match IndexFlatIP cosine index
    scores, indices = store["index"].search(query_vec, top_k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:  # FAISS returns -1 when fewer results exist than top_k
            continue
        chunk_meta = store["metadata"][idx]
        results.append({**chunk_meta, "score": float(score)})

    return results


def retrieve_methodology(query: str, store: VectorStore, top_k: int = 5) -> list[dict]:
    """
    Retrieve top-k relevant chunks, filtered to methodology-related sections only.

    Over-fetches (top_k * 4) before filtering to ensure enough methodology
    chunks are found even if they don't rank highest overall.

    Args:
        query: Natural language query string.
        store: Loaded VectorStore.
        top_k: Number of methodology results to return.

    Returns:
        List of metadata dicts from methodology-related sections only.
    """
    candidates = retrieve(query, store, top_k=top_k * 4)

    filtered = []
    for chunk in candidates:
        section_lower = chunk["section"].lower()
        if any(kw in section_lower for kw in METHODOLOGY_KEYWORDS):
            filtered.append(chunk)
        if len(filtered) >= top_k:
            break

    if not filtered:
        print("[retrieval] No methodology sections found in top results. Falling back to general retrieval.")
        return retrieve(query, store, top_k=top_k)

    return filtered
