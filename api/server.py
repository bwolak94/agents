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
from db import feedback as feedback_db
from db import rag as rag_db
from db import file_versions as file_versions_db
from db import cache as cache_db
from db import personas as personas_db
from db import tags as tags_db
from db import agent_checkpoints as agent_checkpoints_db
from db import collab_graph as collab_graph_db
from db import macros as macros_db
from db import batch as batch_db
from db.history import set_session_title, add_auto_tags, get_session_title
from api.preprocessor import preprocess as preprocess_message
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
    feedback_db.set_db(db)
    rag_db.set_db(db)
    file_versions_db.set_db(db)
    cache_db.set_db(db)
    personas_db.set_db(db)
    tags_db.set_db(db)
    agent_checkpoints_db.set_db(db)
    collab_graph_db.set_db(db)
    macros_db.set_db(db)
    batch_db.set_db(db)
    await feedback_db.ensure_indexes()
    await rag_db.ensure_indexes()
    await file_versions_db.ensure_indexes()
    await cache_db.ensure_indexes()
    await personas_db.ensure_indexes()
    await tags_db.ensure_indexes()
    await agent_checkpoints_db.ensure_indexes()
    await collab_graph_db.ensure_indexes()
    await macros_db.ensure_indexes()
    await batch_db.ensure_indexes()
    # Wire scheduler and discover Ollama models
    default_orch = await get_session("default")
    scheduler.set_handler(
        lambda sid, msg: default_orch.process(message=msg, session_id=sid)
    )
    try:
        await default_orch.llm.refresh_ollama_models()
    except Exception:
        pass
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
_RATE_WINDOW_MAX_IPS = 10_000  # cap to avoid unbounded memory growth (#22)

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

    # Evict IPs with empty windows to prevent unbounded dict growth (#22)
    if len(_rate_windows) > _RATE_WINDOW_MAX_IPS:
        stale = [ip for ip, ts in list(_rate_windows.items()) if not ts]
        for ip in stale:
            del _rate_windows[ip]

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


_SESSION_LOCK_TIMEOUT = 30  # seconds before giving up waiting for a session lock


def _get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


async def _acquire_session_lock(session_id: str):
    """Acquire session lock with timeout to prevent deadlocks."""
    lock = _get_session_lock(session_id)
    try:
        await asyncio.wait_for(lock.acquire(), timeout=_SESSION_LOCK_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=503,
            detail=f"Session '{session_id}' is busy. Another request is in progress.",
        )
    return lock


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
    # Imp 7: per-session model preference
    preferred_model: str = ""
    # Feature 3: self-reflection
    enable_reflection: bool = False
    # Feature 6: checkpoint resume
    checkpoint_id: str = ""
    # Feature 8: multimodal
    image_base64: str | None = None
    image_url: str | None = None
    # Active persona name
    persona: str = ""

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
    delay_seconds: float = Field(default=0, ge=0, le=86400)
    interval_seconds: float | None = Field(default=None, ge=10, le=86400)


class FeedbackRequest(BaseModel):
    session_id: str
    message_idx: int = Field(ge=0)
    rating: int = Field(ge=-1, le=1)
    comment: str = ""


class KnowledgeRequest(BaseModel):
    session_id: str
    title: str
    content: str


class CompareRequest(BaseModel):
    message: str
    session_id: str = "default"
    models: list[str] = Field(default_factory=list, description="Models to compare; defaults to all available")

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not _SESSION_ID_RE.match(v):
            raise ValueError("session_id must be 1-64 alphanumeric characters, hyphens, or underscores.")
        return v


class WebhookToolRequest(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,32}$")
    url: str
    method: str = "POST"


class PersonaRequest(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    system_prompt: str
    description: str = ""


class TagRequest(BaseModel):
    session_id: str
    tag: str = Field(min_length=1, max_length=32)


class BroadcastRequest(BaseModel):
    session_ids: list[str]
    message: str

    @field_validator("session_ids")
    @classmethod
    def validate_ids(cls, ids: list[str]) -> list[str]:
        for sid in ids:
            if not _SESSION_ID_RE.match(sid):
                raise ValueError(f"Invalid session_id: {sid}")
        return ids


class AdminKeyRequest(BaseModel):
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None


class StructuredChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    response_schema: dict = Field(default_factory=dict)
    model: str = ""

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not _SESSION_ID_RE.match(v):
            raise ValueError("session_id must be 1-64 alphanumeric characters, hyphens, or underscores.")
        return v


class HandoffPipelineRequest(BaseModel):
    message: str
    session_id: str = "default"
    pipeline: list[dict] = Field(..., description="List of {agent, model, task_template, tools} steps")

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not _SESSION_ID_RE.match(v):
            raise ValueError("session_id must be 1-64 alphanumeric characters, hyphens, or underscores.")
        return v


class DebateRequest(BaseModel):
    topic: str
    session_id: str = "default"
    rounds: int = Field(default=2, ge=1, le=5)
    model_a: str = "claude"
    model_b: str = "gemini"

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not _SESSION_ID_RE.match(v):
            raise ValueError("session_id must be 1-64 alphanumeric characters, hyphens, or underscores.")
        return v


class FanOutRequest(BaseModel):
    message: str
    session_id: str = "default"
    agents: list[str] = Field(default_factory=list)
    model: str = "claude"

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not _SESSION_ID_RE.match(v):
            raise ValueError("session_id must be 1-64 alphanumeric characters, hyphens, or underscores.")
        return v


class AgentSystemPromptRequest(BaseModel):
    system_prompt: str


class MacroRequest(BaseModel):
    name: str = Field(pattern=r"^/?[a-zA-Z_\-]{1,32}$")
    template: str
    description: str = ""


class BatchRequest(BaseModel):
    tasks: list[dict] = Field(..., description="List of {message, session_id} objects")


class VariantsRequest(BaseModel):
    message: str
    session_id: str = "default"
    count: int = Field(default=3, ge=2, le=5)
    temperature: float = Field(default=0.9, ge=0.0, le=2.0)
    model: str = ""

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not _SESSION_ID_RE.match(v):
            raise ValueError("session_id must be 1-64 alphanumeric characters, hyphens, or underscores.")
        return v


class GitDiffRequest(BaseModel):
    diff: str
    session_id: str = "default"
    focus: str = ""  # optional focus: "security", "performance", "style"

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not _SESSION_ID_RE.match(v):
            raise ValueError("session_id must be 1-64 alphanumeric characters, hyphens, or underscores.")
        return v


class SessionFindRequest(BaseModel):
    query: str = Field(..., min_length=1)


class ImportContextRequest(BaseModel):
    summary_only: bool = True


class IncrementalContextRequest(BaseModel):
    context: str = Field(..., min_length=1)


class SessionTitleRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)


