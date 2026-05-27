"""
File version store — keeps previous content for diff computation.
"""
import difflib
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["file_versions"].create_index([("path", 1), ("created_at", -1)])


async def save_version(path: str, content: str) -> None:
    """Store a snapshot of a file before overwriting."""
    if _db is None:
        return
    await _db["file_versions"].insert_one({
        "path": path,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Keep only last 10 versions per path
    docs = await _db["file_versions"].find(
        {"path": path}, {"_id": 1}
    ).sort("created_at", -1).skip(10).to_list(length=1000)
    if docs:
        ids = [d["_id"] for d in docs]
        await _db["file_versions"].delete_many({"_id": {"$in": ids}})


async def get_previous(path: str) -> str | None:
    """Return the most recent stored version of a file."""
    if _db is None:
        return None
    doc = await _db["file_versions"].find_one(
        {"path": path},
        {"_id": 0, "content": 1},
        sort=[("created_at", -1)],
    )
    return doc["content"] if doc else None


def compute_diff(old: str, new: str, path: str = "") -> str:
    """Return unified diff between old and new content."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return "".join(diff) or "(no changes)"
