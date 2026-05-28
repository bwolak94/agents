"""#20 — Database migrations: idempotent schema changes tracked by version.

Usage (called at startup after init_db):
    from db.migrations import run_migrations
    await run_migrations(db)

Each migration is a coroutine that receives the Motor database object.
Completed migrations are recorded in the 'migrations' collection so they
only run once even if the application is restarted.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ── Migration registry ────────────────────────────────────────────────────────

async def _m001_add_preview_index(db) -> None:
    """Add an index on conversations.preview for sidebar search."""
    await db["conversations"].create_index("preview")


async def _m002_add_session_title_index(db) -> None:
    """Add an index on conversations.title for fast title lookups."""
    await db["conversations"].create_index("title")


async def _m003_analytics_ttl(db) -> None:
    """Ensure analytics records have a TTL index (90 days)."""
    try:
        await db["analytics"].drop_index("ts_1")
    except Exception:
        pass
    await db["analytics"].create_index("ts", expireAfterSeconds=90 * 24 * 3600)


_MIGRATIONS: list[tuple[str, object]] = [
    ("001_add_preview_index",     _m001_add_preview_index),
    ("002_add_session_title_index", _m002_add_session_title_index),
    ("003_analytics_ttl",         _m003_analytics_ttl),
]


# ── Runner ────────────────────────────────────────────────────────────────────

async def run_migrations(db) -> None:
    """Apply any pending migrations in order."""
    col = db["migrations"]
    await col.create_index("name", unique=True)

    applied = {doc["name"] async for doc in col.find({}, {"name": 1})}

    for name, fn in _MIGRATIONS:
        if name in applied:
            continue
        try:
            await fn(db)
            await col.insert_one({
                "name": name,
                "applied_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info("Migration applied: %s", name)
        except Exception:
            logger.exception("Migration failed: %s — skipping", name)