# ─── Per-session rate limiting (Imp 19) ───────────────────────────────────────
_SESSION_RATE_LIMIT = int(os.getenv("SESSION_RATE_LIMIT_RPM", "20"))
_session_rate_windows: dict[str, list[float]] = defaultdict(list)

# ─── Max cost guard (Imp 12) ──────────────────────────────────────────────────
_MAX_REQUEST_COST_USD = float(os.getenv("MAX_REQUEST_COST_USD", "0"))  # 0 = disabled

# ─── Background helpers ───────────────────────────────────────────────────────
async def _auto_title_session(session_id: str, first_message: str, orch: AgentOrchestrator) -> None:
    """Generate and save a short session title if one doesn't exist yet."""
    try:
        existing = await get_session_title(session_id)
        if existing:
            return
        title = await orch.llm.call(
            model="claude-haiku",
            messages=[{"role": "user", "content": first_message[:300]}],
            system_prompt="Generate a 4-6 word title for this conversation. Output ONLY the title, no punctuation, no quotes.",
            max_tokens=20,
            temperature=0.3,
        )
        await set_session_title(session_id, title.strip()[:80])
    except Exception:
        pass


async def _auto_tag_session(session_id: str, message: str, response: str, orch: AgentOrchestrator) -> None:
    """Classify session into 1-3 topic tags using haiku."""
    try:
        combined = f"User: {message[:200]}\nAssistant: {response[:200]}"
        tags_raw = await orch.llm.call(
            model="claude-haiku",
            messages=[{"role": "user", "content": combined}],
            system_prompt=(
                "Classify this conversation exchange into 1-3 short topic tags. "
                "Choose from: python, javascript, debugging, refactoring, research, writing, "
                "data, devops, security, api, database, testing, math, general, cli, frontend, backend. "
                "Output ONLY a comma-separated list of tags, e.g.: python,debugging"
            ),
            max_tokens=30,
            temperature=0.1,
        )
        tags = [t.strip().lower() for t in tags_raw.split(",") if t.strip()][:3]
        if tags:
            await add_auto_tags(session_id, tags)
    except Exception:
        pass


