"""
REST API entry-point — FastAPI application factory.
Run: uvicorn api.server:app --reload --port 8000

Intentionally thin: lifespan, middleware, router registration.
Business logic lives in api/routers/*.  Session state in api/state.
DB module references in api/db (patched by tests at api.db.*).
"""
import asyncio
import contextvars
import logging
import os
import re
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import httpx

# #21 Correlation-ID context variable — propagated through the async call chain
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")

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
from fastapi.middleware.gzip import GZipMiddleware
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
from api.routers import multimodal, platform, intelligence, webhook_triggers, comments, advanced
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

    # #13 Structured startup log with config summary
    logger.info(
        "Agent System starting — mongo=%s max_sessions=%s rate_limit_rpm=%s cost_budget_usd=%s",
        mongo_url.split("@")[-1] if "@" in mongo_url else mongo_url,
        os.getenv("MAX_SESSIONS", "200"),
        os.getenv("RATE_LIMIT_RPM", "60"),
        os.getenv("COST_BUDGET_USD", "0"),
    )

    # Wire scheduler and warm up Ollama models
    default_orch = await _state.get_session("default")
    _sched_mod.scheduler.set_handler(
        lambda sid, msg: default_orch.process(message=msg, session_id=sid)
    )
    try:
        await default_orch.llm.refresh_ollama_models()
    except Exception:
        logger.debug("Ollama warm-up skipped (not available)")

    # Shared httpx client for all outbound HTTP (webhooks, Ollama, vision) — #1 / #9
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
    )

    # #10 Background purge of expired session role tokens (hourly)
    async def _purge_expired_tokens():
        while True:
            await asyncio.sleep(3600)
            try:
                from db import session_roles as _sr
                purged = await _sr.purge_expired()
                if purged:
                    logger.debug("Purged %d expired session role tokens", purged)
            except Exception:
                logger.debug("Token purge failed", exc_info=True)

    _track_task(_purge_expired_tokens())

    yield

    await app.state.http_client.aclose()

    logger.info("Agent System shutting down cleanly.")
    # ── Graceful shutdown: cancel tracked background tasks ────────────────────
    pending = list(_active_tasks)
    if pending:
        logger.info("Cancelling %d active background tasks on shutdown…", len(pending))
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        logger.info("Shutdown complete.")


# ── App ───────────────────────────────────────────────────────────────────────

_MAX_BODY_BYTES = int(os.getenv("MAX_REQUEST_BODY_BYTES", str(2 * 1024 * 1024)))  # 2 MB

app = FastAPI(
    title="Agent System API",
    description="Multi-LLM Agent System — Claude, Gemini, Ollama",
    version="2.0.0",
    lifespan=lifespan,
)

# GZip compression for responses >512 bytes
app.add_middleware(GZipMiddleware, minimum_size=512)

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
    max_age=86400,  # #9 Cache CORS preflight for 24h
)


# ── #8 Structured error handler ───────────────────────────────────────────────

_ERROR_CODE_MAP: dict[str, str] = {
    "ValueError":          "VALIDATION_ERROR",
    "PermissionError":     "FORBIDDEN",
    "TimeoutError":        "TIMEOUT",
    "asyncio.TimeoutError":"TIMEOUT",
    "HTTPException":       "HTTP_ERROR",
}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    error_code = _ERROR_CODE_MAP.get(type(exc).__name__, "INTERNAL_ERROR")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "type": type(exc).__name__,
            "error_code": error_code,
        },
    )


# ── Middleware stack ───────────────────────────────────────────────────────────

@app.middleware("http")
async def body_size_limit_middleware(request: Request, call_next):
    """Reject requests whose Content-Length exceeds MAX_REQUEST_BODY_BYTES."""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Request body too large (max {_MAX_BODY_BYTES} bytes)", "error_code": "BODY_TOO_LARGE"},
        )
    return await call_next(request)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    # #21 — Set correlation_id in context so it propagates through async tasks
    correlation_id.set(rid)
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


_ADMIN_PATHS = {"/admin", "/debug", "/logs/client-errors"}

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # #26 Vary: Accept-Encoding for correct caching of compressed responses
    response.headers["Vary"] = "Accept-Encoding"
    # #10 Cache-Control: no-store on admin/auth endpoints
    if any(request.url.path.startswith(p) for p in _ADMIN_PATHS):
        response.headers["Cache-Control"] = "no-store"
    return response


# ── #23 Server-Timing headers ─────────────────────────────────────────────────

@app.middleware("http")
async def server_timing_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    response.headers["Server-Timing"] = f"total;dur={elapsed_ms:.1f}"
    response.headers["Timing-Allow-Origin"] = "*"
    return response


# ── #27 Expensive-endpoint rate limiter ───────────────────────────────────────

from config.constants import EXPENSIVE_RATE_LIMIT_RPM as _EXP_RPM, COST_BUDGET_USD as _COST_BUDGET
_EXPENSIVE_PATHS = {"/chat/plan", "/chat/red-team", "/chat/fan-out", "/chat/negotiate"}
_exp_windows: dict[str, list[float]] = defaultdict(list)


@app.middleware("http")
async def expensive_rate_limit_middleware(request: Request, call_next):
    if request.url.path not in _EXPENSIVE_PATHS or request.method != "POST":
        return await call_next(request)
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _exp_windows[client_ip]
    cutoff = now - 60
    while window and window[0] < cutoff:
        window.pop(0)
    if len(window) >= _EXP_RPM:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit for compute-heavy endpoint ({_EXP_RPM} rpm)", "error_code": "EXPENSIVE_RATE_LIMIT"},
        )
    window.append(now)
    return await call_next(request)


