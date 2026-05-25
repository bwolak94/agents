"""
Prompt library — save, list, and delete reusable prompts per session.
"""
import uuid
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def save_prompt(session_id: str, title: str, content: str, tags: list[str] | None = None) -> str:
    """Save a prompt and return its ID."""
    if _db is None:
        return ""
    prompt_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await _db["prompts"].insert_one({
        "prompt_id": prompt_id,
        "session_id": session_id,
        "title": title,
        "content": content,
        "tags": tags or [],
        "created_at": now,
        "updated_at": now,
    })
    return prompt_id


async def list_prompts(session_id: str) -> list[dict]:
    """Return all prompts for this session, newest first."""
    if _db is None:
        return []
    cursor = _db["prompts"].find(
        {"session_id": session_id},
        {"_id": 0},
    ).sort("created_at", -1)
    return await cursor.to_list(200)


async def delete_prompt(session_id: str, prompt_id: str) -> bool:
    """Delete a prompt. Returns True if deleted."""
    if _db is None:
        return False
    result = await _db["prompts"].delete_one({"session_id": session_id, "prompt_id": prompt_id})
    return result.deleted_count > 0
