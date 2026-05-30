"""
vector_store.py
---------------
Manages FAISS vector database operations: building, saving, and loading.

Embeddings are generated with sentence-transformers (all-MiniLM-L6-v2),
which produces 384-dim vectors — a good balance of speed and quality.

Design note: Uses cosine similarity (IndexFlatIP + L2 normalization) rather
than Euclidean distance, which is the standard and more accurate metric for
sentence embedding comparisons. Metadata is stored in a parallel Python list
since FAISS only stores float vectors.
"""

import os
import json
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from typing import TypedDict

from pipeline.chunking import Chunk


# Model name — can be swapped for a larger model if quality matters more than speed
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Paths for persisting the vector store to disk
DEFAULT_INDEX_PATH = "faiss_index.bin"
DEFAULT_META_PATH = "faiss_metadata.json"


class VectorStore(TypedDict):
    """In-memory representation of the FAISS index and its metadata."""
    index: faiss.IndexFlatIP   # Cosine similarity via inner product on normalized vectors
    metadata: list[dict]       # Parallel list of chunk metadata
    model: SentenceTransformer # Embedding model (kept alive to avoid reload)


def build_vector_store(chunks: list[Chunk]) -> VectorStore:
    """
    Generate embeddings for all chunks and build a FAISS index.

    Vectors are L2-normalized so that inner product == cosine similarity.

    Args:
        chunks: List of Chunk TypedDicts from chunking.py.

    Returns:
        VectorStore with index, metadata, and loaded embedding model.
    """
    print(f"[vector_store] Loading embedding model '{EMBEDDING_MODEL}'...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    texts = [c["text"] for c in chunks]
    print(f"[vector_store] Encoding {len(texts)} chunks...")
    embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True).astype(np.float32)

    # Normalize to unit vectors so inner product equals cosine similarity
    faiss.normalize_L2(embeddings)

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    metadata = [{"chunk_id": c["chunk_id"], "section": c["section"], "text": c["text"]} for c in chunks]

    print(f"[vector_store] Built FAISS index with {index.ntotal} vectors (dim={dim}, metric=cosine).")
    return VectorStore(index=index, metadata=metadata, model=model)


def save_vector_store(
    store: VectorStore,
    index_path: str = DEFAULT_INDEX_PATH,
    meta_path: str = DEFAULT_META_PATH,
) -> None:
    """
    Persist the FAISS index and metadata to disk.

    Args:
        store: In-memory VectorStore.
        index_path: File path for the FAISS binary index.
        meta_path: File path for the JSON metadata.
    """
    faiss.write_index(store["index"], index_path)
    with open(meta_path, "w") as f:
        json.dump(store["metadata"], f)
    print(f"[vector_store] Saved index to '{index_path}' and metadata to '{meta_path}'.")


def load_vector_store(
    index_path: str = DEFAULT_INDEX_PATH,
    meta_path: str = DEFAULT_META_PATH,
) -> VectorStore:
    """
    Load a persisted FAISS index and metadata from disk.

    Args:
        index_path: File path of the saved FAISS binary index.
        meta_path: File path of the saved JSON metadata.

    Returns:
        Populated VectorStore ready for querying.

    Raises:
        FileNotFoundError: If either file is missing.
    """
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"FAISS index not found: {index_path}")
    if not os.path.exists(meta_path):
        raise FileNotFoundError(f"Metadata file not found: {meta_path}")

    index = faiss.read_index(index_path)
    with open(meta_path) as f:
        metadata = json.load(f)

    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"[vector_store] Loaded index with {index.ntotal} vectors.")
    return VectorStore(index=index, metadata=metadata, model=model)
