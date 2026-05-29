"""Cross-session insights — recurring entities, topics, user knowledge profile."""
from datetime import datetime, timezone

__all__ = ["set_db", "ensure_indexes", "upsert_insight", "list_insights", "delete_insight"]
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["insights"].create_index([("entity", 1), ("insight_type", 1)], unique=True)
    await _db["insights"].create_index("mention_count")


async def upsert_insight(
    entity: str,
    insight_type: str,
    value: str,
    source_session: str,
) -> None:
    if _db is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    await _db["insights"].update_one(
        {"entity": entity, "insight_type": insight_type},
        {
            "$set": {"value": value, "source_session": source_session, "updated_at": now},
            "$inc": {"mention_count": 1},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


async def list_insights(limit: int = 100) -> list:
    if _db is None:
        return []
    cursor = _db["insights"].find({}, {"_id": 0}).sort("mention_count", -1).limit(limit)
    return await cursor.to_list(limit)


async def delete_insight(entity: str, insight_type: str) -> bool:
    if _db is None:
        return False
    result = await _db["insights"].delete_one({"entity": entity, "insight_type": insight_type})
    return result.deleted_count > 0
