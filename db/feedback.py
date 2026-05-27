"""
Feedback store — per-message thumbs up/down ratings.
"""
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["feedback"].create_index([("session_id", 1), ("message_idx", 1)])


async def save_feedback(session_id: str, message_idx: int, rating: int, comment: str = "") -> str:
    """Save or update a thumbs rating. rating: 1=up, -1=down."""
    if _db is None:
        return ""
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "session_id": session_id,
        "message_idx": message_idx,
        "rating": rating,
        "comment": comment,
        "ts": now,
    }
    result = await _db["feedback"].update_one(
        {"session_id": session_id, "message_idx": message_idx},
        {"$set": doc},
        upsert=True,
    )
    return str(result.upserted_id or "updated")


async def get_feedback(session_id: str) -> list[dict]:
    """Return all feedback for a session."""
    if _db is None:
        return []
    cursor = _db["feedback"].find(
        {"session_id": session_id},
        {"_id": 0, "session_id": 0},
    ).sort("message_idx", 1)
    return await cursor.to_list(length=1000)


async def get_summary() -> dict:
    """Aggregate global feedback statistics."""
    if _db is None:
        return {"total": 0, "positive": 0, "negative": 0}
    pipeline = [
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "positive": {"$sum": {"$cond": [{"$eq": ["$rating", 1]}, 1, 0]}},
            "negative": {"$sum": {"$cond": [{"$eq": ["$rating", -1]}, 1, 0]}},
        }},
    ]
    cursor = _db["feedback"].aggregate(pipeline)
    rows = await cursor.to_list(1)
    if rows:
        r = rows[0]
        return {"total": r["total"], "positive": r["positive"], "negative": r["negative"]}
    return {"total": 0, "positive": 0, "negative": 0}
