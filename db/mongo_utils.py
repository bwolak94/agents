"""
Slow-query logging wrapper for MongoDB collections.

Usage:
    col = SlowQueryCollection(db["conversations"], threshold_ms=100)
    result = await col.find_one({"session_id": sid})
"""
import logging
import os
import time
from typing import Any

logger = logging.getLogger("db.slow_query")

_SLOW_QUERY_THRESHOLD_MS = float(os.getenv("SLOW_QUERY_THRESHOLD_MS", "200"))


class SlowQueryCollection:
    """Thin wrapper around a Motor collection that logs slow queries."""

    def __init__(self, collection, threshold_ms: float = _SLOW_QUERY_THRESHOLD_MS):
        self._col = collection
        self._threshold = threshold_ms / 1000.0  # convert to seconds

    def __getattr__(self, name: str):
        """Proxy all attribute access to the underlying collection."""
        attr = getattr(self._col, name)
        if callable(attr):
            return self._wrap(name, attr)
        return attr

    def _wrap(self, op_name: str, fn):
        """Return an async wrapper that logs if the call exceeds the threshold."""
        import asyncio
        import inspect

        async def _async_wrapper(*args, **kwargs):
            t0 = time.monotonic()
            result = await fn(*args, **kwargs)
            elapsed = time.monotonic() - t0
            if elapsed >= self._threshold:
                logger.warning(
                    "SLOW QUERY [%s.%s] %.0f ms — args=%r",
                    self._col.name, op_name, elapsed * 1000, args[:1],
                )
            return result

        def _sync_wrapper(*args, **kwargs):
            t0 = time.monotonic()
            result = fn(*args, **kwargs)
            elapsed = time.monotonic() - t0
            if elapsed >= self._threshold:
                logger.warning(
                    "SLOW CALL [%s.%s] %.0f ms",
                    self._col.name, op_name, elapsed * 1000,
                )
            return result

        if inspect.iscoroutinefunction(fn):
            return _async_wrapper
        return _sync_wrapper
