"""Operational endpoints — health, analytics, models, schedule, memory, prompts,
feedback, tags, checkpoints, admin, batch, briefing."""
import asyncio
import csv
import io
import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

import api.db as _db
import api.state as _state
from api.models import (
    PromptSaveRequest, ScheduleRequest, FeedbackRequest,
    TagRequest, AdminKeyRequest, BatchRequest,
)
from api.validators import validate_session_id
from core import scheduler as _sched_mod  # module ref so tests patch core.scheduler.scheduler

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Root / Health ─────────────────────────────────────────────────────────────

@router.get("/")
async def root():
    orch = await _state.get_session("default")
    return {
        "status": "running",
        "version": "2.0.0",
        "models": orch.llm.available_models(),
        "active_sessions": _state.session_manager.count(),
    }


# ── Stats / Analytics ─────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(session_id: str = "default"):
    orch = await _state.get_session(session_id)
    return orch.get_stats()


@router.get("/analytics")
async def get_analytics(days: int = Query(default=30, ge=1, le=365)):
    return await _db.analytics_db.get_summary(days)


@router.get("/analytics/export")
async def export_analytics(
    days: int = Query(default=30, ge=1, le=365),
    format: str = Query(default="csv", pattern="^(csv|json)$"),
):
    data = await _db.analytics_db.get_summary(days)
    if format == "json":
        return Response(
            content=json.dumps(data, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="analytics.json"'},
        )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "key", "value"])
    for k, v in data.get("totals", {}).items():
        writer.writerow(["totals", k, v])
    for row in data.get("by_agent", []):
        writer.writerow(["by_agent", row.get("agent"), row.get("count")])
    for row in data.get("by_model", []):
        writer.writerow(["by_model", row.get("model"), row.get("count")])
    for row in data.get("daily", []):
        writer.writerow(["daily", row.get("date"), row.get("count")])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="analytics.csv"'},
    )


# ── Models ────────────────────────────────────────────────────────────────────

@router.get("/models")
async def list_models():
    orch = await _state.get_session("default")
    return {"models": orch.llm.available_models()}


@router.post("/models/refresh")
async def refresh_models():
    orch = await _state.get_session("default")
    models = await orch.llm.refresh_ollama_models()
    return {"ollama_models": models, "all_models": orch.llm.available_models()}


@router.get("/models/health")
async def models_health():
    orch = await _state.get_session("default")
    return {"health": orch.llm.get_health_status()}


# ── Scheduler ─────────────────────────────────────────────────────────────────

@router.post("/schedule")
async def schedule_task(req: ScheduleRequest):
    if req.interval_seconds is not None:
        task_id = _sched_mod.scheduler.schedule_recurring(req.session_id, req.prompt, req.interval_seconds)
        return {"task_id": task_id, "status": "recurring", "interval_seconds": req.interval_seconds}
    task_id = _sched_mod.scheduler.schedule(req.session_id, req.prompt, req.delay_seconds)
    return {"task_id": task_id, "status": "scheduled", "delay_seconds": req.delay_seconds}


@router.get("/schedule")
async def list_scheduled(session_id: str | None = None):
    return {"tasks": _sched_mod.scheduler.list_tasks(session_id)}


