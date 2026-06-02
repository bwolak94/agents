"""#9 — Pluggable embedding interface for vector RAG.

Usage:
    from db.embeddings import get_embedder
    embedder = get_embedder()           # auto-selects best available backend
    vec = await embedder.embed("text")  # list[float]

Backends (in order of preference):
1. SentenceTransformers (install: pip install sentence-transformers)
2. OpenAI-compatible embeddings API (set EMBEDDINGS_API_URL + EMBEDDINGS_API_KEY)
3. TF-IDF fallback (no extra deps — uses stdlib only, lower quality)

Set EMBEDDINGS_BACKEND env var to force a specific backend:
    EMBEDDINGS_BACKEND=sentence_transformers
    EMBEDDINGS_BACKEND=api
    EMBEDDINGS_BACKEND=tfidf
"""
import os
import math
import hashlib
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

_EMBEDDINGS_DIM = 384  # default for all-MiniLM-L6-v2


class BaseEmbedder(ABC):
    """Abstract embedding interface."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return a normalized float vector for the given text."""

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts (default: sequential)."""
        return [await self.embed(t) for t in texts]

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


class SentenceTransformersEmbedder(BaseEmbedder):
    """Uses all-MiniLM-L6-v2 (384-dim). Requires: pip install sentence-transformers"""

    _model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore
            model_name = os.getenv("EMBEDDINGS_MODEL", "all-MiniLM-L6-v2")
            self.__class__._model = SentenceTransformer(model_name)

    async def embed(self, text: str) -> list[float]:
        self._load()
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        self._load()
        vecs = self._model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vecs]


class APIEmbedder(BaseEmbedder):
    """Calls an OpenAI-compatible embeddings endpoint.

    Set:
        EMBEDDINGS_API_URL  e.g. https://api.openai.com/v1/embeddings
        EMBEDDINGS_API_KEY  Bearer token
        EMBEDDINGS_MODEL    e.g. text-embedding-3-small
    """

    def __init__(self):
        self.url = os.environ["EMBEDDINGS_API_URL"]
        self.api_key = os.getenv("EMBEDDINGS_API_KEY", "")
        self.model = os.getenv("EMBEDDINGS_MODEL", "text-embedding-3-small")

    async def embed(self, text: str) -> list[float]:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"input": text, "model": self.model},
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]


class TFIDFEmbedder(BaseEmbedder):
    """Deterministic bag-of-words pseudo-embedding. No extra deps — for fallback only.

    Hashes each token into a fixed-dim sparse vector and normalizes it.
    Quality is much lower than real embeddings but allows cosine search without deps.
    """

    DIM = 512

    async def embed(self, text: str) -> list[float]:
        tokens = text.lower().split()
        vec = [0.0] * self.DIM
        for token in tokens:
            idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % self.DIM
            vec[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


# ── Factory ───────────────────────────────────────────────────────────────────

_embedder_instance: BaseEmbedder | None = None


def get_embedder() -> BaseEmbedder:
    """Return the best available embedder (cached singleton)."""
    global _embedder_instance
    if _embedder_instance is not None:
        return _embedder_instance

    backend = os.getenv("EMBEDDINGS_BACKEND", "").lower()

    if backend == "sentence_transformers" or (not backend):
        try:
            import sentence_transformers  # noqa: F401
            _embedder_instance = SentenceTransformersEmbedder()
            logger.info("Embeddings backend: sentence_transformers")
            return _embedder_instance
        except ImportError:
            if backend == "sentence_transformers":
                raise RuntimeError("sentence-transformers not installed. Run: pip install sentence-transformers")

    if backend == "api" or (not backend and os.getenv("EMBEDDINGS_API_URL")):
        try:
            _embedder_instance = APIEmbedder()
            logger.info("Embeddings backend: API (%s)", os.getenv("EMBEDDINGS_API_URL"))
            return _embedder_instance
        except KeyError:
            if backend == "api":
                raise RuntimeError("EMBEDDINGS_API_URL must be set for API backend")

    # Fallback
    logger.warning("Embeddings backend: TF-IDF (fallback — install sentence-transformers for better quality)")
    _embedder_instance = TFIDFEmbedder()
    return _embedder_instance