# ─── Session incremental context store (in-memory, per orchestrator) ──────────
_session_extra_context: dict[str, list[str]] = {}


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

    # Per-session rate limiting (Imp 19)
    now = time.time()
    _session_rate_windows[req.session_id] = [
        t for t in _session_rate_windows[req.session_id] if now - t < 60
    ]
    if len(_session_rate_windows[req.session_id]) >= _SESSION_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Session rate limit exceeded.")
    _session_rate_windows[req.session_id].append(now)

    # Max cost guard (Imp 12)
    if _MAX_REQUEST_COST_USD > 0:
        try:
            orch_check = await get_session(req.session_id)
            current_cost = orch_check.llm.get_cost_stats().get("total_cost_usd", 0)
            if current_cost >= _MAX_REQUEST_COST_USD:
                raise HTTPException(
                    status_code=402,
                    detail=f"Cost limit reached (${current_cost:.4f} >= ${_MAX_REQUEST_COST_USD:.4f}). Reset the session or increase MAX_REQUEST_COST_USD.",
                )
        except HTTPException:
            raise
        except Exception:
            pass

    try:
        lock = await _acquire_session_lock(req.session_id)
        try:
            orch = await get_session(req.session_id)

            # Persona auto-injection (Imp 8)
            if req.persona:
                try:
                    p = await personas_db.get_persona(req.persona)
                    if p:
                        orch.set_persona(p.get("system_prompt", ""))
                except Exception:
                    pass

            # Preprocessing: macros, @file, model prefix, format detection
            processed_message, model_override = await preprocess_message(req.message)
            if model_override and not req.preferred_model:
                req = req.model_copy(update={"preferred_model": model_override})

            # Multimodal: encode image into message content (Feature 8)
            message = processed_message
            if req.image_base64 or req.image_url:
                import base64
                if req.image_base64:
                    image_bytes = base64.b64decode(req.image_base64)
                else:
                    # Fetch from URL
                    try:
                        import httpx as _httpx
                        async with _httpx.AsyncClient(timeout=10) as c:
                            r = await c.get(req.image_url)
                            image_bytes = r.content
                    except Exception as e:
                        image_bytes = None
                        logger.warning("Failed to fetch image from URL: %s", e)

                # Route to gemini for vision tasks and pass image
                if image_bytes:
                    try:
                        img_response = await orch.llm.clients["gemini"].call(
                            messages=[{"role": "user", "content": message}],
                            system_prompt=None,
                            max_tokens=2048,
                            temperature=0.7,
                            stream=False,
                            image_data=image_bytes,
                        )
                        # Wrap gemini response in orchestrator update
                        await orch._update_history(req.session_id, message, img_response)
                        orch.last_decision = type("D", (), {
                            "model": "gemini", "agent": "general_agent", "tools": [],
                            "reasoning": "multimodal vision routing", "complexity": "medium",
                        })()
                        duration_ms = 0
                        return ChatResponse(
                            response=img_response,
                            model_used="gemini",
                            agent_used="general_agent",
                            tools_used=[],
                            reasoning="multimodal vision routing",
                            duration_ms=0,
                        )
                    except Exception as e:
                        logger.warning("Vision call failed: %s — falling through to text", e)

            t_start = time.time()
            response = await orch.process(
                message=message,
                stream=False,
                show_routing=False,
                session_id=req.session_id,
                preferred_model=req.preferred_model,
                enable_reflection=req.enable_reflection,
                checkpoint_id=req.checkpoint_id,
            )
            duration_ms = int((time.time() - t_start) * 1000)
        finally:
            lock.release()

        d = orch.last_decision
        cost_stats = orch.llm.get_cost_stats()

        # Context window utilization tracking (Imp 14)
        try:
            estimated = orch.llm.estimate_tokens(orch.conversation_history)
            context_limits = {"claude": 190_000, "claude-haiku": 190_000, "gemini": 1_000_000}
            limit = context_limits.get(d.model if d else "claude", 32_000)
            context_pct = round(estimated / limit * 100, 1)
        except Exception:
            context_pct = 0

        try:
            await analytics_db.record_request(
                session_id=req.session_id,
                agent=d.agent if d else "unknown",
                model=d.model if d else "unknown",
                tools=d.tools if d else [],
                duration_ms=duration_ms,
                cost_usd=cost_stats.get("total_cost_usd", 0) if cost_stats else 0,
                context_pct=context_pct,
            )
        except Exception as exc:
            logger.warning("Failed to record analytics: %s", exc)

        # Auto-title: generate title on first message (background task)
        asyncio.create_task(_auto_title_session(req.session_id, message, orch))
        # Auto-tag: classify session topic after each response (background task)
        asyncio.create_task(_auto_tag_session(req.session_id, message, response, orch))

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
        lock = await _acquire_session_lock(req.session_id)
        try:
            orch = await get_session(req.session_id)
            decision = await orch.router.route(req.message, orch.conversation_history)
            response = await orch.process(req.message, stream=False, show_routing=False, decision=decision, session_id=req.session_id)
        finally:
            lock.release()
        # Stream outside the lock so other sessions are not blocked
        yield f"data: {json.dumps({'type': 'routing', 'model': decision.model, 'agent': decision.agent, 'tools': decision.tools})}\n\n"
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


# ─── Feedback (with auto-retry on thumbs-down) ────────────────────────────────
@app.get("/feedback/{session_id}")
async def get_feedback(session_id: str):
    _validate_session_id(session_id)
    return {"session_id": session_id, "feedback": await feedback_db.get_feedback(session_id)}


@app.get("/feedback")
async def feedback_summary():
    return await feedback_db.get_summary()


# ─── Knowledge Base (RAG) ─────────────────────────────────────────────────────
@app.post("/knowledge")
async def add_knowledge(req: KnowledgeRequest):
    chunk_ids = await rag_db.add_document(req.session_id, req.title, req.content)
    return {"chunks": len(chunk_ids), "status": "indexed"}


@app.get("/knowledge/{session_id}")
async def list_knowledge(session_id: str):
    _validate_session_id(session_id)
    return {"documents": await rag_db.list_documents(session_id)}


@app.get("/knowledge/{session_id}/search")
async def search_knowledge(session_id: str, q: str = Query(..., min_length=1)):
    _validate_session_id(session_id)
    results = await rag_db.search(session_id, q)
    return {"results": results}


@app.delete("/knowledge/{session_id}/{doc_id}")
async def delete_knowledge(session_id: str, doc_id: str):
    _validate_session_id(session_id)
    deleted = await rag_db.delete_document(session_id, doc_id)
    return {"deleted_chunks": deleted}


# ─── Model Comparison ─────────────────────────────────────────────────────────
@app.post("/chat/compare")
async def chat_compare(req: CompareRequest):
    orch = await get_session(req.session_id)
    models = req.models or orch.llm.available_models()[:3]

    async def _call_model(model: str):
        try:
            t_start = time.time()
            response = await orch.llm.call(
                model=model,
                messages=[{"role": "user", "content": req.message}],
                max_tokens=1024,
            )
            return {
                "model": model,
                "response": response,
                "duration_ms": int((time.time() - t_start) * 1000),
                "error": None,
            }
        except Exception as e:
            return {"model": model, "response": None, "duration_ms": 0, "error": str(e)}

    results = await asyncio.gather(*[_call_model(m) for m in models])
    return {"message": req.message, "results": list(results)}


