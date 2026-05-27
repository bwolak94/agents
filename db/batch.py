"""
Batch job store — fire-and-forget bulk LLM task processing.
Jobs are stored in MongoDB and results appended as they complete.
"""
import uuid
import time
from datetime import datetime, timezone

_db = None


def set_db(db) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["batch_jobs"].create_index([("batch_id", 1)], unique=True)
    await _db["batch_jobs"].create_index([("created_at", 1)], expireAfterSeconds=86400)  # 24h TTL


async def create_batch(tasks: list[dict]) -> str:
    """Create a batch job and return batch_id."""
    if _db is None:
        return ""
    batch_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await _db["batch_jobs"].insert_one({
        "batch_id": batch_id,
        "status": "pending",
        "total": len(tasks),
        "completed": 0,
        "tasks": tasks,
        "results": [],
        "created_at": now,
        "updated_at": now,
    })
    return batch_id


async def get_batch(batch_id: str) -> dict | None:
    if _db is None:
        return None
    doc = await _db["batch_jobs"].find_one({"batch_id": batch_id}, {"_id": 0})
    return doc


async def append_result(batch_id: str, result: dict) -> None:
    if _db is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    await _db["batch_jobs"].update_one(
        {"batch_id": batch_id},
        {
            "$push": {"results": result},
            "$inc": {"completed": 1},
            "$set": {"updated_at": now},
        },
    )


async def set_batch_status(batch_id: str, status: str) -> None:
    if _db is None:
        return
    await _db["batch_jobs"].update_one(
        {"batch_id": batch_id},
        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
