"""
Response cache — stores prompt→response pairs with TTL.
Key: SHA-256(model + sorted_messages). TTL configurable via RESPONSE_CACHE_TTL_S env var.

D19 — In-memory LRU layer in front of MongoDB for hot-path reads.
      Cap controlled by LRU_MAX_ITEMS env var (default 500).
"""
import hashlib
import json
import os
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None
_TTL_SECONDS  = int(os.getenv("RESPONSE_CACHE_TTL_S", "3600"))  # 1 hour default
_LRU_MAX      = int(os.getenv("LRU_MAX_ITEMS", "500"))           # D19 — in-memory cap
_mem_cache: OrderedDict[str, str] = OrderedDict()                # D19 — hot LRU dict


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


def _lru_put(key: str, value: str) -> None:
    """D19 — Insert/refresh key in in-memory LRU; evict oldest if over cap."""
    _mem_cache[key] = value
    _mem_cache.move_to_end(key)
    if len(_mem_cache) > _LRU_MAX:
        _mem_cache.popitem(last=False)


async def get(model: str, messages: list, system_prompt: str | None = None) -> str | None:
    """Return cached response or None. D19 — checks in-memory LRU before MongoDB."""
    key = _make_key(model, messages, system_prompt)
    # D19 — hot path: in-memory LRU hit
    if key in _mem_cache:
        _mem_cache.move_to_end(key)
        return _mem_cache[key]
    if _db is None:
        return None
    now = datetime.now(timezone.utc)
    doc = await _db["response_cache"].find_one(
        {"cache_key": key, "expires_at": {"$gt": now}},
        {"_id": 0, "response": 1},
    )
    if doc:
        _lru_put(key, doc["response"])  # D19 — warm the in-memory cache
    return doc["response"] if doc else None


async def put(model: str, messages: list, response: str, system_prompt: str | None = None) -> None:
    """Store a response in the cache. D19 — writes to LRU + MongoDB."""
    key = _make_key(model, messages, system_prompt)
    _lru_put(key, response)  # D19 — write to in-memory LRU
    if _db is None:
        return
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