@router.get("/schedule/{task_id}")
async def get_scheduled_task(task_id: str):
    task = _sched_mod.scheduler.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    tasks = _sched_mod.scheduler.list_tasks()
    match = next((t for t in tasks if t["task_id"] == task_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Task not found")
    return match


@router.delete("/schedule/{task_id}")
async def cancel_scheduled_task(task_id: str):
    cancelled = _sched_mod.scheduler.cancel_task(task_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "cancelled", "task_id": task_id}


@router.post("/briefing/schedule")
async def schedule_briefing(
    session_id: str = "default",
    hour: int = Query(default=9, ge=0, le=23),
):
    validate_session_id(session_id)
    briefing_prompt = (
        "Generate my daily briefing. Include:\n"
        "1. A summary of our recent conversations and any unresolved topics\n"
        "2. Key facts or decisions we made together\n"
        "3. Any suggestions for what to focus on today\n"
        "Keep it concise — 5-10 bullet points."
    )
    task_id = _sched_mod.scheduler.schedule_recurring(session_id, briefing_prompt, interval_seconds=86400)
    return {"status": "scheduled", "task_id": task_id, "session_id": session_id, "daily_at_hour_utc": hour}


# ── Response cache ────────────────────────────────────────────────────────────

@router.get("/cache/stats")
async def cache_stats():
    return await _db.cache_db.stats()


@router.delete("/cache")
async def invalidate_cache(model: str | None = None):
    deleted = await _db.cache_db.invalidate(model)
    return {"deleted": deleted}


# ── Agent memory ──────────────────────────────────────────────────────────────

@router.get("/memory/{session_id}/{agent_type}")
async def get_memory(session_id: str, agent_type: str):
    validate_session_id(session_id)
    memory = await _db.memory_db.memory_read(session_id, agent_type)
    return {"session_id": session_id, "agent_type": agent_type, "memory": memory}


@router.delete("/memory/{session_id}/{agent_type}")
async def clear_memory(session_id: str, agent_type: str):
    validate_session_id(session_id)
    await _db.memory_db.memory_write(session_id, agent_type, "")
    return {"status": "cleared"}


# ── Prompt library ────────────────────────────────────────────────────────────

@router.get("/prompts/{session_id}")
async def get_prompts(session_id: str):
    validate_session_id(session_id)
    return {"prompts": await _db.prompts_db.list_prompts(session_id)}


@router.post("/prompts")
async def save_prompt(req: PromptSaveRequest):
    prompt_id = await _db.prompts_db.save_prompt(req.session_id, req.title, req.content, req.tags)
    return {"prompt_id": prompt_id, "status": "saved"}


@router.delete("/prompts/{session_id}/{prompt_id}")
async def delete_prompt(session_id: str, prompt_id: str):
    validate_session_id(session_id)
    deleted = await _db.prompts_db.delete_prompt(session_id, prompt_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"status": "deleted"}


# ── Feedback (auto-retry on thumbs-down) ──────────────────────────────────────

@router.get("/feedback/{session_id}")
async def get_feedback(session_id: str):
    validate_session_id(session_id)
    return {"session_id": session_id, "feedback": await _db.feedback_db.get_feedback(session_id)}


@router.get("/feedback")
async def feedback_summary():
    return await _db.feedback_db.get_summary()


@router.post("/feedback")
async def save_feedback(req: FeedbackRequest):
    fid = await _db.feedback_db.save_feedback(req.session_id, req.message_idx, req.rating, req.comment)
    if req.rating == -1:
        asyncio.create_task(_auto_retry_feedback(req.session_id, req.message_idx, req.comment))
    return {"feedback_id": fid, "status": "saved"}


async def _auto_retry_feedback(session_id: str, message_idx: int, comment: str) -> None:
    try:
        messages = await _db.load_history(session_id)
        if message_idx > 0 and message_idx < len(messages):
            for i in range(message_idx - 1, -1, -1):
                if messages[i].get("role") == "user":
                    original = messages[i]["content"]
                    improvement = (
                        f"{original}\n\n[Note: A previous answer was rated unsatisfactory"
                        + (f" because: {comment}" if comment else "")
                        + ". Please provide a significantly improved response.]"
                    )
                    orch = await _state.get_session(session_id)
                    await orch.process(message=improvement, session_id=session_id)
                    break
    except Exception:
        pass


# ── Tags ──────────────────────────────────────────────────────────────────────

@router.get("/tags")
async def list_all_tags():
    return {"tags": await _db.tags_db.all_tags()}


@router.get("/tags/{session_id}")
async def get_session_tags(session_id: str):
    validate_session_id(session_id)
    return {"session_id": session_id, "tags": await _db.tags_db.get_tags(session_id)}


@router.post("/tags")
async def add_tag(req: TagRequest):
    validate_session_id(req.session_id)
    tags = await _db.tags_db.add_tag(req.session_id, req.tag)
    return {"session_id": req.session_id, "tags": tags}


@router.delete("/tags/{session_id}/{tag}")
async def remove_tag(session_id: str, tag: str):
    validate_session_id(session_id)
    tags = await _db.tags_db.remove_tag(session_id, tag)
    return {"session_id": session_id, "tags": tags}


@router.get("/sessions/by-tag/{tag}")
async def sessions_by_tag(tag: str):
    return {"tag": tag, "sessions": await _db.tags_db.sessions_by_tag(tag)}


# ── Checkpoints ───────────────────────────────────────────────────────────────

@router.get("/checkpoints/{session_id}")
async def list_checkpoints(session_id: str):
    validate_session_id(session_id)
    from db.agent_checkpoints import list_checkpoints as _list
    return {"session_id": session_id, "checkpoints": await _list(session_id)}


@router.delete("/checkpoints/{session_id}/{checkpoint_id}")
async def delete_checkpoint(session_id: str, checkpoint_id: str):
    validate_session_id(session_id)
    from db.agent_checkpoints import delete_checkpoint as _delete
    deleted = await _delete(session_id, checkpoint_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return {"status": "deleted"}


# ── Admin: API key rotation ────────────────────────────────────────────────────

@router.put("/admin/keys")
async def rotate_keys(req: AdminKeyRequest):
    updated = []
    if req.anthropic_api_key:
        from llm.manager import AnthropicClient
        import llm.manager as _llm_mod
        if _llm_mod._anthropic_http_client and not _llm_mod._anthropic_http_client.is_closed:
            await _llm_mod._anthropic_http_client.aclose()
        _llm_mod._anthropic_http_client = None
        for _, orch in _state.session_manager.iter_orchestrators():
            orch.llm.clients["claude"] = AnthropicClient(req.anthropic_api_key)
        updated.append("anthropic")
    if req.gemini_api_key:
        from llm.manager import GeminiClient
        import llm.manager as _llm_mod
        if _llm_mod._gemini_http_client and not _llm_mod._gemini_http_client.is_closed:
            await _llm_mod._gemini_http_client.aclose()
        _llm_mod._gemini_http_client = None
        new_client = GeminiClient(req.gemini_api_key)
        for _, orch in _state.session_manager.iter_orchestrators():
            orch.llm.clients["gemini"] = new_client
        updated.append("gemini")
    return {"updated": updated}


# ── Batch processing ──────────────────────────────────────────────────────────

@router.post("/batch")
async def submit_batch(req: BatchRequest):
    if not req.tasks:
        raise HTTPException(status_code=400, detail="tasks must not be empty")
    if len(req.tasks) > 50:
        raise HTTPException(status_code=400, detail="max 50 tasks per batch")

    batch_id = await _db.batch_db.create_batch(req.tasks)

    async def _run_batch():
        await _db.batch_db.set_batch_status(batch_id, "running")
        for task in req.tasks:
            msg = task.get("message", "")
            sid = task.get("session_id", "default")
            try:
                import api.preprocessor as _preprocessor
                processed, model_override = await _preprocessor.preprocess(msg)
                orch = await _state.get_session(sid)
                response = await orch.process(message=processed, session_id=sid, preferred_model=model_override)
                await _db.batch_db.append_result(batch_id, {"message": msg[:200], "session_id": sid, "response": response, "error": None})
            except Exception as e:
                await _db.batch_db.append_result(batch_id, {"message": msg[:200], "session_id": sid, "response": None, "error": str(e)})
        await _db.batch_db.set_batch_status(batch_id, "completed")

    asyncio.create_task(_run_batch())
    return {"batch_id": batch_id, "total": len(req.tasks), "status": "running"}


@router.get("/batch/{batch_id}")
async def get_batch(batch_id: str):
    job = await _db.batch_db.get_batch(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch not found")
    return job
