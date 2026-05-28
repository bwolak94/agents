"""#19 — BaseRepository: abstract base class for all db modules.

Enforces a consistent interface: set_db / ensure_indexes / list / get / delete.
Concrete db modules can inherit from this and override as needed.
"""
from abc import ABC, abstractmethod
from typing import Any


class BaseRepository(ABC):
    """Minimal interface every DB module must satisfy."""

    def set_db(self, db) -> None:
        """Wire the shared Motor database instance."""
        self._db = db

    async def ensure_indexes(self) -> None:
        """Create collection indexes. Called at startup. No-op by default."""

    @abstractmethod
    async def list_all(self, **kwargs) -> list[dict[str, Any]]:
        """Return all documents (with optional filter kwargs)."""

    async def get(self, key: str, value: Any) -> dict[str, Any] | None:
        """Fetch a single document by field=value. Override for custom logic."""
        raise NotImplementedError

    async def delete(self, key: str, value: Any) -> bool:
        """Delete a document by field=value. Returns True if deleted."""
        raise NotImplementedError
