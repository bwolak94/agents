"""
Multi-tenant namespacing.
Every collection query is scoped by tenant_id when tenancy is enabled.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_db = None


def set_db(database) -> None:
    global _db
    _db = database


async def ensure_indexes() -> None:
    await _db["tenants"].create_index("tenant_id", unique=True)
    await _db["tenants"].create_index("api_key", unique=True, sparse=True)


async def create_tenant(tenant_id: str, name: str, plan: str = "free",
                         api_key: str | None = None) -> str:
    now = datetime.now(timezone.utc).isoformat()
    doc: dict = {
        "tenant_id": tenant_id,
        "name": name,
        "plan": plan,
        "limits": _plan_limits(plan),
        "created_at": now,
        "updated_at": now,
    }
    if api_key:
        doc["api_key"] = api_key
    await _db["tenants"].update_one(
        {"tenant_id": tenant_id},
        {"$setOnInsert": doc},
        upsert=True,
    )
    return tenant_id


def _plan_limits(plan: str) -> dict:
    limits = {
        "free":       {"requests_per_day": 100,  "max_sessions": 10,  "max_rag_docs": 20},
        "starter":    {"requests_per_day": 1000, "max_sessions": 100, "max_rag_docs": 200},
        "pro":        {"requests_per_day": 10000,"max_sessions": 1000,"max_rag_docs": 2000},
        "enterprise": {"requests_per_day": -1,   "max_sessions": -1,  "max_rag_docs": -1},
    }
    return limits.get(plan, limits["free"])


async def get_tenant(tenant_id: str) -> dict | None:
    return await _db["tenants"].find_one({"tenant_id": tenant_id}, {"_id": 0})


async def get_tenant_by_api_key(api_key: str) -> dict | None:
    return await _db["tenants"].find_one({"api_key": api_key}, {"_id": 0})


async def list_tenants() -> list:
    cursor = _db["tenants"].find({}, {"_id": 0, "api_key": 0})
    return await cursor.to_list(length=200)


async def update_tenant(tenant_id: str, **fields) -> bool:
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await _db["tenants"].update_one(
        {"tenant_id": tenant_id},
        {"$set": fields},
    )
    return result.modified_count > 0


async def delete_tenant(tenant_id: str) -> bool:
    result = await _db["tenants"].delete_one({"tenant_id": tenant_id})
    return result.deleted_count > 0


# ─── Usage tracking ───────────────────────────────────────────────────────────

async def increment_usage(tenant_id: str, metric: str = "requests") -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await _db["tenant_usage"].update_one(
        {"tenant_id": tenant_id, "date": today},
        {"$inc": {metric: 1}},
        upsert=True,
    )


async def get_usage(tenant_id: str, days: int = 30) -> list:
    from datetime import timedelta
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    cursor = _db["tenant_usage"].find(
        {"tenant_id": tenant_id, "date": {"$gte": start}},
        {"_id": 0},
        sort=[("date", -1)],
    )
    return await cursor.to_list(length=days)
