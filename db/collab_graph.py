"""
Agent Collaboration Graph — records agent-to-agent delegation events.
Provides analytics on which agents call which sub-agents.
"""
import time

_db = None


def set_db(db):
    global _db
    _db = db


async def ensure_indexes():
    if _db is None:
        return
    col = _db["collab_graph"]
    await col.create_index([("session_id", 1), ("timestamp", -1)])
    await col.create_index([("caller", 1), ("callee", 1)])


async def record_delegation(
    session_id: str,
    caller: str,
    callee: str,
    task: str = "",
) -> None:
    if _db is None:
        return
    col = _db["collab_graph"]
    await col.insert_one({
        "session_id": session_id,
        "caller": caller,
        "callee": callee,
        "task_preview": task[:200],
        "timestamp": time.time(),
    })


async def get_graph(session_id: str | None = None) -> list[dict]:
    if _db is None:
        return []
    col = _db["collab_graph"]
    query = {"session_id": session_id} if session_id else {}
    docs = await col.find(query).sort("timestamp", -1).to_list(200)
    return [
        {
            "session_id": d.get("session_id", ""),
            "caller": d.get("caller", ""),
            "callee": d.get("callee", ""),
            "task_preview": d.get("task_preview", ""),
            "timestamp": d.get("timestamp", 0),
        }
        for d in docs
    ]


async def get_summary() -> dict:
    if _db is None:
        return {"edges": []}
    col = _db["collab_graph"]
    pipeline = [
        {"$group": {"_id": {"caller": "$caller", "callee": "$callee"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]
    docs = await col.aggregate(pipeline).to_list(50)
    return {
        "edges": [
            {
                "caller": d["_id"]["caller"],
                "callee": d["_id"]["callee"],
                "count": d["count"],
            }
            for d in docs
        ]
    }
