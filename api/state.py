"""
Session lifecycle, per-session rate limiting, and background task helpers.

Design: ``session_manager`` is a module-level singleton.  Tests patch
``api.state.get_session`` to inject mock orchestrators.
"""
import asyncio
import logging
import os
import time
from collections import defaultdict

from fastapi import HTTPException

from config.settings import load_config
from core.orchestrator import AgentOrchestrator

import api.db as _db  # attribute access so patches on api.db.* work

logger = logging.getLogger(__name__)

_SESSION_RATE_LIMIT = int(os.getenv("SESSION_RATE_LIMIT_RPM", "20"))
_MAX_REQUEST_COST_USD = float(os.getenv("MAX_REQUEST_COST_USD", "0"))
# #8 — LRU cap: evict oldest session when limit is hit
_MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "200"))


class SessionManager:
    """Encapsulates all in-process session state (SRP)."""

    SESSION_TTL = 3600
    REQUEST_ID_TTL = 60
    LOCK_TIMEOUT = 30

    def __init__(self) -> None:
        self._config = load_config()
        self._sessions: dict[str, tuple[AgentOrchestrator, float]] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._request_ids: dict[str, float] = {}
        self._session_rate_windows: dict[str, list[float]] = defaultdict(list)
        self._session_extra_context: dict[str, list[str]] = {}
        self._focus_sessions: set[str] = set()

    # ── Lock helpers ──────────────────────────────────────────────────────────

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    async def acquire_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._get_lock(session_id)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=self.LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=503,
                detail=f"Session '{session_id}' is busy. Another request is in progress.",
            )
        return lock

    # ── Session CRUD ──────────────────────────────────────────────────────────

    async def get(self, session_id: str) -> AgentOrchestrator:
        now = time.time()
        # TTL eviction
        expired = [k for k, (_, t) in self._sessions.items() if now - t > self.SESSION_TTL]
        for k in expired:
            del self._sessions[k]
            self._session_locks.pop(k, None)
        # Request-ID eviction
        old_rids = [k for k, t in self._request_ids.items() if now - t > self.REQUEST_ID_TTL]
        for k in old_rids:
            del self._request_ids[k]

        if session_id not in self._sessions:
            # #8 — LRU eviction when at capacity
            if len(self._sessions) >= _MAX_SESSIONS:
                lru_key = min(self._sessions, key=lambda k: self._sessions[k][1])
                del self._sessions[lru_key]
                self._session_locks.pop(lru_key, None)
                logger.debug("LRU evicted session %s (capacity=%d)", lru_key, _MAX_SESSIONS)

            orch = AgentOrchestrator(self._config)
            try:
                orch.conversation_history = await _db.load_context(session_id)
            except Exception:
                pass
            self._sessions[session_id] = (orch, now)
        else:
            orch, _ = self._sessions[session_id]
            self._sessions[session_id] = (orch, now)
        return self._sessions[session_id][0]

    def delete(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            self._session_locks.pop(session_id, None)
            return True
        return False

    def clear_history(self, session_id: str) -> None:
        if session_id in self._sessions:
            orch, _ = self._sessions[session_id]
            orch.clear_history()

    def count(self) -> int:
        return len(self._sessions)

    def iter_orchestrators(self):
        """Yield (session_id, orchestrator) for all live sessions."""
        for sid, (orch, _) in list(self._sessions.items()):
            yield sid, orch

    # ── Rate limiting ─────────────────────────────────────────────────────────

    def check_session_rate_limit(self, session_id: str) -> None:
        now = time.time()
        self._session_rate_windows[session_id] = [
            t for t in self._session_rate_windows[session_id] if now - t < 60
        ]
        if len(self._session_rate_windows[session_id]) >= _SESSION_RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Session rate limit exceeded.")
        self._session_rate_windows[session_id].append(now)

    # ── Idempotency ───────────────────────────────────────────────────────────

    def check_request_id(self, request_id: str) -> None:
        if request_id in self._request_ids:
            raise HTTPException(status_code=409, detail="Duplicate request_id — already processed")
        self._request_ids[request_id] = time.time()

    # ── Cost guard ────────────────────────────────────────────────────────────

    def check_cost_limit(self, orch: AgentOrchestrator) -> None:
        if _MAX_REQUEST_COST_USD <= 0:
            return
        current = orch.llm.get_cost_stats().get("total_cost_usd", 0)
        if current >= _MAX_REQUEST_COST_USD:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Cost limit reached (${current:.4f} >= ${_MAX_REQUEST_COST_USD:.4f}). "
                    "Reset the session or increase MAX_REQUEST_COST_USD."
                ),
            )

    # ── Incremental context ───────────────────────────────────────────────────

    def add_context(self, session_id: str, context: str) -> int:
        self._session_extra_context.setdefault(session_id, []).append(context)
        return len(self._session_extra_context[session_id])

    def get_context(self, session_id: str) -> list[str]:
        return self._session_extra_context.get(session_id, [])

    # ── Focus mode ────────────────────────────────────────────────────────────

    def enable_focus(self, session_id: str) -> None:
        self._focus_sessions.add(session_id)

    def disable_focus(self, session_id: str) -> None:
        self._focus_sessions.discard(session_id)


# ── Module-level singleton and convenience function ───────────────────────────

session_manager = SessionManager()


async def get_session(session_id: str) -> AgentOrchestrator:
    """Module-level shortcut — patched by tests via api.state.get_session."""
    return await session_manager.get(session_id)


# ── Background task helpers (patched by tests) ────────────────────────────────

async def _auto_title_session(session_id: str, first_message: str, orch: AgentOrchestrator) -> None:
    try:
        existing = await _db.get_session_title(session_id)
        if existing:
            return
        title = await orch.llm.call(
            model="claude-haiku",
            messages=[{"role": "user", "content": first_message[:300]}],
            system_prompt="Generate a 4-6 word title for this conversation. Output ONLY the title, no punctuation, no quotes.",
            max_tokens=20,
            temperature=0.3,
        )
        await _db.set_session_title(session_id, title.strip()[:80])
    except Exception:
        logger.debug("_auto_title_session failed for %s", session_id, exc_info=True)


async def _auto_tag_session(session_id: str, message: str, response: str, orch: AgentOrchestrator) -> None:
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
            await _db.add_auto_tags(session_id, tags)
    except Exception:
        logger.debug("_auto_tag_session failed for %s", session_id, exc_info=True)
