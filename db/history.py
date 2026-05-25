"""
Chat history stored in MongoDB.
Stores full messages (with metadata) per session_id.
"""
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

_client = None
_db = None


async def init_db(mongo_url: str):
    global _client, _db
    _client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
    _db = _client["agent_system"]
    await _db["conversations"].create_index("session_id", unique=True)
    await _db["analytics"].create_index("ts")
    await _db["agent_memory"].create_index([("session_id", 1), ("agent_type", 1)], unique=True)
    await _db["prompts"].create_index([("session_id", 1), ("created_at", -1)])
    return _db


async def load_history(session_id: str) -> list:
    """Return list of messages for display in the UI."""
    doc = await _db["conversations"].find_one(
        {"session_id": session_id},
        {"_id": 0, "messages": 1}
    )
    return doc["messages"] if doc else []


async def load_context(session_id: str) -> list:
    """Return history in {role, content} format for the LLM (without metadata)."""
    messages = await load_history(session_id)
    return [{"role": m["role"], "content": m["content"]} for m in messages]


async def append_message(session_id: str, role: str, content: str, **meta):
    """Append a single message to the session history."""
    msg = {
        "role": role,
        "content": content,
        "ts": datetime.now(timezone.utc).isoformat(),
        **meta,
    }
    now = datetime.now(timezone.utc).isoformat()
    await _db["conversations"].update_one(
        {"session_id": session_id},
        {
            "$push": {"messages": msg},
            "$set": {"updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


async def clear_history(session_id: str):
    await _db["conversations"].delete_one({"session_id": session_id})


async def list_sessions() -> list:
    cursor = _db["conversations"].find(
        {},
        {"_id": 0, "session_id": 1, "updated_at": 1, "created_at": 1, "messages": {"$slice": 3}}
    ).sort("updated_at", -1).limit(100)
    docs = await cursor.to_list(length=100)
    result = []
    for doc in docs:
        messages = doc.get("messages", [])
        # Find first user message for preview title
        first_user = next((m for m in messages if m.get("role") == "user"), None)
        preview = first_user["content"][:80] if first_user else "Empty chat"
        result.append({
            "session_id": doc["session_id"],
            "updated_at": doc.get("updated_at", ""),
            "created_at": doc.get("created_at", ""),
            "preview": preview,
        })
    return result
