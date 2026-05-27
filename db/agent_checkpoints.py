"""
Agent Checkpoint DB — save/resume long-running ReAct state.
Allows interruption and resumption of multi-step agent tasks.
"""
import time
from bson import ObjectId

_db = None


def set_db(db):
    global _db
    _db = db


async def ensure_indexes():
    if _db is None:
        return
    col = _db["agent_checkpoints"]
    await col.create_index([("session_id", 1), ("checkpoint_id", 1)])
    await col.create_index([("expires_at", 1)], expireAfterSeconds=0)


async def save_checkpoint(
    session_id: str,
    checkpoint_id: str,
    messages: list,
    tool_call_cache: dict,
    iteration: int,
    agent_name: str,
    model: str,
) -> str:
    if _db is None:
        return ""
    col = _db["agent_checkpoints"]
    now = time.time()
    doc = {
        "session_id": session_id,
        "checkpoint_id": checkpoint_id,
        "messages": messages,
        "tool_call_cache": {k: str(v) for k, v in tool_call_cache.items()},
        "iteration": iteration,
        "agent_name": agent_name,
        "model": model,
        "created_at": now,
        "expires_at": __import__("datetime").datetime.utcfromtimestamp(now + 86400),  # 24h TTL
    }
    result = await col.replace_one(
        {"session_id": session_id, "checkpoint_id": checkpoint_id},
        doc,
        upsert=True,
    )
    return checkpoint_id


async def load_checkpoint(session_id: str, checkpoint_id: str) -> dict | None:
    if _db is None:
        return None
    col = _db["agent_checkpoints"]
    doc = await col.find_one({"session_id": session_id, "checkpoint_id": checkpoint_id})
    if not doc:
        return None
    return {
        "messages": doc.get("messages", []),
        "tool_call_cache": doc.get("tool_call_cache", {}),
        "iteration": doc.get("iteration", 0),
        "agent_name": doc.get("agent_name", ""),
        "model": doc.get("model", ""),
        "created_at": doc.get("created_at", 0),
    }


async def delete_checkpoint(session_id: str, checkpoint_id: str) -> bool:
    if _db is None:
        return False
    col = _db["agent_checkpoints"]
    result = await col.delete_one({"session_id": session_id, "checkpoint_id": checkpoint_id})
    return result.deleted_count > 0


async def list_checkpoints(session_id: str) -> list[dict]:
    if _db is None:
        return []
    col = _db["agent_checkpoints"]
    docs = await col.find(
        {"session_id": session_id},
        {"checkpoint_id": 1, "iteration": 1, "agent_name": 1, "model": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(50)
    return [
        {
            "checkpoint_id": d["checkpoint_id"],
            "iteration": d.get("iteration", 0),
            "agent_name": d.get("agent_name", ""),
            "model": d.get("model", ""),
            "created_at": d.get("created_at", 0),
        }
        for d in docs
    ]
