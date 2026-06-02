"""Role-based session access — owner grants read/write/admin tokens with optional expiry."""
import uuid
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase

__all__ = ["set_db", "ensure_indexes", "grant_access", "check_token", "list_grants",
           "revoke_token", "purge_expired"]

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["session_roles"].create_index("token", unique=True)
    await _db["session_roles"].create_index("session_id")
    await _db["session_roles"].create_index("expires_at")


async def grant_access(session_id: str, role: str = "read", ttl_hours: int = 0) -> str:
    """Create a new access token for session_id with the given role.

    Args:
        session_id: Target session.
        role: 'read' | 'write' | 'admin'
        ttl_hours: Hours until expiry. 0 = never expires.
    """
    if _db is None:
        return ""
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=ttl_hours)).isoformat() if ttl_hours > 0 else None
    await _db["session_roles"].insert_one({
        "session_id": session_id,
        "token": token,
        "role": role,
        "created_at": now.isoformat(),
        "expires_at": expires_at,
    })
    return token


async def check_token(session_id: str, token: str) -> str | None:
    """Return the role for token in session, or None if not found or expired."""
    if _db is None:
        return None
    doc = await _db["session_roles"].find_one(
        {"session_id": session_id, "token": token}, {"_id": 0, "role": 1, "expires_at": 1}
    )
    if not doc:
        return None
    # Honour expiry
    expires_at = doc.get("expires_at")
    if expires_at:
        expiry = datetime.fromisoformat(expires_at)
        if datetime.now(timezone.utc) > expiry:
            return None
    return doc["role"]


async def list_grants(session_id: str) -> list:
    if _db is None:
        return []
    now = datetime.now(timezone.utc).isoformat()
    cursor = _db["session_roles"].find(
        {"session_id": session_id, "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]},
        {"_id": 0, "token": 0},
    ).sort("created_at", -1)
    return await cursor.to_list(100)


async def revoke_token(token: str) -> bool:
    if _db is None:
        return False
    result = await _db["session_roles"].delete_one({"token": token})
    return result.deleted_count > 0


async def purge_expired() -> int:
    """Delete all expired tokens. Call periodically from a background task."""
    if _db is None:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    result = await _db["session_roles"].delete_many({"expires_at": {"$lt": now}})
    return result.deleted_count
