"""
Webhook triggers — users register external event sources that auto-dispatch agent tasks.
Each trigger: { url_pattern, event_type, session_id, agent_task_template, active }
"""
import uuid
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["webhook_triggers"].create_index("session_id")
    await _db["webhook_triggers"].create_index("active")


async def create_trigger(
    session_id: str,
    name: str,
    event_type: str,
    task_template: str,
    secret: str = "",
) -> str:
    trigger_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    await _db["webhook_triggers"].insert_one({
        "trigger_id": trigger_id,
        "session_id": session_id,
        "name": name,
        "event_type": event_type,
        "task_template": task_template,
        "secret": secret,
        "active": True,
        "created_at": now,
        "last_fired_at": None,
        "fire_count": 0,
    })
    return trigger_id


async def list_triggers(session_id: str) -> list:
    if _db is None:
        return []
    cursor = _db["webhook_triggers"].find(
        {"session_id": session_id},
        {"_id": 0, "secret": 0},
    ).sort("created_at", -1)
    return await cursor.to_list(length=100)


async def get_trigger(trigger_id: str) -> dict | None:
    if _db is None:
        return None
    return await _db["webhook_triggers"].find_one(
        {"trigger_id": trigger_id}, {"_id": 0}
    )


async def delete_trigger(trigger_id: str) -> bool:
    if _db is None:
        return False
    result = await _db["webhook_triggers"].delete_one({"trigger_id": trigger_id})
    return result.deleted_count > 0


async def record_fire(trigger_id: str) -> None:
    if _db is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    await _db["webhook_triggers"].update_one(
        {"trigger_id": trigger_id},
        {"$set": {"last_fired_at": now}, "$inc": {"fire_count": 1}},
    )
