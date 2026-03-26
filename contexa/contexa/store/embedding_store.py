"""
Embedding_Store: local vector embeddings for semantic search over contexts.

Uses sentence-transformers for local inference (no API key required).
Embeddings are stored as serialized numpy float32 arrays in the SQLite
`embeddings` table.

If no embedding model is configured, all methods raise EmbeddingDisabledError.
This is an optional feature — the daemon runs fine without it.

Install the optional dependency to enable:
  pip install "contexa[embeddings]"
  # or: pip install sentence-transformers
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from contexa.store.models import EmbeddingRecord


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class EmbeddingDisabledError(Exception):
    """Raised when semantic search is called but no model is configured."""

    def __init__(self) -> None:
        super().__init__(
            "Embedding model not configured. Set [embeddings] model in config.toml "
            "and install sentence-transformers: pip install 'contexa[embeddings]'"
        )


# ---------------------------------------------------------------------------
# Embedding Store
# ---------------------------------------------------------------------------

class EmbeddingStore:
    """Manages vector embeddings for semantic search over context objects.

    Args:
        session: SQLAlchemy session.
        model_name: sentence-transformers model name (e.g. 'all-MiniLM-L6-v2').
                    If empty string or None, embeddings are disabled.
    """

    def __init__(self, session: Session, model_name: str = "") -> None:
        self._session = session
        self._model_name = model_name or ""
        self._model = None  # lazy-loaded on first use

    @property
    def enabled(self) -> bool:
        """Return True if an embedding model is configured."""
        return bool(self._model_name)

    def _get_model(self):
        """Lazy-load the sentence-transformers model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise EmbeddingDisabledError()
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def _encode(self, text: str):
        """Encode text to a normalized float32 numpy vector."""
        import numpy as np
        model = self._get_model()
        vector = model.encode(text, convert_to_numpy=True).astype("float32")
        # Normalize to unit length for cosine similarity via dot product
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        return vector

    def generate_and_store(
        self,
        context_id: str,
        version_tag: str,
        content: dict[str, Any],
    ) -> None:
        """Generate and persist an embedding for a context version.

        Called automatically after each context create/update when enabled.

        Args:
            context_id: UUID of the context.
            version_tag: Version tag of the context version.
            content: The context content dict to embed.

        Raises:
            EmbeddingDisabledError: If no model is configured.
        """
        if not self.enabled:
            raise EmbeddingDisabledError()

        text = json.dumps(content, sort_keys=True, ensure_ascii=False)
        vector = self._encode(text)

        record = EmbeddingRecord(
            embedding_id=str(uuid.uuid4()),
            context_id=context_id,
            version_tag=version_tag,
            model_name=self._model_name,
            vector=vector.tobytes(),
        )
        self._session.add(record)
        self._session.commit()

    def search(
        self,
        query: str,
        top_n: int = 10,
    ) -> list[tuple[str, str, float]]:
        """Find the top-N most semantically similar contexts.

        Args:
            query: Natural language query string.
            top_n: Number of results to return.

        Returns:
            List of (context_id, version_tag, score) tuples ordered by
            descending cosine similarity score.

        Raises:
            EmbeddingDisabledError: If no model is configured.
        """
        if not self.enabled:
            raise EmbeddingDisabledError()

        import numpy as np

        query_vector = self._encode(query)

        # Load all embeddings for latest versions
        records = self._session.query(EmbeddingRecord).all()
        if not records:
            return []

        results = []
        for record in records:
            stored = np.frombuffer(record.vector, dtype="float32")
            score = float(np.dot(query_vector, stored))
            results.append((record.context_id, record.version_tag, score))

        # Sort by descending score and return top-N
        results.sort(key=lambda x: x[2], reverse=True)
        return results[:top_n]

    def get_embedding(self, context_id: str, version_tag: str) -> EmbeddingRecord | None:
        """Return the stored embedding for a specific context version."""
        return (
            self._session.query(EmbeddingRecord)
            .filter_by(context_id=context_id, version_tag=version_tag)
            .first()
        )
