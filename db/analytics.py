"""
Analytics store — records per-request metrics and aggregates them.
"""
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def record_request(
    session_id: str,
    agent: str,
    model: str,
    tools: list[str],
    duration_ms: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
) -> None:
    """Append one request record to the analytics collection."""
    if _db is None:
        return
    await _db["analytics"].insert_one({
        "session_id": session_id,
        "agent": agent,
        "model": model,
        "tools": tools,
        "duration_ms": duration_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "ts": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    })


async def get_summary(days: int = 30) -> dict:
    """Aggregate analytics over the last N days."""
    if _db is None:
        return {"totals": {"total_requests": 0, "total_cost_usd": 0.0, "avg_duration_ms": 0.0, "total_input_tokens": 0, "total_output_tokens": 0}, "by_agent": [], "by_model": [], "daily": []}

    pipeline = [
        {"$group": {
            "_id": None,
            "total_requests": {"$sum": 1},
            "total_cost_usd": {"$sum": "$cost_usd"},
            "total_duration_ms": {"$sum": "$duration_ms"},
            "avg_duration_ms": {"$avg": "$duration_ms"},
            "total_input_tokens": {"$sum": "$input_tokens"},
            "total_output_tokens": {"$sum": "$output_tokens"},
        }},
    ]
    cursor = _db["analytics"].aggregate(pipeline)
    totals = await cursor.to_list(1)

    # Per-agent breakdown
    agent_pipe = [
        {"$group": {"_id": "$agent", "count": {"$sum": 1}, "cost": {"$sum": "$cost_usd"}}},
        {"$sort": {"count": -1}},
    ]
    agent_cursor = _db["analytics"].aggregate(agent_pipe)
    by_agent = await agent_cursor.to_list(100)

    # Per-model breakdown
    model_pipe = [
        {"$group": {"_id": "$model", "count": {"$sum": 1}, "cost": {"$sum": "$cost_usd"}}},
        {"$sort": {"count": -1}},
    ]
    model_cursor = _db["analytics"].aggregate(model_pipe)
    by_model = await model_cursor.to_list(100)

    # Daily requests (last 30 days)
    daily_pipe = [
        {"$group": {"_id": "$date", "count": {"$sum": 1}, "cost": {"$sum": "$cost_usd"}}},
        {"$sort": {"_id": 1}},
        {"$limit": days},
    ]
    daily_cursor = _db["analytics"].aggregate(daily_pipe)
    daily = await daily_cursor.to_list(days)

    default_totals = {
        "total_requests": 0,
        "total_cost_usd": 0.0,
        "avg_duration_ms": 0.0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
    }
    if totals:
        t = totals[0]
        merged = {k: t.get(k, default_totals[k]) for k in default_totals}
    else:
        merged = default_totals

    return {
        "totals": merged,
        "by_agent": [{"agent": r["_id"], "count": r["count"], "cost_usd": round(r["cost"], 6)} for r in by_agent],
        "by_model": [{"model": r["_id"], "count": r["count"], "cost_usd": round(r["cost"], 6)} for r in by_model],
        "daily": [{"date": r["_id"], "count": r["count"], "cost_usd": round(r["cost"], 6)} for r in daily],
    }
