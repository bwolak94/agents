"""Platform endpoints: async queue (#27), webhooks (#29), canary (#30), plugins (#20), Redis (#26)."""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query

import api.db as _db
import api.state as _state
from api.models import AsyncChatRequest, WebhookRegisterRequest, CanaryRequest

logger = logging.getLogger(__name__)
router = APIRouter()


# ── #27 Async chat queue ──────────────────────────────────────────────────────

@router.post("/chat/async")
async def chat_async(req: AsyncChatRequest):
    """Enqueue a chat job. Returns job_id for polling."""
    from core.queue import enqueue
    job_id = await enqueue(req.session_id, req.message, req.preferred_model)
    # Start in-process worker if not using Redis
    import os
    if not os.getenv("REDIS_URL"):
        asyncio.create_task(_process_job(req.session_id))
    return {"job_id": job_id, "status": "pending"}


@router.get("/chat/async/{job_id}")
async def chat_async_result(job_id: str):
    """Poll for an async job result."""
    from core.queue import get_result
    result = await get_result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return result


async def _process_job(session_id: str) -> None:
    from core.queue import process_next
    async def _fn(message: str, session_id: str, preferred_model: str = "") -> str:
        orch = await _state.get_session(session_id)
        return await orch.process(message=message, session_id=session_id, preferred_model=preferred_model)
    await process_next(_fn)


# ── #29 Outbound webhooks ─────────────────────────────────────────────────────

@router.post("/webhooks")
async def register_webhook(req: WebhookRegisterRequest):
    webhook_id = await _db.webhooks_db.register(req.session_id, req.url, req.events, req.secret)
    return {"webhook_id": webhook_id, "status": "registered"}


@router.get("/webhooks")
async def list_webhooks(session_id: str = Query(...)):
    return {"webhooks": await _db.webhooks_db.list_webhooks(session_id)}


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str):
    deleted = await _db.webhooks_db.delete_webhook(webhook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"status": "deleted", "webhook_id": webhook_id}


@router.post("/webhooks/test/{webhook_id}")
async def test_webhook(webhook_id: str):
    """Send a test payload to a registered webhook."""
    results = await _db.webhooks_db.fire("__test__", "test", {"message": "Test ping from Agent System"})
    # find result for this specific webhook
    match = next((r for r in results if r["webhook_id"] == webhook_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return match


# ── #30 Canary deployments ────────────────────────────────────────────────────

@router.post("/canary/{agent_name}")
async def create_canary(agent_name: str, req: CanaryRequest):
    """Define a canary config for an agent: split traffic between stable and canary prompts."""
    from agents.agents import AGENT_REGISTRY
    if agent_name not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    # Store as an A/B experiment under the hood
    exp_id = f"canary_{agent_name}"
    await _db.experiments_db.create_experiment(
        experiment_id=exp_id,
        name=f"Canary: {agent_name}",
        variants=[
            {"name": "stable", "agent": agent_name, "system_prompt": req.stable_prompt},
            {"name": "canary", "agent": agent_name, "system_prompt": req.canary_prompt},
        ],
        traffic_split=[1.0 - req.canary_pct / 100, req.canary_pct / 100],
    )
    return {"status": "created", "experiment_id": exp_id, "agent_name": agent_name, "canary_pct": req.canary_pct}


@router.get("/canary/{agent_name}")
async def get_canary(agent_name: str):
    exp_id = f"canary_{agent_name}"
    exp = await _db.experiments_db.get_experiment(exp_id)
    if not exp:
        raise HTTPException(status_code=404, detail="No canary configured for this agent")
    return exp


@router.delete("/canary/{agent_name}")
async def stop_canary(agent_name: str):
    exp_id = f"canary_{agent_name}"
    stopped = await _db.experiments_db.stop_experiment(exp_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="No active canary for this agent")
    return {"status": "stopped", "agent_name": agent_name}


# ── #20 Plugin registry ───────────────────────────────────────────────────────

@router.get("/plugins")
async def list_plugins():
    from core.plugins import list_plugins as _list
    return {"plugins": _list()}


@router.post("/plugins/reload")
async def reload_plugins():
    """Reload all plugins from the plugins/ directory."""
    orch = await _state.get_session("default")
    from core.plugins import load_plugins
    loaded = load_plugins(orch.tools)
    return {"status": "reloaded", "loaded": loaded}


# ── #26 Redis session info ────────────────────────────────────────────────────

@router.get("/sessions/backend")
async def session_backend_info():
    """Report which session backend is in use (in-memory or Redis)."""
    import os
    redis_url = os.getenv("REDIS_URL", "")
    return {
        "backend": "redis" if redis_url else "in_memory",
        "redis_url": redis_url.split("@")[-1] if redis_url else None,  # mask credentials
        "active_sessions": _state.session_manager.count(),
    }
