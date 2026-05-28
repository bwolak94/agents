"""
REST API entry-point — FastAPI application factory.
Run: uvicorn api.server:app --reload --port 8000

Intentionally thin: lifespan, middleware, router registration.
Business logic lives in api/routers/*.  Session state in api/state.
DB module references in api/db (patched by tests at api.db.*).
"""
import asyncio
import logging
import os
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
import sys

_active_tasks: set[asyncio.Task] = set()


def _track_task(coro):
    """Create a tracked background task that cancels cleanly on shutdown."""
    task = asyncio.create_task(coro)
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)
    return task

# Ensure project root is importable in all execution contexts
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.logging import setup_logging
from config.settings import load_config

setup_logging()
logger = logging.getLogger(__name__)

# Keep these module-level imports so tests can patch api.server.init_db / scheduler
from db.history import init_db
from core import scheduler as _sched_mod
from core.scheduler import scheduler  # noqa: F401  — re-exported for test patches
from core.events import event_bus      # noqa: F401
from core.rbac import rbac_middleware

import api.db as _db
import api.state as _state

from api.routers import chat, sessions, knowledge, agents, ops, workflows, ws
from api.routers import multimodal, platform, intelligence
from core import sse as _sse_mod

config = load_config()

# ── Rate limiter ──────────────────────────────────────────────────────────────
_RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_RPM", "60"))
_RATE_WINDOW_MAX_IPS = 10_000
_rate_windows: dict[str, list[float]] = defaultdict(list)

# ── API key auth ──────────────────────────────────────────────────────────────
_API_KEY = os.getenv("API_KEY", "")
_AUTH_SKIP_PREFIXES = ("/docs", "/openapi", "/redoc", "/health")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_url = config["mongo_url"]
    db = await init_db(mongo_url)

    # Wire all DB modules to the shared Motor database (#1 — single loop)
    for mod in _db.ALL_DB_MODULES:
        mod.set_db(db)

    # Ensure indexes best-effort (#1 — single loop from registry)
    for mod in _db.INDEXABLE_DB_MODULES:
        try:
            await mod.ensure_indexes()
        except Exception:
            logger.exception("ensure_indexes failed for %s", mod.__name__ if hasattr(mod, '__name__') else mod)

    # Wire scheduler and warm up Ollama models
    default_orch = await _state.get_session("default")
    _sched_mod.scheduler.set_handler(
        lambda sid, msg: default_orch.process(message=msg, session_id=sid)
    )
    try:
        await default_orch.llm.refresh_ollama_models()
    except Exception:
        logger.debug("Ollama warm-up skipped (not available)")

    yield

    # ── Graceful shutdown: cancel tracked background tasks ────────────────────
    pending = list(_active_tasks)
    if pending:
        logger.info("Cancelling %d active background tasks on shutdown…", len(pending))
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        logger.info("Shutdown complete.")


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


# ── #8 Structured error handler ───────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


# ── Middleware stack ───────────────────────────────────────────────────────────

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not _API_KEY:
        return await call_next(request)
    if any(request.url.path.startswith(p) for p in _AUTH_SKIP_PREFIXES):
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if token != _API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)


app.middleware("http")(rbac_middleware)


_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self' ws: wss:;"
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _rate_windows[client_ip]
    # Slide window: drop timestamps older than 60s
    cutoff = now - 60
    while window and window[0] < cutoff:
        window.pop(0)
    if len(window) >= _RATE_LIMIT_REQUESTS:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please slow down."},
        )
    window.append(now)
    # Evict stale IPs to bound memory
    if len(_rate_windows) > _RATE_WINDOW_MAX_IPS:
        stale = [ip for ip, ts in list(_rate_windows.items()) if not ts]
        for ip in stale:
            del _rate_windows[ip]
    return await call_next(request)


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(ops.router)
app.include_router(chat.router,         tags=["Chat"])
app.include_router(sessions.router,     tags=["Sessions"])
app.include_router(knowledge.router,    tags=["Knowledge"])
app.include_router(agents.router,       tags=["Agents"])
app.include_router(workflows.router,    tags=["Workflows"])
app.include_router(ws.router,           tags=["WebSocket"])
app.include_router(multimodal.router,   tags=["Multimodal"])
app.include_router(platform.router,     tags=["Platform"])
app.include_router(intelligence.router, tags=["Intelligence"])
app.include_router(_sse_mod.router,     tags=["Events"])

# ── /api/v1/* aliases (versioned access) ─────────────────────────────────────
from fastapi import APIRouter as _APIRouter  # noqa: E402
_v1 = _APIRouter(prefix="/api/v1")
_v1.include_router(ops.router)
_v1.include_router(chat.router,         tags=["Chat"])
_v1.include_router(sessions.router,     tags=["Sessions"])
_v1.include_router(knowledge.router,    tags=["Knowledge"])
_v1.include_router(agents.router,       tags=["Agents"])
_v1.include_router(workflows.router,    tags=["Workflows"])
_v1.include_router(multimodal.router,   tags=["Multimodal"])
_v1.include_router(platform.router,     tags=["Platform"])
_v1.include_router(intelligence.router, tags=["Intelligence"])
app.include_router(_v1)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config["api_host"], port=config["api_port"], reload=True)
