"""Request log — persists chat requests for replay and regression testing."""
import uuid

__all__ = ["set_db", "ensure_indexes", "log_request", "list_log", "get_entry"]
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["request_log"].create_index("ts")
    await _db["request_log"].create_index("session_id")
    await _db["request_log"].create_index("entry_id", unique=True)


async def log_request(
    session_id: str,
    message: str,
    model: str,
    response: str,
    duration_ms: int,
) -> str:
    if _db is None:
        return ""
    entry_id = uuid.uuid4().hex
    await _db["request_log"].insert_one({
        "entry_id": entry_id,
        "session_id": session_id,
        "message": message,
        "model": model,
        "response": response,
        "duration_ms": duration_ms,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return entry_id


async def list_log(session_id: str | None = None, limit: int = 50) -> list:
    if _db is None:
        return []
    query = {"session_id": session_id} if session_id else {}
    cursor = _db["request_log"].find(query, {"_id": 0}).sort("ts", -1).limit(limit)
    return await cursor.to_list(limit)


async def get_entry(entry_id: str) -> dict | None:
    if _db is None:
        return None
    return await _db["request_log"].find_one({"entry_id": entry_id}, {"_id": 0})
