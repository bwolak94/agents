"""
Agent memory — persistent per-(session, agent) key-value store in MongoDB.
Agents can read and write facts about the user across conversations.

Memory decay: entries written more than MEMORY_DECAY_DAYS ago are
prefixed with a staleness marker so the LLM can deprioritise them.
"""
import os
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase

_MEMORY_DECAY_DAYS = int(os.getenv("MEMORY_DECAY_DAYS", "30"))
_DECAY_MARKER = "[STALE] "

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def memory_read(session_id: str, agent_type: str) -> str:
    """Return stored memory string for this agent, or empty string.

    Entries older than MEMORY_DECAY_DAYS are prefixed with a staleness marker
    so the LLM naturally deprioritises them without requiring deletion.
    """
    if _db is None:
        return ""
    doc = await _db["agent_memory"].find_one(
        {"session_id": session_id, "agent_type": agent_type},
        {"_id": 0, "memory": 1, "updated_at": 1},
    )
    if not doc:
        return ""
    memory = doc.get("memory", "")
    updated_at_str = doc.get("updated_at", "")
    if updated_at_str and memory:
        try:
            updated_at = datetime.fromisoformat(updated_at_str)
            age_days = (datetime.now(timezone.utc) - updated_at).days
            if age_days > _MEMORY_DECAY_DAYS and not memory.startswith(_DECAY_MARKER):
                memory = _DECAY_MARKER + memory
        except Exception:
            pass
    return memory


async def memory_write(session_id: str, agent_type: str, memory: str) -> None:
    """Overwrite (upsert) memory for this agent."""
    if _db is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    await _db["agent_memory"].update_one(
        {"session_id": session_id, "agent_type": agent_type},
        {"$set": {"memory": memory, "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )


async def memory_append(session_id: str, agent_type: str, fact: str) -> str:
    """Append a fact to existing memory and return the full updated memory."""
    existing = await memory_read(session_id, agent_type)
    updated = (existing + "\n" + fact).strip() if existing else fact
    await memory_write(session_id, agent_type, updated)
    return updated
