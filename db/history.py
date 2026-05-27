"""
Chat history stored in MongoDB.
Stores full messages (with metadata) per session_id.
"""
import logging
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

_client = None
_db = None

# Sessions excluded from the history sidebar (system/library sessions)
_SYSTEM_SESSIONS = {"default"}


async def init_db(mongo_url: str):
    """Initialize the MongoDB connection.

    Safe to call multiple times — only initializes once.
    If a previous call failed (connection drop), the guard is reset so a retry
    is possible (#27).
    """
    global _client, _db
    if _db is not None:
        return _db

    # Create a fresh client; store in a local first so _db stays None on failure
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = client["agent_system"]

    # Verify MongoDB is actually reachable at startup; raises on failure
    await client.admin.command("ping")

    # Only commit to globals after a successful ping so callers can retry
    _client = client
    _db = db

    await _db["conversations"].create_index("session_id", unique=True)
    # Full-text search index on message content
    try:
        await _db["conversations"].create_index([("messages.content", "text"), ("preview", "text")])
    except Exception:
        pass  # Index may already exist
    # TTL index: analytics records expire after 90 days (#20).
    # Drop the old non-TTL index first if it exists so we can recreate it.
    try:
        await _db["analytics"].drop_index("ts_1")
    except Exception:
        pass
    await _db["analytics"].create_index("ts", expireAfterSeconds=90 * 24 * 3600)
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


_CONTEXT_MESSAGE_LIMIT = 40  # keep last 40 messages to avoid blowing up the LLM context (#23)


async def load_context(session_id: str, limit: int = _CONTEXT_MESSAGE_LIMIT) -> list:
    """Return history in {role, content} format for the LLM (without metadata)."""
    messages = await load_history(session_id)
    recent = messages[-limit:] if len(messages) > limit else messages
    return [{"role": m["role"], "content": m["content"]} for m in recent]


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

    # Store preview (first user message, XML tags stripped) for the sidebar
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


async def list_sessions(limit: int = 50, skip: int = 0) -> list:
    """Return recent sessions for the chat history sidebar, excluding system sessions.
    #24 — supports cursor-based pagination via limit/skip.
    """
    cursor = _db["conversations"].find(
        {"session_id": {"$nin": list(_SYSTEM_SESSIONS)}},
        {"_id": 0, "session_id": 1, "updated_at": 1, "created_at": 1, "preview": 1, "messages": {"$slice": 1}}
    ).sort("updated_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)

    result = []
    for doc in docs:
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
