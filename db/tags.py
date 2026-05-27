"""
Conversation tags — attach labels to sessions for organisation.
"""
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["conversations"].create_index("tags")


async def add_tag(session_id: str, tag: str) -> list[str]:
    if _db is None:
        return []
    await _db["conversations"].update_one(
        {"session_id": session_id},
        {"$addToSet": {"tags": tag.strip().lower()}},
        upsert=True,
    )
    return await get_tags(session_id)


async def remove_tag(session_id: str, tag: str) -> list[str]:
    if _db is None:
        return []
    await _db["conversations"].update_one(
        {"session_id": session_id},
        {"$pull": {"tags": tag.strip().lower()}},
    )
    return await get_tags(session_id)


async def get_tags(session_id: str) -> list[str]:
    if _db is None:
        return []
    doc = await _db["conversations"].find_one({"session_id": session_id}, {"_id": 0, "tags": 1})
    return doc.get("tags", []) if doc else []


async def sessions_by_tag(tag: str, limit: int = 50) -> list[str]:
    """Return session_ids that have the given tag."""
    if _db is None:
        return []
    cursor = _db["conversations"].find(
        {"tags": tag.strip().lower()},
        {"_id": 0, "session_id": 1},
    ).limit(limit)
    docs = await cursor.to_list(length=limit)
    return [d["session_id"] for d in docs]


async def all_tags() -> list[str]:
    """Return all distinct tags across all sessions."""
    if _db is None:
        return []
    result = await _db["conversations"].distinct("tags")
    return sorted(t for t in result if t)
