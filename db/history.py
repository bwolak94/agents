"""
Chat history stored in MongoDB.
Stores full messages (with metadata) per session_id.
"""
import logging
import os
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

_client = None
_db = None

# Sessions excluded from the history sidebar (system/library sessions)
_SYSTEM_SESSIONS = {"default"}


_MONGO_MAX_POOL     = int(os.getenv("MONGO_MAX_POOL_SIZE", "20"))
_MONGO_MIN_POOL     = int(os.getenv("MONGO_MIN_POOL_SIZE", "5"))
_SESSION_TTL_DAYS   = int(os.getenv("SESSION_TTL_DAYS", "90"))
_MONGO_WRITE_CONCERN = os.getenv("MONGO_WRITE_CONCERN", "majority")  # D18
_MAX_MESSAGES       = int(os.getenv("MAX_MESSAGES_PER_SESSION", "2000"))  # D12
_READ_CONCERN       = os.getenv("MONGO_READ_CONCERN", "local")  # D15: "local" or "majority"


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
    client = AsyncIOMotorClient(
        mongo_url,
        serverSelectionTimeoutMS=5000,
        maxPoolSize=_MONGO_MAX_POOL,
        minPoolSize=_MONGO_MIN_POOL,
        connectTimeoutMS=5000,
        socketTimeoutMS=30_000,
        retryWrites=True,
        w=_MONGO_WRITE_CONCERN,  # D18 — configurable write concern
    )
    db = client["agent_system"]

    # Verify MongoDB is actually reachable at startup; raises on failure
    await client.admin.command("ping")

    # Only commit to globals after a successful ping so callers can retry
    _client = client
    _db = db

    await _db["conversations"].create_index("session_id", unique=True)
    # TTL: auto-delete stale sessions after SESSION_TTL_DAYS of inactivity
    try:
        await _db["conversations"].drop_index("updated_at_ttl_1")
    except Exception:
        pass
    await _db["conversations"].create_index(
        "updated_at",
        expireAfterSeconds=_SESSION_TTL_DAYS * 24 * 3600,
        name="updated_at_ttl_1",
    )
    # #21 — Sparse indexes: skip docs that lack these optional fields
    try:
        await _db["conversations"].create_index("title", sparse=True)
    except Exception:
        pass
    try:
        await _db["conversations"].create_index("auto_tags", sparse=True)
    except Exception:
        pass
    # #28 — Compound index for "last user message" lookup (auto-title/tag, snapshots)
    try:
        await _db["conversations"].create_index(
            [("session_id", 1), ("messages.role", 1), ("messages.ts", -1)],
            name="session_role_ts",
        )
    except Exception:
        pass
    # #23 — Collation-aware text search index (case-insensitive, locale en)
    try:
        await _db["conversations"].create_index(
            [("messages.content", "text"), ("preview", "text"), ("title", "text")],
            default_language="english",
        )
    except Exception:
        pass  # index may already exist
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


def reset_db() -> None:
    """#11 — Reset module-level DB state. For use in tests only."""
    global _client, _db
    _client = None
    _db = None


async def load_history(session_id: str, tail: int | None = None) -> list:
    """Return list of messages for display in the UI.

    D16 — ``tail`` uses a ``$slice`` projection to load only the last N messages
    without fetching the entire conversation array.
    """
    projection: dict = {"_id": 0, "messages": 1}
    if tail is not None:
        projection["messages"] = {"$slice": -tail}
    # D15 — use configurable read concern for critical history reads
    try:
        from pymongo import ReadPreference as _RP
        _coll = _db.get_collection("conversations", read_concern=__import__("pymongo").ReadConcern(_READ_CONCERN))
    except Exception:
        _coll = _db["conversations"]
    doc = await _coll.find_one({"session_id": session_id}, projection)
    return doc["messages"] if doc else []


_CONTEXT_MESSAGE_LIMIT = 40  # keep last 40 messages to avoid blowing up the LLM context (#23)


async def load_context(session_id: str, limit: int = _CONTEXT_MESSAGE_LIMIT) -> list:
    """Return history in {role, content} format for the LLM (without metadata)."""
    messages = await load_history(session_id)
    recent = messages[-limit:] if len(messages) > limit else messages
    return [{"role": m["role"], "content": m["content"]} for m in recent]


