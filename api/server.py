"""
REST API entry-point — FastAPI application factory.
Run: uvicorn api.server:app --reload --port 8000

This module is intentionally thin: lifespan, middleware, and router registration.
Business logic lives in api/routers/*.  Session state lives in api/state.
DB module references live in api/db (patched by tests at api.db.*).
"""
import os
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Keep these module-level imports so tests can patch api.server.init_db / api.server.scheduler
from db.history import init_db
from core import scheduler as _sched_mod
from core.scheduler import scheduler  # noqa: F401  — re-exported for test patches
from core.events import event_bus  # noqa: F401
from config.settings import load_config

import api.db as _db
import api.state as _state

from api.routers import chat, sessions, knowledge, agents, ops, workflows, ws

config = load_config()

# ── Rate limiter state (kept here so tests can access api.server._rate_windows) ──
_RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_RPM", "60"))
_RATE_WINDOW_MAX_IPS = 10_000
_rate_windows: dict[str, list[float]] = defaultdict(list)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_url = config.get("mongo_url", "mongodb://mongo:27017")
    db = await init_db(mongo_url)

    # Wire all DB modules to the same Motor database
    for mod in (
        _db.memory_db, _db.analytics_db, _db.prompts_db, _db.feedback_db,
        _db.rag_db, _db.file_versions_db, _db.cache_db, _db.personas_db,
        _db.tags_db, _db.agent_checkpoints_db, _db.collab_graph_db,
        _db.macros_db, _db.batch_db, _db.workflows_db, _db.experiments_db,
        _db.prompt_versions_db, _db.tenants_db,
    ):
        mod.set_db(db)

    # Ensure indexes (best-effort)
    for mod in (
        _db.workflows_db, _db.experiments_db, _db.prompt_versions_db, _db.tenants_db,
        _db.feedback_db, _db.rag_db, _db.file_versions_db, _db.cache_db,
        _db.personas_db, _db.tags_db, _db.agent_checkpoints_db,
        _db.collab_graph_db, _db.macros_db, _db.batch_db,
    ):
        await mod.ensure_indexes()

    # Wire scheduler and warm up Ollama models
    default_orch = await _state.get_session("default")
    _sched_mod.scheduler.set_handler(
        lambda sid, msg: default_orch.process(message=msg, session_id=sid)
    )
    try:
        await default_orch.llm.refresh_ollama_models()
    except Exception:
        pass

    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Agent System API",
    description="Multi-LLM Agent System — Claude, Gemini, Ollama",
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────

_ALLOWED_ORIGINS = [o.strip() for o in os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:3001,http://localhost:3003,http://localhost:3004",
).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Rate limiting middleware ───────────────────────────────────────────────────

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    _rate_windows[client_ip] = [t for t in _rate_windows[client_ip] if now - t < 60]
    if len(_rate_windows[client_ip]) >= _RATE_LIMIT_REQUESTS:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please slow down."},
        )
    _rate_windows[client_ip].append(now)
    if len(_rate_windows) > _RATE_WINDOW_MAX_IPS:
        stale = [ip for ip, ts in list(_rate_windows.items()) if not ts]
        for ip in stale:
            del _rate_windows[ip]
    return await call_next(request)


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(ops.router)       # includes GET /
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(knowledge.router)
app.include_router(agents.router)
app.include_router(workflows.router)
app.include_router(ws.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
