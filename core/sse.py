"""#18 — Server-Sent Events broadcast.

Alternative to WebSocket for clients that prefer SSE (simpler, HTTP/1.1 compatible).

Usage:
    GET /events/stream?session_id=xxx   — subscribe to a filtered stream
    GET /events/stream                  — subscribe to all events

The SSE stream emits the same events as the WebSocket endpoint.
Each event is a JSON object on a `data:` line.
"""
import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from core.events import event_bus

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/events/stream")
async def sse_stream(session_id: str | None = None):
    """Server-Sent Events stream — real-time agent events without WebSocket."""
    q = event_bus.subscribe(session_id=session_id)

    async def generate():
        import json
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield "data: {\"type\": \"ping\"}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