import hashlib as _hashlib


async def append_message(session_id: str, role: str, content: str, **meta):
    """Append a single message to the session history.

    D17 — Eliminated a separate ``find_one`` for preview by using ``$setOnInsert``
    exclusively: preview is written only when the document is first created (upsert),
    removing one round-trip on every message append.

    D12 — Before pushing, check the last message's content hash to prevent
    double-writes from idempotent retries.
    """
    # D12 — compute content hash for dedup check
    _content_hash = _hashlib.md5(f"{role}:{content}".encode()).hexdigest()

    # D12 — skip if the last stored message is identical (same role + content hash)
    existing = await _db["conversations"].find_one(
        {"session_id": session_id, "messages": {"$exists": True}},
        {"_id": 0, "messages": {"$slice": -1}},
    )
    if existing:
        last = existing.get("messages", [{}])[-1]
        if last.get("_hash") == _content_hash:
            return  # duplicate — skip

    msg = {
        "role": role,
        "content": content,
        "ts": datetime.now(timezone.utc).isoformat(),
        "_hash": _content_hash,
        **meta,
    }
    now = datetime.now(timezone.utc).isoformat()

    set_on_insert: dict = {"created_at": now}
    # D17 — preview only on new document creation; no extra find_one needed
    if role == "user":
        set_on_insert["preview"] = _strip_xml(content)[:100]

    # D12 — cap messages array with $slice to prevent unbounded growth
    await _db["conversations"].update_one(
        {"session_id": session_id},
        {
            "$push": {"messages": {"$each": [msg], "$slice": -_MAX_MESSAGES}},
            "$set":  {"updated_at": now},
            "$setOnInsert": set_on_insert,
        },
        upsert=True,
    )


def _strip_xml(text: str) -> str:
    """Remove XML-style tags and return clean preview text."""
    import re
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean if clean else text


async def set_session_title(session_id: str, title: str) -> None:
    """Update the human-readable title for a session."""
    await _db["conversations"].update_one(
        {"session_id": session_id},
        {"$set": {"title": title, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


async def get_session_title(session_id: str) -> str:
    doc = await _db["conversations"].find_one({"session_id": session_id}, {"_id": 0, "title": 1})
    return doc.get("title", "") if doc else ""


async def add_auto_tags(session_id: str, tags: list[str]) -> None:
    """Add auto-generated tags (prefixed 'auto:') without overwriting manual tags."""
    auto_tags = [f"auto:{t}" for t in tags]
    await _db["conversations"].update_one(
        {"session_id": session_id},
        {"$addToSet": {"auto_tags": {"$each": auto_tags}}},
        upsert=True,
    )


async def clear_history(session_id: str):
    await _db["conversations"].delete_one({"session_id": session_id})


async def list_sessions(limit: int = 50, skip: int = 0, after: str | None = None) -> list:
    """Return recent sessions for the chat history sidebar, excluding system sessions.

    Supports two pagination modes:
    - ``skip`` (legacy): offset-based, fine for small collections.
    - ``after`` (cursor-based): pass the ``updated_at`` value of the last item seen
      for efficient keyset pagination — avoids full-collection scans on large datasets.
    """
    base_filter: dict = {"session_id": {"$nin": list(_SYSTEM_SESSIONS)}}
    if after:
        base_filter["updated_at"] = {"$lt": after}

    from pymongo import DESCENDING
    # #11 — add _id as tiebreaker so concurrent inserts don't cause page drift
    cursor = _db["conversations"].find(
        base_filter,
        {"_id": 1, "session_id": 1, "updated_at": 1, "created_at": 1, "preview": 1, "title": 1, "auto_tags": 1, "archived": 1, "messages": {"$slice": 1}}
    ).sort([("updated_at", DESCENDING), ("_id", DESCENDING)]).batch_size(50)
    if not after:
        cursor = cursor.skip(skip)
    cursor = cursor.limit(limit)
    # B10 — Use `async for` to stream results from MongoDB instead of loading all at once
    docs: list = []
    async for doc in cursor:
        docs.append(doc)
        if len(docs) >= limit:
            break

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
            "title": doc.get("title", ""),
            "auto_tags": doc.get("auto_tags", []),
            "archived": doc.get("archived", False),  # D10
        })
    return result
