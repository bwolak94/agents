"""
REST API — FastAPI.
Run: uvicorn api.server:app --reload --port 8000
"""
import sys
import time
import os
import re
import shutil
import hashlib
import uuid
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import asyncio
import json

from core.orchestrator import AgentOrchestrator
from core.events import event_bus
from core.scheduler import scheduler
from db.history import init_db, load_history, clear_history as db_clear_history, list_sessions as db_list_sessions, load_context
from db import memory as memory_db
from db import analytics as analytics_db
from db import prompts as prompts_db
from config.settings import load_config

logger = logging.getLogger(__name__)

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "/tmp/agent_uploads"))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

config = load_config()

# ─── Rate limiter (#7) ────────────────────────────────────────────────────────
_RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_RPM", "60"))  # requests per minute per IP
_rate_windows: dict[str, list[float]] = defaultdict(list)


# ─── Lifespan (#3 — replaces deprecated @app.on_event("startup")) ─────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_url = config.get("mongo_url", "mongodb://mongo:27017")
    db = await init_db(mongo_url)
    memory_db.set_db(db)
    analytics_db.set_db(db)
    prompts_db.set_db(db)

    # Wire scheduler to the default orchestrator
    default_orch = await get_session("default")
    scheduler.set_handler(
        lambda sid, msg: default_orch.process(message=msg, session_id=sid)
    )
    yield
    # Cleanup on shutdown (connection pools, etc.) can be added here


app = FastAPI(
    title="Agent System API",
    description="Multi-LLM Agent System — Claude, Gemini, Ollama",
    version="2.0.0",
    lifespan=lifespan,
)

# ─── CORS — restrict to configured origins ────────────────────────────────────
_ALLOWED_ORIGINS = [o.strip() for o in os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001"
).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Rate limiting middleware (#7) ────────────────────────────────────────────
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _rate_windows[client_ip]
    # Slide the window: drop entries older than 60 seconds
    _rate_windows[client_ip] = [t for t in window if now - t < 60]
    if len(_rate_windows[client_ip]) >= _RATE_LIMIT_REQUESTS:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please slow down."},
        )
    _rate_windows[client_ip].append(now)
    return await call_next(request)


# ─── Session ID validation helper (#6) ───────────────────────────────────────
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def _validate_session_id(session_id: str) -> str:
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(
            status_code=400,
            detail="session_id must be 1-64 alphanumeric characters, hyphens, or underscores.",
        )
    return session_id


# ─── Sessions ─────────────────────────────────────────────────────────────────
_sessions: dict[str, tuple[AgentOrchestrator, float]] = {}
_session_locks: dict[str, asyncio.Lock] = {}
_request_ids: dict[str, float] = {}  # deduplication: request_id → timestamp
SESSION_TTL = 3600
REQUEST_ID_TTL = 60  # seconds


def _get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


async def get_session(session_id: str) -> AgentOrchestrator:
    now = time.time()
    # Evict expired sessions and their locks (#4)
    expired = [k for k, (_, t) in _sessions.items() if now - t > SESSION_TTL]
    for k in expired:
        del _sessions[k]
        _session_locks.pop(k, None)  # #4 — also evict the lock

    # Evict old request IDs
    old_rids = [k for k, t in _request_ids.items() if now - t > REQUEST_ID_TTL]
    for k in old_rids:
        del _request_ids[k]

    if session_id not in _sessions:
        orch = AgentOrchestrator(config)
        try:
            orch.conversation_history = await load_context(session_id)
        except Exception:
            pass
        _sessions[session_id] = (orch, now)
    else:
        orch, _ = _sessions[session_id]
        _sessions[session_id] = (orch, now)

    return _sessions[session_id][0]


# ─── Request / Response Models ────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    stream: bool = False
    show_routing: bool = False
    request_id: str | None = Field(default=None, description="Idempotency key — prevents duplicate sends")

    # #6 — validate session_id format in the model itself
    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not _SESSION_ID_RE.match(v):
            raise ValueError("session_id must be 1-64 alphanumeric characters, hyphens, or underscores.")
        return v


class ChatResponse(BaseModel):
    response: str
    model_used: str
    agent_used: str
    tools_used: list[str]
    reasoning: str
    duration_ms: int = 0


class PromptSaveRequest(BaseModel):
    session_id: str
    title: str
    content: str
    tags: list[str] = []


class ScheduleRequest(BaseModel):
    session_id: str
    prompt: str
    delay_seconds: float = Field(ge=0, le=86400)


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    orch = await get_session("default")
    return {
        "status": "running",
        "version": "2.0.0",
        "models": orch.llm.available_models(),
        "active_sessions": len(_sessions),
    }


