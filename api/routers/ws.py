"""WebSocket endpoint — real-time agent event stream."""
import asyncio
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.events import event_bus

router = APIRouter()

# #5 — WebSocket origin validation (opt-in via ALLOWED_ORIGINS env var)
_WS_ALLOWED_ORIGINS: set[str] = {
    o.strip() for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:3001,http://localhost:3003,http://localhost:3004",
    ).split(",") if o.strip()
}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time agent events. Pass ?session_id=xxx to filter to your session."""
    origin = websocket.headers.get("origin", "")
    if origin and _WS_ALLOWED_ORIGINS and origin not in _WS_ALLOWED_ORIGINS:
        await websocket.close(code=1008)  # Policy violation
        return

    session_id = websocket.query_params.get("session_id")
    await websocket.accept()
    q = event_bus.subscribe(session_id=session_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=25.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        event_bus.unsubscribe(q)
