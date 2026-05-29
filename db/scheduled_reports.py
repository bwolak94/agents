"""Scheduled prompt reports — run a prompt on a cron schedule, deliver via webhook."""
import uuid
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

__all__ = ["set_db", "ensure_indexes", "create_report", "list_reports",
           "get_report", "delete_report", "update_last_run"]

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["scheduled_reports"].create_index("report_id", unique=True)
    await _db["scheduled_reports"].create_index("active")
    await _db["scheduled_reports"].create_index("next_run_at")


async def create_report(
    name: str,
    prompt: str,
    session_id: str,
    cron: str,
    webhook_url: str = "",
    model: str = "claude",
) -> str:
    if _db is None:
        return ""
    report_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    await _db["scheduled_reports"].insert_one({
        "report_id": report_id,
        "name": name,
        "prompt": prompt,
        "session_id": session_id,
        "cron": cron,
        "webhook_url": webhook_url,
        "model": model,
        "active": True,
        "created_at": now,
        "last_run_at": None,
        "next_run_at": now,
        "run_count": 0,
    })
    return report_id


async def list_reports(active_only: bool = False) -> list:
    if _db is None:
        return []
    query = {"active": True} if active_only else {}
    cursor = _db["scheduled_reports"].find(query, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(100)


async def get_report(report_id: str) -> dict | None:
    if _db is None:
        return None
    return await _db["scheduled_reports"].find_one({"report_id": report_id}, {"_id": 0})


async def delete_report(report_id: str) -> bool:
    if _db is None:
        return False
    result = await _db["scheduled_reports"].delete_one({"report_id": report_id})
    return result.deleted_count > 0


async def update_last_run(report_id: str, result_preview: str) -> None:
    if _db is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    await _db["scheduled_reports"].update_one(
        {"report_id": report_id},
        {
            "$set": {"last_run_at": now, "last_result": result_preview[:500]},
            "$inc": {"run_count": 1},
        },
    )
