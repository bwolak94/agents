"""Message comments — users annotate any message in a session."""
import uuid

__all__ = ["set_db", "ensure_indexes", "add_comment", "list_comments",
           "list_all_for_session", "delete_comment"]
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["comments"].create_index([("session_id", 1), ("message_idx", 1)])
    await _db["comments"].create_index("comment_id", unique=True)


async def add_comment(session_id: str, message_idx: int, author: str, text: str) -> str:
    comment_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    await _db["comments"].insert_one({
        "comment_id": comment_id,
        "session_id": session_id,
        "message_idx": message_idx,
        "author": author,
        "text": text,
        "created_at": now,
    })
    return comment_id


async def list_comments(session_id: str, message_idx: int) -> list:
    if _db is None:
        return []
    cursor = _db["comments"].find(
        {"session_id": session_id, "message_idx": message_idx}, {"_id": 0}
    ).sort("created_at", 1)
    return await cursor.to_list(length=100)


async def list_all_for_session(session_id: str) -> list:
    if _db is None:
        return []
    cursor = _db["comments"].find({"session_id": session_id}, {"_id": 0}).sort("message_idx", 1)
    return await cursor.to_list(length=1000)


async def delete_comment(comment_id: str) -> bool:
    if _db is None:
        return False
    result = await _db["comments"].delete_one({"comment_id": comment_id})
    return result.deleted_count > 0
