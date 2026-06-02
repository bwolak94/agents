"""BaseRepository — lightweight interface for DB modules (#6).

DB modules are plain modules (not classes) for simplicity and test-patch ergonomics.
This file documents the expected interface as a Protocol so type checkers can
validate conformance without requiring inheritance.
"""
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DbModule(Protocol):
    """Structural protocol every DB module satisfies."""

    def set_db(self, db: Any) -> None:
        """Wire the shared Motor database instance."""
        ...

    async def ensure_indexes(self) -> None:
        """Create collection indexes at startup. No-op if not needed."""
        ...
