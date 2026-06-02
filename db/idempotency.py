"""
B3 — Idempotency store: cache Idempotency-Key → response for 24h in MongoDB.
Duplicate POST requests return the stored response instead of re-hitting the LLM.
"""
import os
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None
_TTL_HOURS = int(os.getenv("IDEMPOTENCY_TTL_HOURS", "24"))


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["idempotency"].create_index("key", unique=True)
    await _db["idempotency"].create_index("expires_at", expireAfterSeconds=0)


async def get(key: str) -> dict | None:
    """Return cached response dict or None if not found / expired."""
    if _db is None or not key:
        return None
    now = datetime.now(timezone.utc)
    doc = await _db["idempotency"].find_one(
        {"key": key, "expires_at": {"$gt": now}},
        {"_id": 0, "response": 1},
    )
    return doc["response"] if doc else None


async def store(key: str, response: dict) -> None:
    """Store a response under an idempotency key with TTL."""
    if _db is None or not key:
        return
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=_TTL_HOURS)
    await _db["idempotency"].update_one(
        {"key": key},
        {"$set": {"response": response, "expires_at": expires, "created_at": now}},
        upsert=True,
    )
