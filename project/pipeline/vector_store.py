"""
vector_store.py
---------------
Manages FAISS vector database operations: building, saving, and loading.

Uses fastembed (ONNX runtime) instead of sentence-transformers (PyTorch).
fastembed uses ~80MB RAM vs ~350MB, making it viable on Render's free tier.
"""

import os
import json
import numpy as np
import faiss
from fastembed import TextEmbedding
from typing import TypedDict

from pipeline.chunking import Chunk


# 384-dim, ONNX — same dimensions as all-MiniLM-L6-v2, no PyTorch required
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

DEFAULT_INDEX_PATH = "faiss_index.bin"
DEFAULT_META_PATH = "faiss_metadata.json"


class VectorStore(TypedDict):
    index: faiss.IndexFlatIP
    metadata: list[dict]
    model: TextEmbedding


_model_instance: "TextEmbedding | None" = None

def _get_model() -> TextEmbedding:
    global _model_instance
    if _model_instance is None:
        _model_instance = TextEmbedding(EMBEDDING_MODEL)
    return _model_instance


def _embed(model: TextEmbedding, texts: list[str]) -> np.ndarray:
    """Embed a list of texts and return a float32 numpy array."""
    return np.array(list(model.embed(texts)), dtype=np.float32)


def build_vector_store(chunks: list[Chunk]) -> VectorStore:
    model = _get_model()
    texts = [c["text"] for c in chunks]
    print(f"[vector_store] Encoding {len(texts)} chunks...")
    embeddings = _embed(model, texts)
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
    faiss.write_index(store["index"], index_path)
    with open(meta_path, "w") as f:
        json.dump(store["metadata"], f)
    print(f"[vector_store] Saved index to '{index_path}' and metadata to '{meta_path}'.")


def load_vector_store(
    index_path: str = DEFAULT_INDEX_PATH,
    meta_path: str = DEFAULT_META_PATH,
) -> VectorStore:
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"FAISS index not found: {index_path}")
    if not os.path.exists(meta_path):
        raise FileNotFoundError(f"Metadata file not found: {meta_path}")

    index = faiss.read_index(index_path)
    with open(meta_path) as f:
        metadata = json.load(f)

    model = _get_model()
    print(f"[vector_store] Loaded index with {index.ntotal} vectors.")
    return VectorStore(index=index, metadata=metadata, model=model)
