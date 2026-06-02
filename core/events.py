"""
Session-aware event bus — each WebSocket subscriber can filter by session_id.
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_SUBSCRIBERS = 500  # cap to prevent unbounded growth on rapid reconnects (#19)


class EventBus:
    def __init__(self):
        # Maps queue → session_id filter (None = receive all events)
        self._subscribers: dict[asyncio.Queue, Optional[str]] = {}

    def subscribe(self, session_id: Optional[str] = None) -> asyncio.Queue:
        """Subscribe to events. Pass session_id to receive only that session's events."""
        if len(self._subscribers) >= _MAX_SUBSCRIBERS:
            logger.warning(
                "EventBus subscriber cap (%d) reached — rejecting new subscription",
                _MAX_SUBSCRIBERS,
            )
            raise RuntimeError("Too many WebSocket subscribers — server is at capacity")
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers[q] = session_id
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.pop(q, None)

    async def emit(self, event: dict) -> None:
        event_session = event.get("session_id")
        for q, filter_session in list(self._subscribers.items()):
            # Deliver if: no filter set (global), or event has a session and IDs match
            if filter_session is None or (event_session is not None and filter_session == event_session):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass  # slow subscriber — drop event rather than block

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscriber_count_for(self, session_id: str) -> int:
        """Count subscribers filtering on a specific session_id."""
        return sum(1 for s in self._subscribers.values() if s == session_id)

    async def emit_typing(self, session_id: str) -> None:
        """W21 — Emit a typing indicator so other clients see agent is processing."""
        await self.emit({"type": "typing", "session_id": session_id})

    async def emit_error(self, session_id: str, code: str, message: str) -> None:
        """W23 — Emit a unified structured error event."""
        await self.emit({"type": "error", "code": code, "message": message, "session_id": session_id})


# Global singleton
event_bus = EventBus()