# ─── Full-text Search ─────────────────────────────────────────────────────────
@app.get("/search")
async def search_conversations(q: str = Query(..., min_length=1)):
    """Search across all conversation messages."""
    from db.history import _db as hist_db
    if hist_db is None:
        return {"results": []}
    try:
        cursor = hist_db["conversations"].find(
            {"$text": {"$search": q}},
            {"_id": 0, "session_id": 1, "preview": 1, "updated_at": 1, "score": {"$meta": "textScore"}},
        ).sort([("score", {"$meta": "textScore"})]).limit(20)
        results = await cursor.to_list(length=20)
        return {"results": results}
    except Exception:
        # Text index may not exist yet; fall back to regex
        cursor = hist_db["conversations"].find(
            {"messages.content": {"$regex": q, "$options": "i"}},
            {"_id": 0, "session_id": 1, "preview": 1, "updated_at": 1},
        ).limit(20)
        results = await cursor.to_list(length=20)
        return {"results": results}


# ─── Session Export ───────────────────────────────────────────────────────────
@app.get("/history/{session_id}/export")
async def export_session(session_id: str, format: str = Query(default="json", pattern="^(json|md)$")):
    _validate_session_id(session_id)
    messages = await load_history(session_id)
    if format == "md":
        lines = [f"# Chat Export — {session_id}\n"]
        for m in messages:
            role = m.get("role", "unknown").capitalize()
            ts = m.get("ts", "")
            lines.append(f"## {role} {f'({ts[:19]})' if ts else ''}\n\n{m.get('content', '')}\n")
        content = "\n---\n\n".join(lines)
        from fastapi.responses import Response
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{session_id}.md"'},
        )
    from fastapi.responses import Response
    return Response(
        content=json.dumps({"session_id": session_id, "messages": messages}, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{session_id}.json"'},
    )


# ─── Custom Webhook Tools ─────────────────────────────────────────────────────
@app.post("/tools/custom")
async def register_webhook_tool(req: WebhookToolRequest):
    from tools.tools import WebhookTool
    orch = await get_session("default")
    orch.tools.register(req.name, WebhookTool(req.url, req.method))
    return {"status": "registered", "tool_name": req.name}


# ─── Scheduler ────────────────────────────────────────────────────────────────
@app.post("/schedule")
async def schedule_task(req: ScheduleRequest):
    if req.interval_seconds is not None:
        task_id = scheduler.schedule_recurring(req.session_id, req.prompt, req.interval_seconds)
        return {"task_id": task_id, "status": "recurring", "interval_seconds": req.interval_seconds}
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


@app.delete("/schedule/{task_id}")
async def cancel_scheduled_task(task_id: str):
    cancelled = scheduler.cancel_task(task_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "cancelled", "task_id": task_id}


# ─── Response Cache ───────────────────────────────────────────────────────────
@app.get("/cache/stats")
async def cache_stats():
    return await cache_db.stats()


@app.delete("/cache")
async def invalidate_cache(model: str | None = None):
    deleted = await cache_db.invalidate(model)
    return {"deleted": deleted}


# ─── Personas ─────────────────────────────────────────────────────────────────
@app.get("/personas")
async def list_personas():
    return {"personas": await personas_db.list_personas()}


@app.post("/personas")
async def save_persona(req: PersonaRequest):
    await personas_db.save_persona(req.name, req.system_prompt, req.description)
    return {"status": "saved", "name": req.name}


@app.delete("/personas/{name}")
async def delete_persona(name: str):
    deleted = await personas_db.delete_persona(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Persona not found")
    return {"status": "deleted"}


# ─── Tags ─────────────────────────────────────────────────────────────────────
@app.get("/tags")
async def list_all_tags():
    return {"tags": await tags_db.all_tags()}


@app.get("/tags/{session_id}")
async def get_session_tags(session_id: str):
    _validate_session_id(session_id)
    return {"session_id": session_id, "tags": await tags_db.get_tags(session_id)}


@app.post("/tags")
async def add_tag(req: TagRequest):
    _validate_session_id(req.session_id)
    tags = await tags_db.add_tag(req.session_id, req.tag)
    return {"session_id": req.session_id, "tags": tags}


@app.delete("/tags/{session_id}/{tag}")
async def remove_tag(session_id: str, tag: str):
    _validate_session_id(session_id)
    tags = await tags_db.remove_tag(session_id, tag)
    return {"session_id": session_id, "tags": tags}


@app.get("/sessions/by-tag/{tag}")
async def sessions_by_tag(tag: str):
    return {"tag": tag, "sessions": await tags_db.sessions_by_tag(tag)}


# ─── Multi-session Broadcast ──────────────────────────────────────────────────
@app.post("/broadcast")
async def broadcast(req: BroadcastRequest):
    async def _send(session_id: str):
        try:
            orch = await get_session(session_id)
            result = await orch.process(message=req.message, stream=False, session_id=session_id)
            return {"session_id": session_id, "response": result, "error": None}
        except Exception as e:
            return {"session_id": session_id, "response": None, "error": str(e)}

    results = await asyncio.gather(*[_send(sid) for sid in req.session_ids])
    return {"message": req.message, "results": list(results)}


# ─── Conversation Replay ──────────────────────────────────────────────────────
@app.post("/history/{session_id}/replay")
async def replay_session(session_id: str, model: str = Query(...)):
    _validate_session_id(session_id)
    messages = await load_history(session_id)
    user_messages = [m for m in messages if m.get("role") == "user"]
    if not user_messages:
        raise HTTPException(status_code=404, detail="No user messages to replay")

    orch = await get_session("default")
    results = []
    history: list = []
    for msg in user_messages:
        try:
            response = await orch.llm.call(
                model=model,
                messages=history + [{"role": "user", "content": msg["content"]}],
                max_tokens=1024,
            )
            results.append({"user": msg["content"][:200], "response": response, "error": None})
            history.append({"role": "user", "content": msg["content"]})
            history.append({"role": "assistant", "content": response})
        except Exception as e:
            results.append({"user": msg["content"][:200], "response": None, "error": str(e)})
    return {"session_id": session_id, "model": model, "replay": results}


# ─── Admin: API Key Rotation ──────────────────────────────────────────────────
@app.put("/admin/keys")
async def rotate_keys(req: AdminKeyRequest):
    """Hot-swap API keys without restarting. Resets shared httpx clients."""
    orch = await get_session("default")
    updated = []
    if req.anthropic_api_key:
        from llm.manager import AnthropicClient, _anthropic_http_client
        import llm.manager as _llm_mod
        # Close old client and reset
        if _llm_mod._anthropic_http_client and not _llm_mod._anthropic_http_client.is_closed:
            await _llm_mod._anthropic_http_client.aclose()
        _llm_mod._anthropic_http_client = None
        orch.llm.clients["claude"] = AnthropicClient(req.anthropic_api_key)
        # Propagate to all active sessions
        for sid, (s_orch, _) in _sessions.items():
            s_orch.llm.clients["claude"] = AnthropicClient(req.anthropic_api_key)
        updated.append("anthropic")
    if req.gemini_api_key:
        from llm.manager import GeminiClient, _gemini_http_client
        import llm.manager as _llm_mod
        if _llm_mod._gemini_http_client and not _llm_mod._gemini_http_client.is_closed:
            await _llm_mod._gemini_http_client.aclose()
        _llm_mod._gemini_http_client = None
        new_client = GeminiClient(req.gemini_api_key)
        for sid, (s_orch, _) in _sessions.items():
            s_orch.llm.clients["gemini"] = new_client
        updated.append("gemini")
    return {"updated": updated}


# ─── Analytics Export ─────────────────────────────────────────────────────────
@app.get("/analytics/export")
async def export_analytics(days: int = Query(default=30, ge=1, le=365), format: str = Query(default="csv", pattern="^(csv|json)$")):
    data = await analytics_db.get_summary(days)
    if format == "json":
        from fastapi.responses import Response
        return Response(
            content=json.dumps(data, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=\"analytics.json\""},
        )
    # Build CSV
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "key", "value"])
    totals = data.get("totals", {})
    for k, v in totals.items():
        writer.writerow(["totals", k, v])
    for row in data.get("by_agent", []):
        writer.writerow(["by_agent", row.get("agent"), row.get("count")])
    for row in data.get("by_model", []):
        writer.writerow(["by_model", row.get("model"), row.get("count")])
    for row in data.get("daily", []):
        writer.writerow(["daily", row.get("date"), row.get("count")])
    from fastapi.responses import Response
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=\"analytics.csv\""},
    )