# ── #F9 Cost budget guard ─────────────────────────────────────────────────────

_daily_cost_cache: dict[str, float] = {}  # date -> total_cost
_daily_cost_lock = asyncio.Lock()  # #12 prevent race on cache reads/writes


@app.middleware("http")
async def cost_budget_middleware(request: Request, call_next):
    if _COST_BUDGET <= 0 or request.url.path not in {"/chat", "/chat/stream", "/chat/plan", "/chat/red-team"}:
        return await call_next(request)
    today = time.strftime("%Y-%m-%d")
    # #12 asyncio.Lock prevents concurrent cache population races
    async with _daily_cost_lock:
        cached_cost = _daily_cost_cache.get(today, -1.0)
        if cached_cost < 0:
            try:
                from db.analytics import _db as _adb
                if _adb is not None:
                    rows = await _adb["analytics"].aggregate([
                        {"$match": {"date": today}},
                        {"$group": {"_id": None, "total": {"$sum": "$cost_usd"}}},
                    ]).to_list(1)
                    cached_cost = rows[0]["total"] if rows else 0.0
                else:
                    cached_cost = 0.0
            except Exception:
                cached_cost = 0.0
            _daily_cost_cache[today] = cached_cost

    if cached_cost >= _COST_BUDGET:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Daily cost budget ${_COST_BUDGET:.2f} exceeded", "error_code": "BUDGET_EXCEEDED"},
        )
    return await call_next(request)


_PII_ENABLED = os.getenv("PII_REDACTION", "false").lower() == "true"
_PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13}|6(?:011|5\d{2})\d{12})\b"), "[CARD]"),
]
_PII_REDACT_PATHS = {"/chat", "/chat/stream", "/chat/plan", "/chat/simulate"}


@app.middleware("http")
async def pii_redaction_middleware(request: Request, call_next):
    """#20 — Redact PII from request bodies before they reach LLM endpoints."""
    if _PII_ENABLED and request.url.path in _PII_REDACT_PATHS and request.method == "POST":
        try:
            body = await request.body()
            body_text = body.decode("utf-8", errors="replace")
            redacted = body_text
            for pattern, replacement in _PII_PATTERNS:
                redacted = pattern.sub(replacement, redacted)
            if redacted != body_text:
                async def _receive():
                    return {"type": "http.request", "body": redacted.encode("utf-8"), "more_body": False}
                request = Request(request.scope, receive=_receive)
        except Exception:
            pass
    return await call_next(request)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _rate_windows[client_ip]
    # Slide window: drop timestamps older than 60s
    cutoff = now - 60
    while window and window[0] < cutoff:
        window.pop(0)
    remaining = max(0, _RATE_LIMIT_REQUESTS - len(window))
    reset_at = int(window[0] + 60) if window else int(now + 60)
    if len(window) >= _RATE_LIMIT_REQUESTS:
        # #4 Retry-After + #5 X-RateLimit headers on 429
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please slow down."},
            headers={
                "Retry-After": str(reset_at - int(now)),
                "X-RateLimit-Limit": str(_RATE_LIMIT_REQUESTS),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_at),
            },
        )
    window.append(now)
    # Evict stale IPs to bound memory — #28 cap dict size
    if len(_rate_windows) > _RATE_WINDOW_MAX_IPS:
        stale = [ip for ip, ts in list(_rate_windows.items()) if not ts]
        for ip in stale:
            del _rate_windows[ip]
    response = await call_next(request)
    # #5 Add X-RateLimit headers to all responses
    response.headers["X-RateLimit-Limit"] = str(_RATE_LIMIT_REQUESTS)
    response.headers["X-RateLimit-Remaining"] = str(remaining - 1)
    response.headers["X-RateLimit-Reset"] = str(reset_at)
    return response


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(ops.router)
app.include_router(chat.router,         tags=["Chat"])
app.include_router(sessions.router,     tags=["Sessions"])
app.include_router(knowledge.router,    tags=["Knowledge"])
app.include_router(agents.router,       tags=["Agents"])
app.include_router(workflows.router,    tags=["Workflows"])
app.include_router(ws.router,           tags=["WebSocket"])
app.include_router(multimodal.router,          tags=["Multimodal"])
app.include_router(platform.router,            tags=["Platform"])
app.include_router(intelligence.router,        tags=["Intelligence"])
app.include_router(webhook_triggers.router,    tags=["Webhooks"])
app.include_router(comments.router,            tags=["Comments"])
app.include_router(advanced.router,            tags=["Advanced"])
app.include_router(_sse_mod.router,            tags=["Events"])

# ── /api/v1/* aliases (versioned access) ─────────────────────────────────────
from fastapi import APIRouter as _APIRouter  # noqa: E402
_v1 = _APIRouter(prefix="/api/v1")
_v1.include_router(ops.router)
_v1.include_router(chat.router,         tags=["Chat"])
_v1.include_router(sessions.router,     tags=["Sessions"])
_v1.include_router(knowledge.router,    tags=["Knowledge"])
_v1.include_router(agents.router,       tags=["Agents"])
_v1.include_router(workflows.router,    tags=["Workflows"])
_v1.include_router(multimodal.router,          tags=["Multimodal"])
_v1.include_router(platform.router,            tags=["Platform"])
_v1.include_router(intelligence.router,        tags=["Intelligence"])
_v1.include_router(webhook_triggers.router,    tags=["Webhooks"])
_v1.include_router(comments.router,            tags=["Comments"])
_v1.include_router(advanced.router,            tags=["Advanced"])
app.include_router(_v1)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config["api_host"], port=config["api_port"], reload=True)
