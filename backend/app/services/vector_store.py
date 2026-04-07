"""
FAISS vector store for storing and searching problem chunk embeddings.
"""
import json
import os
import numpy as np
import faiss
from app.config import get_settings

settings = get_settings()


class FaissVectorStore:
    """Manages a FAISS index with an ID mapping for chunk retrieval."""

    def __init__(
        self,
        dim: int = None,
        index_path: str = None,
        id_map_path: str = None,
    ):
        self.dim = dim or settings.embedding_dim
        self.index_path = index_path or settings.faiss_index_path
        self.id_map_path = id_map_path or settings.faiss_id_map_path
        self.index: faiss.IndexFlatIP = None  # Inner product (cosine sim on normalized vecs)
        self.id_map: list[str] = []  # Maps FAISS internal index → chunk UUID string

        self._load_or_create()

    def _load_or_create(self):
        """Load existing index or create a new one."""
        if os.path.exists(self.index_path) and os.path.exists(self.id_map_path):
            try:
                self.index = faiss.read_index(self.index_path)
                with open(self.id_map_path, "r") as f:
                    self.id_map = json.load(f)
                print(f"[FAISS] Loaded index with {self.index.ntotal} vectors")
            except Exception as e:
                print(f"[FAISS] Error loading index: {e}. Creating new.")
                self._create_new()
        else:
            self._create_new()

    def _create_new(self):
        """Create a fresh FAISS index."""
        self.index = faiss.IndexFlatIP(self.dim)
        self.id_map = []
        print(f"[FAISS] Created new index with dim={self.dim}")

    def add_vectors(self, embeddings: list[np.ndarray], chunk_ids: list[str]):
        """Add vectors to the index with corresponding chunk IDs."""
        if not embeddings:
            return

        vectors = np.stack(embeddings).astype(np.float32)
        # Ensure normalized
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        vectors = vectors / norms

        start_idx = self.index.ntotal
        self.index.add(vectors)

        for i, chunk_id in enumerate(chunk_ids):
            self.id_map.append(str(chunk_id))

        print(f"[FAISS] Added {len(embeddings)} vectors (total: {self.index.ntotal})")
        return list(range(start_idx, start_idx + len(embeddings)))

    def search(self, query_embedding: np.ndarray, top_k: int = 10) -> list[tuple[str, float]]:
        """
        Search for the most similar vectors.
        Returns list of (chunk_id, score) tuples sorted by similarity.
        """
        if self.index.ntotal == 0:
            return []

        query = query_embedding.reshape(1, -1).astype(np.float32)
        # Normalize query
        norm = np.linalg.norm(query)
        if norm > 0:
            query = query / norm

        k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(query, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.id_map):
                continue
            results.append((self.id_map[idx], float(score)))

        return results

    def save(self):
        """Persist index and ID map to disk."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        faiss.write_index(self.index, self.index_path)
        with open(self.id_map_path, "w") as f:
            json.dump(self.id_map, f)
        print(f"[FAISS] Saved index ({self.index.ntotal} vectors) to {self.index_path}")

    def clear(self):
        """Reset the index."""
        self._create_new()
        self.save()

    @property
    def total_vectors(self) -> int:
        return self.index.ntotal


# Singleton instance
_vector_store: FaissVectorStore | None = None


def get_vector_store() -> FaissVectorStore:
    """Get or create the singleton FAISS vector store."""
    global _vector_store
    if _vector_store is None:
        _vector_store = FaissVectorStore()
    return _vector_store
