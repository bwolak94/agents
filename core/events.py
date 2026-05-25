"""
Session-aware event bus — each WebSocket subscriber can filter by session_id.
"""
import asyncio
from typing import Optional


class EventBus:
    def __init__(self):
        # Maps queue → session_id filter (None = receive all events)
        self._subscribers: dict[asyncio.Queue, Optional[str]] = {}

    def subscribe(self, session_id: Optional[str] = None) -> asyncio.Queue:
        """Subscribe to events. Pass session_id to receive only that session's events."""
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


# Global singleton
event_bus = EventBus()
