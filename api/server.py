"""
REST API — FastAPI.
Run: uvicorn api.server:app --reload --port 8000
"""
import sys
import time
import os
import shutil
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
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

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "/tmp/agent_uploads"))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Agent System API",
    description="Multi-LLM Agent System — Claude, Gemini, Ollama",
    version="2.0.0",
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

config = load_config()

# ─── Startup ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
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


# ─── Sessions ─────────────────────────────────────────────────────────────────
_sessions: dict[str, tuple[AgentOrchestrator, float]] = {}
_session_locks: dict[str, asyncio.Lock] = {}  # #6 — per-session lock
_request_ids: dict[str, float] = {}  # deduplication: request_id → timestamp
SESSION_TTL = 3600
REQUEST_ID_TTL = 60  # seconds


def _get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


async def get_session(session_id: str) -> AgentOrchestrator:
    now = time.time()
    # Evict expired sessions
    expired = [k for k, (_, t) in _sessions.items() if now - t > SESSION_TTL]
    for k in expired:
        del _sessions[k]

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


class ChatResponse(BaseModel):
    response: str
    model_used: str
    agent_used: str
    tools_used: list[str]
    reasoning: str


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
        # #6 — serialize requests within the same session to prevent race conditions
        async with _get_session_lock(req.session_id):
            orch = await get_session(req.session_id)
            response = await orch.process(
                message=req.message,
                stream=False,
                show_routing=False,
                session_id=req.session_id,
            )
        d = orch.last_decision

        # Record analytics
        cost_stats = orch.llm.get_cost_stats()
        try:
            await analytics_db.record_request(
                session_id=req.session_id,
                agent=d.agent if d else "unknown",
                model=d.model if d else "unknown",
                tools=d.tools if d else [],
                duration_ms=0,
                cost_usd=cost_stats.get("total_cost_usd", 0) if cost_stats else 0,
            )
        except Exception:
            pass

        return ChatResponse(
            response=response,
            model_used=d.model if d else "unknown",
            agent_used=d.agent if d else "unknown",
            tools_used=d.tools if d else [],
            reasoning=d.reasoning if d else "",
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
        orch = await get_session(req.session_id)
        decision = await orch.router.route(req.message, orch.conversation_history)
        yield f"data: {json.dumps({'type': 'routing', 'model': decision.model, 'agent': decision.agent, 'tools': decision.tools})}\n\n"
        response = await orch.process(req.message, stream=False, show_routing=False, decision=decision)
        yield f"data: {json.dumps({'type': 'response', 'content': response})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ─── History ──────────────────────────────────────────────────────────────────
@app.get("/history/{session_id}")
async def get_history(session_id: str):
    messages = await load_history(session_id)
    return {"session_id": session_id, "messages": messages}


@app.delete("/history/{session_id}")
async def clear_session_history(session_id: str):
    await db_clear_history(session_id)
    if session_id in _sessions:
        orch, _ = _sessions[session_id]
        orch.clear_history()
    return {"status": "cleared", "session_id": session_id}


@app.get("/sessions")
async def list_sessions():
    return {"sessions": await db_list_sessions()}


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    if session_id in _sessions:
        del _sessions[session_id]
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
    if file.size and file.size > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    # Stable ID = hash of session + filename
    file_id = hashlib.sha256(f"{session_id}{file.filename}".encode()).hexdigest()[:16]
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
    memory = await memory_db.memory_read(session_id, agent_type)
    return {"session_id": session_id, "agent_type": agent_type, "memory": memory}


@app.delete("/memory/{session_id}/{agent_type}")
async def clear_memory(session_id: str, agent_type: str):
    await memory_db.memory_write(session_id, agent_type, "")
    return {"status": "cleared"}


# ─── Prompt Library ───────────────────────────────────────────────────────────
@app.get("/prompts/{session_id}")
async def get_prompts(session_id: str):
    return {"prompts": await prompts_db.list_prompts(session_id)}


@app.post("/prompts")
async def save_prompt(req: PromptSaveRequest):
    prompt_id = await prompts_db.save_prompt(req.session_id, req.title, req.content, req.tags)
    return {"prompt_id": prompt_id, "status": "saved"}


@app.delete("/prompts/{session_id}/{prompt_id}")
async def delete_prompt(session_id: str, prompt_id: str):
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
    task = scheduler.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return scheduler.list_tasks()[0] if scheduler.list_tasks() else {}


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
