"""
A/B testing experiment store.
Tracks experiment definitions, traffic splits, and per-variant metrics.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_db = None


def set_db(database) -> None:
    global _db
    _db = database


async def ensure_indexes() -> None:
    await _db["experiments"].create_index("experiment_id", unique=True)
    await _db["experiment_results"].create_index(
        [("experiment_id", 1), ("variant", 1), ("session_id", 1)]
    )


async def create_experiment(experiment_id: str, name: str, variants: list[dict],
                             traffic_split: list[float]) -> str:
    """
    variants: [{"name": "control", "agent": "general_agent", "model": "claude"},
               {"name": "treatment", "agent": "general_agent", "model": "claude-haiku"}]
    traffic_split: [0.5, 0.5] must sum to 1.0
    """
    now = datetime.now(timezone.utc).isoformat()
    await _db["experiments"].update_one(
        {"experiment_id": experiment_id},
        {"$set": {
            "name": name,
            "variants": variants,
            "traffic_split": traffic_split,
            "status": "active",
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return experiment_id


async def get_experiment(experiment_id: str) -> dict | None:
    return await _db["experiments"].find_one({"experiment_id": experiment_id}, {"_id": 0})


async def list_experiments(status: str = "") -> list:
    filt: dict = {}
    if status:
        filt["status"] = status
    cursor = _db["experiments"].find(filt, {"_id": 0})
    return await cursor.to_list(length=100)


async def assign_variant(experiment_id: str, session_id: str) -> dict | None:
    """Deterministically assign a variant based on session_id hash."""
    import hashlib
    exp = await get_experiment(experiment_id)
    if not exp or exp.get("status") != "active":
        return None
    variants = exp["variants"]
    splits = exp["traffic_split"]
    # Deterministic bucket from session_id
    h = int(hashlib.md5(f"{experiment_id}:{session_id}".encode()).hexdigest(), 16)
    bucket = (h % 1000) / 1000.0
    cumulative = 0.0
    for variant, split in zip(variants, splits):
        cumulative += split
        if bucket < cumulative:
            return variant
    return variants[-1]


async def record_result(experiment_id: str, variant: str, session_id: str,
                         metric: str, value: float) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await _db["experiment_results"].insert_one({
        "experiment_id": experiment_id,
        "variant": variant,
        "session_id": session_id,
        "metric": metric,
        "value": value,
        "ts": now,
    })


async def get_experiment_summary(experiment_id: str) -> dict:
    pipeline = [
        {"$match": {"experiment_id": experiment_id}},
        {"$group": {
            "_id": {"variant": "$variant", "metric": "$metric"},
            "count": {"$sum": 1},
            "avg": {"$avg": "$value"},
            "total": {"$sum": "$value"},
        }},
        {"$sort": {"_id.variant": 1, "_id.metric": 1}},
    ]
    docs = await _db["experiment_results"].aggregate(pipeline).to_list(length=None)
    results: dict = {}
    for doc in docs:
        variant = doc["_id"]["variant"]
        metric = doc["_id"]["metric"]
        results.setdefault(variant, {})[metric] = {
            "count": doc["count"],
            "avg": round(doc["avg"], 4),
            "total": round(doc["total"], 4),
        }
    return results


async def stop_experiment(experiment_id: str) -> bool:
    result = await _db["experiments"].update_one(
        {"experiment_id": experiment_id},
        {"$set": {"status": "stopped", "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return result.modified_count > 0
