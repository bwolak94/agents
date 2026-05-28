"""
Workflow definitions and execution state stored in MongoDB.
Used by the LangGraph-style workflow engine in core/graph.py.
"""
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_db = None


def set_db(database) -> None:
    global _db
    _db = database


async def ensure_indexes() -> None:
    await _db["workflows"].create_index("workflow_id", unique=True)
    await _db["workflow_runs"].create_index([("workflow_id", 1), ("run_id", 1)], unique=True)
    await _db["workflow_runs"].create_index("created_at", expireAfterSeconds=7 * 24 * 3600)


async def save_workflow(workflow_id: str, name: str, definition: dict) -> str:
    """Upsert a workflow DAG definition."""
    now = datetime.now(timezone.utc).isoformat()
    await _db["workflows"].update_one(
        {"workflow_id": workflow_id},
        {"$set": {"name": name, "definition": definition, "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return workflow_id


async def get_workflow(workflow_id: str) -> dict | None:
    return await _db["workflows"].find_one({"workflow_id": workflow_id}, {"_id": 0})


async def list_workflows() -> list:
    cursor = _db["workflows"].find({}, {"_id": 0, "workflow_id": 1, "name": 1, "updated_at": 1})
    return await cursor.to_list(length=100)


async def delete_workflow(workflow_id: str) -> bool:
    result = await _db["workflows"].delete_one({"workflow_id": workflow_id})
    return result.deleted_count > 0


# ─── Execution state (runs) ───────────────────────────────────────────────────

async def create_run(workflow_id: str, run_id: str, initial_state: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await _db["workflow_runs"].insert_one({
        "workflow_id": workflow_id,
        "run_id": run_id,
        "status": "running",
        "state": initial_state,
        "snapshots": [],
        "human_input_pending": False,
        "human_input_node": None,
        "created_at": now,
        "updated_at": now,
    })


async def get_run(run_id: str) -> dict | None:
    return await _db["workflow_runs"].find_one({"run_id": run_id}, {"_id": 0})


async def update_run_state(run_id: str, state: dict, status: str = "running",
                           human_input_node: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    upd: dict[str, Any] = {
        "$set": {"state": state, "status": status, "updated_at": now},
    }
    if human_input_node is not None:
        upd["$set"]["human_input_pending"] = True
        upd["$set"]["human_input_node"] = human_input_node
    else:
        upd["$set"]["human_input_pending"] = False
        upd["$set"]["human_input_node"] = None
    await _db["workflow_runs"].update_one({"run_id": run_id}, upd)


async def append_snapshot(run_id: str, node_name: str, snapshot: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    entry = {"node": node_name, "snapshot": snapshot, "ts": now}
    await _db["workflow_runs"].update_one(
        {"run_id": run_id},
        {"$push": {"snapshots": entry}, "$set": {"updated_at": now}},
    )


async def resume_run(run_id: str, human_response: str) -> dict | None:
    """Inject human response and clear the pause flag."""
    run = await get_run(run_id)
    if not run or not run.get("human_input_pending"):
        return None
    state = run["state"]
    state["human_response"] = human_response
    await update_run_state(run_id, state, status="running")
    return state
