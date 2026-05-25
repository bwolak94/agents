"""
Event bus - broadcasts agent events to all subscribers (WebSocket).
"""
import asyncio


class EventBus:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=200)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._queues:
            self._queues.remove(q)

    async def emit(self, event: dict):
        for q in self._queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow subscriber - drop


# Global singleton
event_bus = EventBus()
