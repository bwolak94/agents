"""
Agent personas — named custom system prompts selectable per session.
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
    await _db["personas"].create_index("name", unique=True)


async def save_persona(name: str, system_prompt: str, description: str = "") -> str:
    if _db is None:
        return ""
    now = datetime.now(timezone.utc).isoformat()
    await _db["personas"].update_one(
        {"name": name},
        {"$set": {"name": name, "system_prompt": system_prompt, "description": description, "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return name


async def get_persona(name: str) -> dict | None:
    if _db is None:
        return None
    return await _db["personas"].find_one({"name": name}, {"_id": 0})


async def list_personas() -> list[dict]:
    if _db is None:
        return []
    cursor = _db["personas"].find({}, {"_id": 0}).sort("name", 1)
    return await cursor.to_list(length=200)


async def delete_persona(name: str) -> bool:
    if _db is None:
        return False
    result = await _db["personas"].delete_one({"name": name})
    return result.deleted_count > 0
