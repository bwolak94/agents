"""
Response cache — stores prompt→response pairs with TTL.
Key: SHA-256(model + sorted_messages). TTL configurable via RESPONSE_CACHE_TTL_S env var.
"""
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None
_TTL_SECONDS = int(os.getenv("RESPONSE_CACHE_TTL_S", "3600"))  # 1 hour default


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["response_cache"].create_index("cache_key", unique=True)
    await _db["response_cache"].create_index("expires_at", expireAfterSeconds=0)


def _make_key(model: str, messages: list, system_prompt: str | None) -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "system": system_prompt},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def get(model: str, messages: list, system_prompt: str | None = None) -> str | None:
    """Return cached response or None."""
    if _db is None:
        return None
    key = _make_key(model, messages, system_prompt)
    now = datetime.now(timezone.utc)
    doc = await _db["response_cache"].find_one(
        {"cache_key": key, "expires_at": {"$gt": now}},
        {"_id": 0, "response": 1},
    )
    return doc["response"] if doc else None


async def put(model: str, messages: list, response: str, system_prompt: str | None = None) -> None:
    """Store a response in the cache."""
    if _db is None:
        return
    key = _make_key(model, messages, system_prompt)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=_TTL_SECONDS)
    await _db["response_cache"].update_one(
        {"cache_key": key},
        {"$set": {"response": response, "expires_at": expires, "model": model, "created_at": now}},
        upsert=True,
    )


async def invalidate(model: str | None = None) -> int:
    """Delete cache entries, optionally filtered by model."""
    if _db is None:
        return 0
    query = {"model": model} if model else {}
    result = await _db["response_cache"].delete_many(query)
    return result.deleted_count


async def stats() -> dict:
    """Return cache hit statistics."""
    if _db is None:
        return {"total": 0}
    now = datetime.now(timezone.utc)
    total = await _db["response_cache"].count_documents({})
    active = await _db["response_cache"].count_documents({"expires_at": {"$gt": now}})
    return {"total": total, "active": active, "ttl_seconds": _TTL_SECONDS}
