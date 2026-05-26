"""
Chat history stored in MongoDB.
Stores full messages (with metadata) per session_id.
"""
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

_client = None
_db = None

# Sessions excluded from the history sidebar (system/library sessions)
_SYSTEM_SESSIONS = {"default"}


async def init_db(mongo_url: str):
    global _client, _db
    _client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
    _db = _client["agent_system"]

    # #9 — verify MongoDB is actually reachable at startup
    await _client.admin.command("ping")

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

    update = {
        "$push": {"messages": msg},
        "$set": {"updated_at": now},
        "$setOnInsert": {"created_at": now},
    }

    # #13 — store preview (first user message, XML tags stripped) for the sidebar
    if role == "user":
        existing = await _db["conversations"].find_one(
            {"session_id": session_id}, {"_id": 0, "preview": 1}
        )
        if not existing or not existing.get("preview"):
            preview = _strip_xml(content)[:100]
            update["$setOnInsert"]["preview"] = preview  # type: ignore[index]

    await _db["conversations"].update_one(
        {"session_id": session_id},
        update,
        upsert=True,
    )


def _strip_xml(text: str) -> str:
    """Remove XML-style tags and return clean preview text."""
    import re
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean if clean else text


async def clear_history(session_id: str):
    await _db["conversations"].delete_one({"session_id": session_id})


async def list_sessions() -> list:
    """Return recent sessions for the chat history sidebar, excluding system sessions."""
    cursor = _db["conversations"].find(
        # #8 — exclude system sessions (prompt library, etc.)
        {"session_id": {"$nin": list(_SYSTEM_SESSIONS)}},
        {"_id": 0, "session_id": 1, "updated_at": 1, "created_at": 1, "preview": 1, "messages": {"$slice": 1}}
    ).sort("updated_at", -1).limit(100)
    docs = await cursor.to_list(length=100)

    result = []
    for doc in docs:
        # Use stored preview field if available (#13), else fall back to first message
        preview = doc.get("preview", "")
        if not preview:
            messages = doc.get("messages", [])
            first_user = next((m for m in messages if m.get("role") == "user"), None)
            raw = first_user["content"] if first_user else "Empty chat"
            preview = _strip_xml(raw)[:100]
        result.append({
            "session_id": doc["session_id"],
            "updated_at": doc.get("updated_at", ""),
            "created_at": doc.get("created_at", ""),
            "preview": preview,
        })
    return result