# ─── Chat ─────────────────────────────────────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    # Idempotency — reject duplicate request_ids within TTL
    if req.request_id:
        if req.request_id in _request_ids:
            raise HTTPException(status_code=409, detail="Duplicate request_id — already processed")
        _request_ids[req.request_id] = time.time()

    try:
        # Serialize requests within the same session to prevent race conditions
        async with _get_session_lock(req.session_id):
            orch = await get_session(req.session_id)
            t_start = time.time()
            response = await orch.process(
                message=req.message,
                stream=False,
                show_routing=False,
                session_id=req.session_id,
            )
            # #5 — measure actual duration and pass to analytics
            duration_ms = int((time.time() - t_start) * 1000)

        d = orch.last_decision

        # Record analytics with real duration (#5)
        cost_stats = orch.llm.get_cost_stats()
        try:
            await analytics_db.record_request(
                session_id=req.session_id,
                agent=d.agent if d else "unknown",
                model=d.model if d else "unknown",
                tools=d.tools if d else [],
                duration_ms=duration_ms,
                cost_usd=cost_stats.get("total_cost_usd", 0) if cost_stats else 0,
            )
        except Exception as exc:
            logger.warning("Failed to record analytics: %s", exc)

        return ChatResponse(
            response=response,
            model_used=d.model if d else "unknown",
            agent_used=d.agent if d else "unknown",
            tools_used=d.tools if d else [],
            reasoning=d.reasoning if d else "",
            duration_ms=duration_ms,
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    async def generate():
        # #2 — acquire session lock before processing, same as /chat
        async with _get_session_lock(req.session_id):
            orch = await get_session(req.session_id)
            decision = await orch.router.route(req.message, orch.conversation_history)
            yield f"data: {json.dumps({'type': 'routing', 'model': decision.model, 'agent': decision.agent, 'tools': decision.tools})}\n\n"
            response = await orch.process(req.message, stream=False, show_routing=False, decision=decision, session_id=req.session_id)
        yield f"data: {json.dumps({'type': 'response', 'content': response})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ─── History ──────────────────────────────────────────────────────────────────
@app.get("/history/{session_id}")
async def get_history(session_id: str):
    _validate_session_id(session_id)
    messages = await load_history(session_id)
    return {"session_id": session_id, "messages": messages}


@app.delete("/history/{session_id}")
async def clear_session_history(session_id: str):
    _validate_session_id(session_id)
    await db_clear_history(session_id)
    if session_id in _sessions:
        orch, _ = _sessions[session_id]
        orch.clear_history()
    return {"status": "cleared", "session_id": session_id}


@app.get("/sessions")
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
):
    """#24 — paginated session listing."""
    return {"sessions": await db_list_sessions(limit=limit, skip=skip)}


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    _validate_session_id(session_id)
    if session_id in _sessions:
        del _sessions[session_id]
        _session_locks.pop(session_id, None)
        return {"status": "deleted", "session_id": session_id}
    return {"status": "not_found", "session_id": session_id}


# ─── Stats / Analytics ────────────────────────────────────────────────────────
@app.get("/stats")
async def get_stats(session_id: str = "default"):
    orch = await get_session(session_id)
    return orch.get_stats()


@app.get("/analytics")
async def get_analytics(days: int = Query(default=30, ge=1, le=365)):
    return await analytics_db.get_summary(days)


# ─── Models ───────────────────────────────────────────────────────────────────
@app.get("/models")
async def list_models():
    orch = await get_session("default")
    return {"models": orch.llm.available_models()}


# ─── File Upload ──────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_file(file: UploadFile = File(...), session_id: str = "default"):
    _validate_session_id(session_id)
    if file.size and file.size > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    # #20 — include uuid to prevent silent overwrites of same filename
    file_id = hashlib.sha256(
        f"{session_id}{file.filename}{uuid.uuid4()}".encode()
    ).hexdigest()[:16]
    session_dir = UPLOADS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "upload").suffix
    dest = session_dir / f"{file_id}{suffix}"

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    return {
        "file_id": file_id,
        "filename": file.filename,
        "size": dest.stat().st_size,
        "reference": f"upload::{file_id}",
        "hint": f"Use this in your message: 'Analyse upload::{file_id}'",
    }


@app.get("/uploads/{session_id}")
async def list_uploads(session_id: str):
    _validate_session_id(session_id)
    session_dir = UPLOADS_DIR / session_id
    if not session_dir.exists():
        return {"uploads": []}
    uploads = [
        {"filename": f.name, "size": f.stat().st_size, "reference": f"upload::{f.stem}"}
        for f in session_dir.iterdir() if f.is_file()
    ]
    return {"uploads": uploads}


# ─── Agent Memory ─────────────────────────────────────────────────────────────
@app.get("/memory/{session_id}/{agent_type}")
async def get_memory(session_id: str, agent_type: str):
    _validate_session_id(session_id)
    memory = await memory_db.memory_read(session_id, agent_type)
    return {"session_id": session_id, "agent_type": agent_type, "memory": memory}


@app.delete("/memory/{session_id}/{agent_type}")
async def clear_memory(session_id: str, agent_type: str):
    _validate_session_id(session_id)
    await memory_db.memory_write(session_id, agent_type, "")
    return {"status": "cleared"}


# ─── Prompt Library ───────────────────────────────────────────────────────────
@app.get("/prompts/{session_id}")
async def get_prompts(session_id: str):
    _validate_session_id(session_id)
    return {"prompts": await prompts_db.list_prompts(session_id)}


@app.post("/prompts")
async def save_prompt(req: PromptSaveRequest):
    prompt_id = await prompts_db.save_prompt(req.session_id, req.title, req.content, req.tags)
    return {"prompt_id": prompt_id, "status": "saved"}


@app.delete("/prompts/{session_id}/{prompt_id}")
async def delete_prompt(session_id: str, prompt_id: str):
    _validate_session_id(session_id)
    deleted = await prompts_db.delete_prompt(session_id, prompt_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"status": "deleted"}


# ─── Scheduler ────────────────────────────────────────────────────────────────
@app.post("/schedule")
async def schedule_task(req: ScheduleRequest):
    task_id = scheduler.schedule(req.session_id, req.prompt, req.delay_seconds)
    return {"task_id": task_id, "status": "scheduled", "delay_seconds": req.delay_seconds}


@app.get("/schedule")
async def list_scheduled(session_id: str | None = None):
    return {"tasks": scheduler.list_tasks(session_id)}


@app.get("/schedule/{task_id}")
async def get_scheduled_task(task_id: str):
    # #1 — return the specific task, not the first item in the list
    task = scheduler.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    tasks = scheduler.list_tasks()
    match = next((t for t in tasks if t["task_id"] == task_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Task not found")
    return match


# ─── WebSocket — session-filtered events ──────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time agent events. Pass ?session_id=xxx to filter to your session only."""
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
