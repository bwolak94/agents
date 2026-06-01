"""WebSocket endpoint — real-time agent event stream."""
import asyncio
import logging
import os
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.events import event_bus

_ws_logger = logging.getLogger("ws")
_SLOW_FRAME_MS = float(os.getenv("WS_SLOW_FRAME_MS", "200"))  # B12

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
    stop_event = asyncio.Event()

    async def _reader():
        """Drain incoming frames (pong / client messages); set stop_event on disconnect."""
        try:
            while not stop_event.is_set():
                await websocket.receive_text()  # blocks until client sends or closes
        except Exception:
            stop_event.set()

    reader_task = asyncio.create_task(_reader())
    try:
        while not stop_event.is_set():
            try:
                event = await asyncio.wait_for(q.get(), timeout=25.0)
                # B12 — Log slow frame dispatch
                t0 = time.perf_counter()
                await websocket.send_json(event)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                if elapsed_ms > _SLOW_FRAME_MS:
                    _ws_logger.debug(
                        "Slow WS frame: %.1fms (session=%s type=%s)",
                        elapsed_ms, session_id, event.get("type", "?"),
                    )
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
            except Exception:
                break
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        stop_event.set()
        reader_task.cancel()
        event_bus.unsubscribe(q)