# ─── Models (with Ollama refresh) ─────────────────────────────────────────────
@app.post("/models/refresh")
async def refresh_models():
    """Re-discover Ollama models that are installed."""
    orch = await get_session("default")
    models = await orch.llm.refresh_ollama_models()
    return {"ollama_models": models, "all_models": orch.llm.available_models()}


@app.get("/models/health")
async def models_health():
    """Return health status for all models (Imp 6)."""
    orch = await get_session("default")
    return {"health": orch.llm.get_health_status()}


# ─── Structured Output (Feature 4) ────────────────────────────────────────────
@app.post("/chat/structured")
async def chat_structured(req: StructuredChatRequest):
    """Return a JSON response validated against the provided schema."""
    orch = await get_session(req.session_id)
    schema_str = json.dumps(req.response_schema, indent=2) if req.response_schema else ""
    prompt = (
        f"{req.message}\n\nRespond with ONLY valid JSON matching this schema:\n{schema_str}"
        if schema_str
        else req.message
    )
    model = req.model or "claude"
    try:
        response = await orch.llm.call(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.2,
        )
        # Parse and re-serialize to validate JSON
        cleaned = re.sub(r"```(?:json)?\s*", "", response).strip()
        json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if json_match:
            cleaned = json_match.group(0)
        parsed = json.loads(cleaned)
        return {"response": parsed, "model_used": model, "valid": True}
    except json.JSONDecodeError:
        return {"response": response, "model_used": model, "valid": False, "error": "Response was not valid JSON"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Document Q&A (Feature 10) ────────────────────────────────────────────────
@app.post("/chat/rag")
async def chat_rag(req: ChatRequest):
    """Answer a question using only the session's knowledge base."""
    _validate_session_id(req.session_id)
    chunks = await rag_db.search(req.session_id, req.message, limit=5)
    if not chunks:
        return {"response": "No relevant documents found in the knowledge base for this session.", "chunks_used": 0}
    ctx = "\n\n".join(f"[{c['title']}]\n{c['content']}" for c in chunks)
    orch = await get_session(req.session_id)
    from agents.agents import DocumentAgent
    doc_agent = DocumentAgent(orch.llm, orch.tools)
    response = await doc_agent.run(
        message=req.message,
        model="claude",
        tool_names=[],
        conversation_history=[],
        session_id=req.session_id,
        active_persona=f"<context>\n{ctx}\n</context>",
    )
    return {"response": response, "chunks_used": len(chunks)}


# ─── Multi-Agent Fan-Out (Feature 1) ──────────────────────────────────────────
@app.post("/chat/fan-out")
async def chat_fan_out(req: FanOutRequest):
    """Run the same message through multiple specialist agents simultaneously."""
    _validate_session_id(req.session_id)
    from agents.agents import AGENT_REGISTRY
    agents = req.agents or list(AGENT_REGISTRY.keys())[:4]
    orch = await get_session(req.session_id)
    result = await orch.run_fan_out(
        message=req.message,
        agents=agents,
        session_id=req.session_id,
        model=req.model,
    )
    return result


# ─── Agent Handoff Pipeline (Feature 2) ───────────────────────────────────────
@app.post("/chat/pipeline")
async def chat_pipeline(req: HandoffPipelineRequest):
    """Run a sequential agent pipeline where each step's output feeds the next."""
    _validate_session_id(req.session_id)
    orch = await get_session(req.session_id)
    result = await orch.run_pipeline(
        message=req.message,
        pipeline=req.pipeline,
        session_id=req.session_id,
    )
    return {"response": result, "steps": len(req.pipeline)}


# ─── Agent Debate (Feature 5) ─────────────────────────────────────────────────
@app.post("/chat/debate")
async def chat_debate(req: DebateRequest):
    """Run two agents debating a topic for N rounds with a judge."""
    _validate_session_id(req.session_id)
    orch = await get_session(req.session_id)
    result = await orch.run_debate(
        topic=req.topic,
        session_id=req.session_id,
        rounds=req.rounds,
        model_a=req.model_a,
        model_b=req.model_b,
    )
    return {"response": result, "topic": req.topic, "rounds": req.rounds}


# ─── Checkpoints (Feature 6) ──────────────────────────────────────────────────
@app.get("/checkpoints/{session_id}")
async def list_checkpoints(session_id: str):
    _validate_session_id(session_id)
    from db.agent_checkpoints import list_checkpoints as _list
    return {"session_id": session_id, "checkpoints": await _list(session_id)}


@app.delete("/checkpoints/{session_id}/{checkpoint_id}")
async def delete_checkpoint(session_id: str, checkpoint_id: str):
    _validate_session_id(session_id)
    from db.agent_checkpoints import delete_checkpoint as _delete
    deleted = await _delete(session_id, checkpoint_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return {"status": "deleted"}


# ─── Agent Collaboration Graph (Imp 17) ───────────────────────────────────────
@app.get("/agents/collab-graph")
async def agent_collab_graph(session_id: str | None = None):
    from db.collab_graph import get_summary, get_graph
    return {
        "summary": await get_summary(),
        "recent": await get_graph(session_id),
    }


# ─── System Prompt Hot Reload (Imp 18) ────────────────────────────────────────
@app.put("/agents/{agent_name}/system-prompt")
async def set_agent_system_prompt(agent_name: str, req: AgentSystemPromptRequest):
    from agents.agents import AGENT_REGISTRY, set_agent_system_prompt as _set
    if agent_name not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found. Available: {list(AGENT_REGISTRY.keys())}")
    _set(agent_name, req.system_prompt)
    # Clear cached instances so they pick up the override
    for _, (orch, _) in _sessions.items():
        orch._agent_cache.pop(agent_name, None)
    return {"status": "updated", "agent": agent_name}


@app.delete("/agents/{agent_name}/system-prompt")
async def reset_agent_system_prompt(agent_name: str):
    from agents.agents import _system_prompt_overrides
    _system_prompt_overrides.pop(agent_name, None)
    for _, (orch, _) in _sessions.items():
        orch._agent_cache.pop(agent_name, None)
    return {"status": "reset", "agent": agent_name}


# ─── Persona activation per session ───────────────────────────────────────────
# ─── Macros (Feature 1: prompt macros) ───────────────────────────────────────
@app.get("/macros")
async def list_macros():
    return {"macros": await macros_db.list_macros()}


@app.post("/macros")
async def save_macro(req: MacroRequest):
    await macros_db.save_macro(req.name, req.template, req.description)
    return {"status": "saved", "name": req.name}


@app.delete("/macros/{name}")
async def delete_macro(name: str):
    deleted = await macros_db.delete_macro(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Macro not found or is a builtin (cannot delete builtins)")
    return {"status": "deleted", "name": name}


# ─── Chat: prompt variants (Feature 10: parallel variants) ────────────────────
@app.post("/chat/variants")
async def chat_variants(req: VariantsRequest):
    """Run the same prompt N times concurrently with high temperature for variety."""
    orch = await get_session(req.session_id)
    processed, model_override = await preprocess_message(req.message)
    model = req.model or model_override or "claude"

    async def _call_once(idx: int) -> dict:
        try:
            result = await orch.llm.call(
                model=model,
                messages=[{"role": "user", "content": processed}],
                max_tokens=1024,
                temperature=req.temperature,
            )
            return {"variant": idx + 1, "response": result, "error": None}
        except Exception as e:
            return {"variant": idx + 1, "response": None, "error": str(e)}

    results = await asyncio.gather(*[_call_once(i) for i in range(req.count)])
    return {"message": req.message, "model": model, "variants": list(results)}


# ─── Git diff code review (Feature 20) ────────────────────────────────────────
@app.post("/chat/git-diff")
async def chat_git_diff(req: GitDiffRequest):
    """Structured code review of a git diff."""
    if not req.diff.strip():
        raise HTTPException(status_code=400, detail="diff must not be empty")
    focus_hint = f"\n\nFocus especially on: {req.focus}." if req.focus else ""
    prompt = (
        f"Review the following git diff carefully.{focus_hint}\n\n"
        "Provide structured feedback with these sections:\n"
        "1. **Summary** — what changed and why (inferred)\n"
        "2. **Correctness** — logic bugs, off-by-one errors, missing edge cases\n"
        "3. **Security** — injection risks, auth issues, exposed secrets, unsafe operations\n"
        "4. **Performance** — N+1 queries, unnecessary allocations, blocking calls\n"
        "5. **Style** — naming, readability, dead code\n"
        "6. **Tests needed** — what test cases should be added\n"
        "7. **Verdict** — LGTM / Needs changes / Major issues\n\n"
        f"```diff\n{req.diff[:8000]}\n```"
    )
    orch = await get_session(req.session_id)
    response = await orch.llm.call(
        model="claude",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2048,
        temperature=0.2,
    )
    return {"review": response, "session_id": req.session_id}


# ─── Batch processing (Feature 16) ────────────────────────────────────────────
@app.post("/batch")
async def submit_batch(req: BatchRequest):
    """Submit a batch of tasks. Returns batch_id to poll."""
    if not req.tasks:
        raise HTTPException(status_code=400, detail="tasks must not be empty")
    if len(req.tasks) > 50:
        raise HTTPException(status_code=400, detail="max 50 tasks per batch")

    batch_id = await batch_db.create_batch(req.tasks)

    async def _run_batch():
        await batch_db.set_batch_status(batch_id, "running")
        for task in req.tasks:
            msg = task.get("message", "")
            sid = task.get("session_id", "default")
            try:
                processed, model_override = await preprocess_message(msg)
                orch = await get_session(sid)
                response = await orch.process(
                    message=processed,
                    session_id=sid,
                    preferred_model=model_override,
                )
                await batch_db.append_result(batch_id, {
                    "message": msg[:200], "session_id": sid,
                    "response": response, "error": None,
                })
            except Exception as e:
                await batch_db.append_result(batch_id, {
                    "message": msg[:200], "session_id": sid,
                    "response": None, "error": str(e),
                })
        await batch_db.set_batch_status(batch_id, "completed")

    asyncio.create_task(_run_batch())
    return {"batch_id": batch_id, "total": len(req.tasks), "status": "running"}


@app.get("/batch/{batch_id}")
async def get_batch(batch_id: str):
    job = await batch_db.get_batch(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch not found")
    return job


# ─── Smart session resume (Feature 12) ────────────────────────────────────────
@app.post("/sessions/find")
async def find_session(req: SessionFindRequest):
    """Find the most relevant session for a query using full-text search."""
    from db.history import _db as hist_db
    if hist_db is None:
        return {"session_id": None, "sessions": []}
    try:
        cursor = hist_db["conversations"].find(
            {"$text": {"$search": req.query}},
            {"_id": 0, "session_id": 1, "preview": 1, "title": 1, "updated_at": 1,
             "score": {"$meta": "textScore"}},
        ).sort([("score", {"$meta": "textScore"})]).limit(5)
        results = await cursor.to_list(5)
        return {
            "query": req.query,
            "best_match": results[0]["session_id"] if results else None,
            "sessions": results,
        }
    except Exception:
        return {"session_id": None, "sessions": []}


# ─── Cross-session context import (Feature 13) ────────────────────────────────
@app.post("/sessions/{session_id}/import-context/{source_id}")
async def import_context(session_id: str, source_id: str, req: ImportContextRequest):
    """Import key context from another session into this session."""
    _validate_session_id(session_id)
    _validate_session_id(source_id)
    source_history = await load_history(source_id)
    if not source_history:
        raise HTTPException(status_code=404, detail="Source session has no history")

    orch = await get_session(session_id)
    if req.summary_only:
        # Summarize source session and inject as context
        combined = "\n".join(
            f"{m['role'].upper()}: {m['content'][:200]}"
            for m in source_history[-20:]
        )
        try:
            summary = await orch.llm.call(
                model="claude-haiku",
                messages=[{"role": "user", "content": combined}],
                system_prompt="Summarize this conversation in 5 key bullet points. Output ONLY the bullets.",
                max_tokens=300,
                temperature=0.2,
            )
            context_block = f"<imported_context from='{source_id}'>\n{summary}\n</imported_context>"
        except Exception:
            context_block = f"<imported_context from='{source_id}'>\n{combined[:500]}\n</imported_context>"
    else:
        msgs = [{"role": m["role"], "content": m["content"]} for m in source_history[-10:]]
        orch.conversation_history = msgs + orch.conversation_history

    if req.summary_only:
        orch.conversation_history.insert(0, {"role": "user", "content": context_block})
        orch.conversation_history.insert(1, {"role": "assistant", "content": "Understood. I have the context from the imported session."})

    return {"status": "imported", "session_id": session_id, "source_id": source_id, "messages_imported": len(source_history)}


# ─── Incremental context building (Feature 14) ────────────────────────────────
@app.post("/sessions/{session_id}/context")
async def add_incremental_context(session_id: str, req: IncrementalContextRequest):
    """Add context to a session without triggering a response."""
    _validate_session_id(session_id)
    _session_extra_context.setdefault(session_id, []).append(req.context)
    orch = await get_session(session_id)
    # Inject as a silent system message into conversation history
    orch.conversation_history.append({
        "role": "user",
        "content": f"<context_addition>\n{req.context}\n</context_addition>",
    })
    orch.conversation_history.append({
        "role": "assistant",
        "content": "Context noted.",
    })
    return {"status": "added", "session_id": session_id, "total_additions": len(_session_extra_context[session_id])}


@app.get("/sessions/{session_id}/context")
async def get_incremental_context(session_id: str):
    _validate_session_id(session_id)
    return {"session_id": session_id, "context_additions": _session_extra_context.get(session_id, [])}


# ─── Session title management ──────────────────────────────────────────────────
@app.get("/sessions/{session_id}/title")
async def get_title(session_id: str):
    _validate_session_id(session_id)
    title = await get_session_title(session_id)
    return {"session_id": session_id, "title": title}


@app.put("/sessions/{session_id}/title")
async def set_title(session_id: str, req: SessionTitleRequest):
    _validate_session_id(session_id)
    await set_session_title(session_id, req.title)
    return {"status": "updated", "session_id": session_id, "title": req.title}


# ─── Focus mode (Feature 15) ──────────────────────────────────────────────────
_focus_sessions: set[str] = set()


@app.post("/sessions/{session_id}/focus")
async def enable_focus(session_id: str):
    _validate_session_id(session_id)
    _focus_sessions.add(session_id)
    return {"status": "focus_enabled", "session_id": session_id}


@app.delete("/sessions/{session_id}/focus")
async def disable_focus(session_id: str):
    _validate_session_id(session_id)
    _focus_sessions.discard(session_id)
    return {"status": "focus_disabled", "session_id": session_id}


# ─── Auto-retry on thumbs-down (Feature 17) ────────────────────────────────────
@app.post("/feedback")
async def save_feedback(req: FeedbackRequest):
    fid = await feedback_db.save_feedback(req.session_id, req.message_idx, req.rating, req.comment)
    result = {"feedback_id": fid, "status": "saved"}

    # On thumbs-down, fire auto-retry in background
    if req.rating == -1:
        asyncio.create_task(_auto_retry_feedback(req.session_id, req.message_idx, req.comment))

    return result


async def _auto_retry_feedback(session_id: str, message_idx: int, comment: str) -> None:
    """Re-run the original user message with improvement hint after thumbs-down."""
    try:
        messages = await load_history(session_id)
        # Find the user message just before this assistant message
        if message_idx > 0 and message_idx < len(messages):
            # Walk backwards to find the user message
            for i in range(message_idx - 1, -1, -1):
                if messages[i].get("role") == "user":
                    original = messages[i]["content"]
                    improvement = (
                        f"{original}\n\n[Note: A previous answer was rated unsatisfactory"
                        + (f" because: {comment}" if comment else "")
                        + ". Please provide a significantly improved response.]"
                    )
                    orch = await get_session(session_id)
                    await orch.process(message=improvement, session_id=session_id)
                    break
    except Exception:
        pass


# ─── Scheduled daily briefing (Feature 18) ────────────────────────────────────
@app.post("/briefing/schedule")
async def schedule_briefing(
    session_id: str = "default",
    hour: int = Query(default=9, ge=0, le=23),
):
    """Schedule a daily briefing at the specified hour (24h format, UTC)."""
    _validate_session_id(session_id)
    briefing_prompt = (
        "Generate my daily briefing. Include:\n"
        "1. A summary of our recent conversations and any unresolved topics\n"
        "2. Key facts or decisions we made together\n"
        "3. Any suggestions for what to focus on today\n"
        "Keep it concise — 5-10 bullet points."
    )
    # Schedule as a recurring task with ~24h interval
    task_id = scheduler.schedule_recurring(session_id, briefing_prompt, interval_seconds=86400)
    return {"status": "scheduled", "task_id": task_id, "session_id": session_id, "daily_at_hour_utc": hour}


# ─── Expand macro endpoint (for preview) ──────────────────────────────────────
@app.post("/macros/expand")
async def expand_macro_preview(body: dict):
    """Preview what a message looks like after macro expansion."""
    message = body.get("message", "")
    variables = body.get("variables", {})
    processed, model_override = await preprocess_message(message)
    if variables:
        from db.macros import expand_macro
        processed = expand_macro(processed, variables)
    return {"original": message, "expanded": processed, "model_override": model_override}


@app.post("/sessions/{session_id}/persona/{persona_name}")
async def activate_persona(session_id: str, persona_name: str):
    _validate_session_id(session_id)
    p = await personas_db.get_persona(persona_name)
    if not p:
        raise HTTPException(status_code=404, detail="Persona not found")
    orch = await get_session(session_id)
    orch.set_persona(p["system_prompt"])
    return {"status": "activated", "session_id": session_id, "persona": persona_name}


@app.delete("/sessions/{session_id}/persona")
async def deactivate_persona(session_id: str):
    _validate_session_id(session_id)
    orch = await get_session(session_id)
    orch.set_persona("")
    return {"status": "deactivated", "session_id": session_id}


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
