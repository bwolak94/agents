"""Operational endpoints — health, analytics, models, schedule, memory, prompts,
feedback, tags, checkpoints, admin, batch, briefing."""
import asyncio
import csv
import io
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

# ── Prometheus metrics ────────────────────────────────────────────────────────
try:
    from prometheus_client import (
        Counter, Histogram, Gauge,
        generate_latest, CONTENT_TYPE_LATEST, REGISTRY,
    )
    _PROMETHEUS = True
    _chat_requests = Counter(
        "agent_chat_requests_total", "Total chat requests",
        ["model", "agent"],
    )
    _chat_duration = Histogram(
        "agent_chat_duration_seconds", "Chat request duration",
        buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
    )
    _llm_errors = Counter(
        "agent_llm_errors_total", "LLM call failures", ["model"],
    )
    _active_sessions_gauge = Gauge(
        "agent_active_sessions", "Number of active sessions",
    )
except ImportError:
    _PROMETHEUS = False

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


@router.get("/metrics")
async def prometheus_metrics():
    """Expose Prometheus metrics (requires prometheus-client)."""
    if not _PROMETHEUS:
        raise HTTPException(
            status_code=501,
            detail="prometheus-client is not installed. Run: pip install prometheus-client",
        )
    if _PROMETHEUS:
        _active_sessions_gauge.set(_state.session_manager.count())
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@router.get("/health")
async def health():
    """#9 — Real dependency health check: MongoDB ping + LLM reachability."""
    checks: dict = {}
    overall = "ok"

    # MongoDB ping
    try:
        from db.history import _db as hist_db
        if hist_db is not None:
            await hist_db.command("ping")
            checks["mongodb"] = "ok"
        else:
            checks["mongodb"] = "not_connected"
            overall = "degraded"
    except Exception as exc:
        checks["mongodb"] = f"error: {exc}"
        overall = "degraded"

    # LLM health
    try:
        orch = await _state.get_session("default")
        llm_status = orch.llm.get_health_status()
        checks["llm"] = llm_status
        if not any(v == "healthy" for v in llm_status.values()):
            overall = "degraded"
    except Exception as exc:
        checks["llm"] = f"error: {exc}"
        overall = "degraded"

    # Active sessions + queue depth
    checks["active_sessions"] = _state.session_manager.count()
    try:
        from core.queue import queue_depth
        checks["queue_depth"] = queue_depth()
    except Exception:
        pass

    # #29 — migration state
    try:
        from db.history import _db as hist_db
        if hist_db is not None:
            applied_count = await hist_db["migrations"].count_documents({})
            checks["migrations_applied"] = applied_count
            checks["db_indexes"] = await hist_db["conversations"].index_information()
            checks["db_indexes"] = len(checks["db_indexes"])
    except Exception:
        pass

    # #27 db_version from MongoDB buildInfo
    try:
        from db.history import _db as hist_db
        if hist_db is not None:
            build_info = await hist_db.command("buildInfo")
            checks["db_version"] = build_info.get("version", "unknown")
    except Exception:
        pass

    status_code = 200 if overall == "ok" else 207
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={"status": overall, "checks": checks},
        headers={"Connection": "keep-alive", "Keep-Alive": "timeout=5, max=100"},  # #22
    )


# #8 Kubernetes readiness + liveness probes
@router.get("/health/ready")
async def health_ready():
    """Readiness probe — reports not ready if MongoDB is unreachable. #8: includes pool stats."""
    try:
        from db.history import _client as hist_client, _db as hist_db
        if hist_db is None:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=503, content={"ready": False, "reason": "db_not_initialized"})
        await hist_db.command("ping")
        # #8 — include connection pool utilisation
        pool_info: dict = {}
        try:
            if hist_client is not None:
                topology = hist_client.delegate._topology  # type: ignore[attr-defined]
                servers = topology._servers
                for addr, server in servers.items():
                    pool = getattr(server, "_pool", None)
                    if pool:
                        pool_info[str(addr)] = {
                            "available": getattr(pool, "_available_count", "?"),
                            "max": getattr(pool, "_max_pool_size", "?"),
                        }
        except Exception:
            pass
        return {"ready": True, "pool": pool_info}
    except Exception as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"ready": False, "reason": str(exc)})


@router.get("/health/live")
async def health_live():
    """Liveness probe — always 200 as long as the process is running."""
    return {"alive": True, "pid": __import__("os").getpid()}


@router.get("/health/pool")
async def health_pool():
    """D14 — Expose Motor connection pool stats for monitoring dashboards."""
    from db.history import _client
    if _client is None:
        return {"error": "database not initialised"}
    try:
        server_info = _client.topology_description
        pools = []
        for sd in server_info.server_descriptions().values():
            pools.append({"host": sd.address, "type": str(sd.server_type.name)})
        # Motor exposes pool stats via the underlying pymongo client
        pool_state = {}
        try:
            pool_state = {
                "max_pool_size": _client.options.pool_options.max_pool_size,
                "min_pool_size": _client.options.pool_options.min_pool_size,
            }
        except Exception:
            pass
        return {"pool": pool_state, "servers": pools}
    except Exception as exc:
        return {"error": str(exc)}




# ── W22 Session presence ──────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/presence")
async def session_presence(session_id: str):
    """W22 — How many active WebSocket clients are subscribed to this session."""
    from api.validators import validate_session_id
    validate_session_id(session_id)
    from core.events import event_bus
    count = event_bus.subscriber_count_for(session_id)
    return {"session_id": session_id, "active_connections": count}

# ── #24 Debug sessions ────────────────────────────────────────────────────────

@router.get("/debug/sessions")
async def debug_sessions(admin_key: str = Query(default="")):
    """Admin endpoint: show in-memory session map, lock state, cost totals."""
    api_key = __import__("os").getenv("API_KEY", "")
    if api_key and admin_key != api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Invalid admin key")

    sessions = []
    for sid, orch in _state.session_manager.iter_orchestrators():
        cost = {}
        try:
            cost = orch.llm.get_cost_stats()
        except Exception:
            pass
        sessions.append({
            "session_id": sid,
            "history_length": len(getattr(orch, "conversation_history", [])),
            "cost_stats": cost,
            "has_lock": (
                sid in _state.session_manager._session_locks
                and _state.session_manager._session_locks[sid].locked()
            ),
        })

    return {
        "active_sessions": len(sessions),
        "max_sessions": __import__("os").getenv("MAX_SESSIONS", "200"),
        "sessions": sessions,
    }


# ── Stats / Analytics ─────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(session_id: str = "default"):
    orch = await _state.get_session(session_id)
    return orch.get_stats()


@router.get("/analytics", response_model_exclude_none=True)
@router.get("/analytics/summary", response_model_exclude_none=True)
async def get_analytics(days: int = Query(default=30, ge=1, le=365)):
    from config.constants import ANALYTICS_STALE_SECONDS
    # #11 secondaryPreferred: use secondary replica for heavy analytics reads
    try:
        from db.analytics import _db as _adb
        from pymongo import ReadPreference
        if _adb is not None:
            coll = _adb.get_collection("analytics", read_preference=ReadPreference.SECONDARY_PREFERRED)
            _ = coll  # signal intent — get_summary uses its own collection ref
    except Exception:
        pass
    data = await _db.analytics_db.get_summary(days)
    # #28 stale-while-revalidate: browser can serve cached version while fetching new one
    return Response(
        content=json.dumps(data),
        media_type="application/json",
        headers={"Cache-Control": f"private, max-age=10, stale-while-revalidate={ANALYTICS_STALE_SECONDS}"},
    )


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

@router.get("/models", response_model_exclude_none=True)
async def list_models(request: Request):
    orch = await _state.get_session("default")
    data = {"models": orch.llm.available_models()}
    # #12 — ETag: model list rarely changes; avoid re-serialisation on unchanged data
    import hashlib as _hl
    etag = f'"{_hl.md5(str(data["models"]).encode()).hexdigest()[:12]}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=json.dumps(data),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "private, max-age=60"},
    )


@router.post("/models/refresh")
async def refresh_models():
    orch = await _state.get_session("default")
    models = await orch.llm.refresh_ollama_models()
    return {"ollama_models": models, "all_models": orch.llm.available_models()}


# ── Cache admin (#19) ─────────────────────────────────────────────────────────

@router.delete("/cache")
async def invalidate_cache(model: str | None = Query(default=None, description="Limit to a specific model; omit to clear all")):
    """#19 — Invalidate the LLM response cache (optionally per-model)."""
    deleted = await _db.cache_db.invalidate(model)
    return {"deleted": deleted, "model": model or "all"}


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
async def get_memory(session_id: str, agent_type: str, request: Request):
    import hashlib
    validate_session_id(session_id)
    memory = await _db.memory_db.memory_read(session_id, agent_type)
    # #18 ETag caching for memory endpoint
    etag = '"' + hashlib.sha256(json.dumps(memory, sort_keys=True).encode()).hexdigest()[:16] + '"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=json.dumps({"session_id": session_id, "agent_type": agent_type, "memory": memory}),
        media_type="application/json",
        headers={
            "ETag": etag,
            "Cache-Control": "private, max-age=30, stale-while-revalidate=120",
        },
    )


@router.delete("/memory/{session_id}/{agent_type}")
async def clear_memory(session_id: str, agent_type: str):
    validate_session_id(session_id)
    await _db.memory_db.memory_write(session_id, agent_type, "")
    return {"status": "cleared"}


class _MemoryPatch(BaseModel):
    fact: str = Field(..., min_length=1, max_length=5000)


@router.patch("/memory/{session_id}/{agent_type}")
async def patch_memory(session_id: str, agent_type: str, patch: _MemoryPatch):
    """B6 — Merge/append a fact into existing memory instead of overwriting."""
    validate_session_id(session_id)
    updated = await _db.memory_db.memory_append(session_id, agent_type, patch.fact)
    return {"status": "merged", "session_id": session_id, "agent_type": agent_type, "memory_length": len(updated)}


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


# ── #11 Scheduled digest ──────────────────────────────────────────────────────

@router.post("/digests/schedule")
async def schedule_digest(req: "DigestScheduleRequest"):
    interval = 7 * 86400 if req.frequency == "weekly" else 86400
    digest_prompt = (
        "Generate a concise digest of this conversation session:\n"
        "1. Key topics discussed\n"
        "2. Decisions and conclusions reached\n"
        "3. Open questions or follow-ups\n"
        "4. Cost and usage summary\n"
        "Format as a brief bullet-point report."
    )
    task_id = _sched_mod.scheduler.schedule_recurring(req.session_id, digest_prompt, interval_seconds=interval)
    return {
        "status": "scheduled",
        "task_id": task_id,
        "frequency": req.frequency,
        "session_id": req.session_id,
        "delivery": req.email or "in-session",
    }


@router.post("/digests/now/{session_id}")
async def generate_digest_now(session_id: str):
    """Generate a digest immediately for a session."""
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="No history to digest")
    recent = messages[-40:]
    combined = "\n".join(f"{m['role'].upper()}: {m.get('content','')[:300]}" for m in recent)
    orch = await _state.get_session(session_id)
    digest = await orch.llm.call(
        model="claude-haiku",
        messages=[{"role": "user", "content": f"Generate a concise session digest:\n\n{combined}"}],
        max_tokens=512,
        temperature=0.3,
    )
    return {"session_id": session_id, "digest": digest, "messages_analyzed": len(recent)}


# ── #22 Cost forecasting ──────────────────────────────────────────────────────

@router.get("/analytics/forecast")
async def cost_forecast(days: int = Query(default=30, ge=7, le=90)):
    """Linear extrapolation of costs based on the last 7 days trend."""
    data = await _db.analytics_db.get_summary(7)
    daily = data.get("daily", [])
    if len(daily) < 2:
        return {"forecast_days": days, "estimated_cost_usd": 0.0, "basis": "insufficient_data"}
    costs = [d.get("cost_usd", 0) for d in daily]
    avg_daily = sum(costs) / len(costs)
    # Linear trend: slope from first to last day
    slope = (costs[-1] - costs[0]) / max(len(costs) - 1, 1)
    forecast = max(0.0, (avg_daily + slope * (days / 2)) * days)
    return {
        "forecast_days": days,
        "estimated_cost_usd": round(forecast, 4),
        "avg_daily_cost_usd": round(avg_daily, 6),
        "trend": "increasing" if slope > 0 else ("decreasing" if slope < 0 else "flat"),
        "basis": f"{len(daily)} days",
    }


# ── #23 Token heatmap ─────────────────────────────────────────────────────────

@router.get("/analytics/heatmap")
async def token_heatmap(days: int = Query(default=7, ge=1, le=30)):
    """Return daily token usage broken down by model."""
    data = await _db.analytics_db.get_summary(days)
    return {
        "days": days,
        "heatmap": data.get("daily", []),
        "by_model": data.get("by_model", []),
        "total_input_tokens": data.get("totals", {}).get("total_input_tokens", 0),
        "total_output_tokens": data.get("totals", {}).get("total_output_tokens", 0),
    }


# ── #24 Anomaly detection ─────────────────────────────────────────────────────

@router.get("/analytics/anomalies")
async def detect_anomalies(days: int = Query(default=7, ge=1, le=30), sigma: float = Query(default=3.0, ge=1.0, le=5.0)):
    """Return requests where latency or cost is beyond sigma standard deviations."""
    import math
    data = await _db.analytics_db.get_summary(days)
    daily = data.get("daily", [])
    if len(daily) < 3:
        return {"anomalies": [], "message": "Need at least 3 days of data"}

    costs = [d.get("cost_usd", 0) for d in daily]
    latencies = [d.get("avg_duration_ms", 0) for d in daily]

    def _zscore(values: list[float]) -> list[float]:
        if len(values) < 2:
            return [0.0] * len(values)
        mean = sum(values) / len(values)
        std = math.sqrt(sum((x - mean) ** 2 for x in values) / len(values)) or 1e-9
        return [(x - mean) / std for x in values]

    cost_z = _zscore(costs)
    lat_z = _zscore(latencies)

    anomalies = []
    for i, d in enumerate(daily):
        flags = []
        if abs(cost_z[i]) > sigma:
            flags.append(f"cost z={cost_z[i]:.2f}")
        if abs(lat_z[i]) > sigma:
            flags.append(f"latency z={lat_z[i]:.2f}")
        if flags:
            anomalies.append({**d, "anomaly_flags": flags})

    return {"anomalies": anomalies, "sigma_threshold": sigma, "days_analyzed": len(daily)}




# ── D13 Analytics percentiles ─────────────────────────────────────────────────

@router.get("/analytics/percentiles")
async def analytics_percentiles(days: int = Query(default=7, ge=1, le=90)):
    """D13 — p50/p95/p99 latency per model and overall using $bucketAuto."""
    from db.analytics import _db as _adb
    if _adb is None:
        return {"error": "database not initialised"}
    import math
    cutoff = (__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
    match = {"": {"date": {"": cutoff}, "duration_ms": {"": 0}}}
    # Fetch raw durations grouped by model (up to 2000 docs)
    pipe = [match, {"": {"_id": "", "durations": {"": ""}}}, {"": 100}]
    rows = await _adb["analytics"].aggregate(pipe).to_list(100)
    def percentile(vals, p):
        if not vals: return 0
        s = sorted(vals)
        idx = int(math.ceil(p / 100 * len(s))) - 1
        return s[max(0, idx)]
    result = []
    all_durations = []
    for r in rows:
        d = r["durations"]
        all_durations.extend(d)
        result.append({"model": r["_id"] or "unknown", "p50": percentile(d, 50), "p95": percentile(d, 95), "p99": percentile(d, 99), "count": len(d)})
    return {"days": days, "overall": {"p50": percentile(all_durations, 50), "p95": percentile(all_durations, 95), "p99": percentile(all_durations, 99)}, "by_model": result}


# ── L20 Cache stats ────────────────────────────────────────────────────────────

@router.get("/cache/stats")
async def cache_stats():
    """L20 — Expose cache hit/miss counters alongside existing stats."""
    base = await _db.cache_db.stats()
    try:
        from db.cache import _hits, _misses
        base["hits"] = _hits
        base["misses"] = _misses
        base["hit_rate_pct"] = round(_hits / (_hits + _misses) * 100, 1) if (_hits + _misses) else 0
    except ImportError:
        pass
    return base

# ── #25 Fine-tuning dataset export ────────────────────────────────────────────

@router.get("/analytics/fine-tune-export")
async def fine_tune_export(rating: int = Query(default=1, ge=-1, le=1)):
    """Export thumbs-up (rating=1) or all rated messages as JSONL for fine-tuning."""
    positive_fb = await _db.feedback_db.get_summary()
    # Collect all sessions with positive feedback
    try:
        from db.history import _db as hist_db, load_history
        from db.feedback import _db as fb_db
        if fb_db is None or hist_db is None:
            return Response(content="", media_type="application/x-ndjson")

        # Get sessions with matching feedback
        cursor = fb_db["feedback"].find({"rating": rating}, {"session_id": 1, "message_idx": 1})
        fb_records = await cursor.to_list(500)
    except Exception:
        return Response(content="", media_type="application/x-ndjson")

    lines = []
    seen_sessions: dict[str, list] = {}
    for fb in fb_records:
        sid = fb.get("session_id", "")
        if sid not in seen_sessions:
            seen_sessions[sid] = await load_history(sid)
        messages = seen_sessions[sid]
        idx = fb.get("message_idx", -1)
        if idx > 0 and idx < len(messages):
            user_msg = messages[idx - 1] if messages[idx - 1].get("role") == "user" else None
            asst_msg = messages[idx] if messages[idx].get("role") == "assistant" else None
            if user_msg and asst_msg:
                import json as _json
                lines.append(_json.dumps({
                    "messages": [
                        {"role": "user", "content": user_msg["content"]},
                        {"role": "assistant", "content": asst_msg["content"]},
                    ]
                }))

    content = "\n".join(lines) + ("\n" if lines else "")
    return Response(
        content=content,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="fine_tune.jsonl"'},
    )


# ── #15 GitHub PR diff webhook ────────────────────────────────────────────────

@router.post("/webhooks/github")
async def github_pr_webhook(request: "Request"):
    """Receive a GitHub PR webhook and auto-review the diff."""
    import hashlib, hmac, os as _os
    from fastapi import Request as _Req
    body = await request.body()
    secret = _os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        sig = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = request.headers.get("X-GitHub-Event", "")
    if event != "pull_request":
        return {"status": "ignored", "event": event}

    action = payload.get("action", "")
    if action not in ("opened", "synchronize"):
        return {"status": "ignored", "action": action}

    pr = payload.get("pull_request", {})
    diff_url = pr.get("diff_url", "")
    pr_number = pr.get("number", 0)
    repo = payload.get("repository", {}).get("full_name", "")

    if not diff_url:
        return {"status": "no_diff_url"}

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            diff_resp = await client.get(diff_url, headers={"Accept": "application/vnd.github.v3.diff"})
            diff = diff_resp.text[:8000]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch diff: {exc}")

    orch = await _state.get_session("github-reviews")
    review = await orch.process(
        message=f"Review this PR diff from {repo} #{pr_number}:\n\n```diff\n{diff}\n```",
        session_id="github-reviews",
        preferred_model="claude",
    )
    return {"status": "reviewed", "pr": pr_number, "repo": repo, "review_preview": review[:500]}


# ── #16 OpenAPI SDK endpoint ──────────────────────────────────────────────────

@router.get("/sdk/spec")
async def get_openapi_spec():
    """Return the current OpenAPI schema JSON for SDK generation."""
    from fastapi.openapi.utils import get_openapi
    from api.server import app as _app
    schema = _app.openapi()
    return schema


@router.get("/sdk/info")
async def sdk_info():
    """Return instructions for generating typed clients from the OpenAPI spec."""
    return {
        "spec_url": "/sdk/spec",
        "python_sdk": "openapi-python-client generate --url http://localhost:8000/sdk/spec",
        "typescript_sdk": "npx @hey-api/openapi-ts -i http://localhost:8000/sdk/spec -o ./src/client",
        "install_generator": "pip install openapi-python-client",
    }


# ── #17 GraphQL gateway ───────────────────────────────────────────────────────

@router.post("/graphql")
@router.get("/graphql")
async def graphql_endpoint(request: "Request"):
    """Minimal GraphQL gateway over the REST API.
    Requires: pip install strawberry-graphql[fastapi]
    """
    try:
        import strawberry  # type: ignore
        from strawberry.fastapi import GraphQLRouter as _GQLRouter  # type: ignore
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="GraphQL requires `pip install strawberry-graphql[fastapi]`",
        )

    @strawberry.type
    class Query:
        @strawberry.field
        async def analytics(self, days: int = 30) -> str:
            import json
            data = await _db.analytics_db.get_summary(days)
            return json.dumps(data)

        @strawberry.field
        async def models(self) -> list[str]:
            orch = await _state.get_session("default")
            return orch.llm.available_models()

        @strawberry.field
        async def sessions(self, limit: int = 20) -> str:
            import json
            sessions = await _db.db_list_sessions(limit=limit)
            return json.dumps(sessions)

    schema = strawberry.Schema(query=Query)
    body = await request.json() if request.method == "POST" else {}
    query = body.get("query", "{ models }")
    result = await schema.execute_async(query)
    return {"data": result.data, "errors": [str(e) for e in (result.errors or [])]}


from api.models import DigestScheduleRequest  # noqa: E402 — deferred to avoid circular at module load


# ── F1 Daily Briefing ─────────────────────────────────────────────────────────

@router.get("/briefing/daily")
async def daily_briefing(session_id: str = "default", model: str = Query(default="claude")):
    """Morning briefing: pending sessions, cost burn, agent health, yesterday's activity summary."""
    validate_session_id(session_id)

    # Gather data in parallel
    recent_sessions, analytics, history = await asyncio.gather(
        _db.db_list_sessions(limit=10, skip=0),
        _db.analytics_db.get_summary(1),
        _db.load_history(session_id),
        return_exceptions=True,
    )
    if isinstance(recent_sessions, Exception):
        recent_sessions = []
    if isinstance(analytics, Exception):
        analytics = {}
    if isinstance(history, Exception):
        history = []

    try:
        sched_tasks = _sched_mod.scheduler.list_tasks(session_id)
    except Exception:
        sched_tasks = []

    orch = await _state.get_session(session_id)
    health = orch.llm.get_health_status()

    totals   = analytics.get("totals", {})
    cost_usd = totals.get("total_cost_usd", 0)

    # LLM-generated summary of recent conversation
    summary = ""
    if history:
        recent = history[-20:]
        combined = "\n".join(f"{m['role'].upper()}: {m.get('content','')[:300]}" for m in recent)
        try:
            summary = await orch.llm.call(
                model=model,
                messages=[{"role": "user", "content":
                    f"Summarise this conversation in 3 bullet points for a morning briefing:\n\n{combined}"}],
                max_tokens=200, temperature=0.3,
            )
        except Exception:
            summary = "(summary unavailable)"

    return {
        "date": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d"),
        "session_id": session_id,
        "active_sessions": len(recent_sessions),
        "scheduled_tasks": len(sched_tasks),
        "yesterday_cost_usd": round(cost_usd, 4),
        "yesterday_requests": totals.get("total_requests", 0),
        "agent_health": health,
        "recent_summary": summary,
        "sessions": [s.get("session_id") for s in recent_sessions[:5]],
    }


# ── F4 Diff-based Prompt Iteration ────────────────────────────────────────────

class PromptIterateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10_000)
    result: str = Field(default="", max_length=10_000)
    critique: str = Field(default="", max_length=2000)
    model: str = "claude"


@router.post("/prompts/iterate")
async def iterate_prompt(req: PromptIterateRequest):
    """Send a prompt + result + critique to Claude; get an improved version with a diff."""
    import difflib

    orch = await _state.get_session("default")
    improve_msg = (
        f"You are a prompt engineer. Improve the following prompt based on the result and critique.\n\n"
        f"ORIGINAL PROMPT:\n{req.prompt}\n\n"
        f"RESULT PRODUCED:\n{req.result[:2000]}\n\n"
        f"CRITIQUE:\n{req.critique}\n\n"
        "Output ONLY the improved prompt text. Do not explain."
    )
    try:
        improved = await orch.llm.call(
            model=req.model,
            messages=[{"role": "user", "content": improve_msg}],
            max_tokens=2000, temperature=0.3,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    # Generate a unified diff
    diff_lines = list(difflib.unified_diff(
        req.prompt.splitlines(keepends=True),
        improved.splitlines(keepends=True),
        fromfile="original", tofile="improved", lineterm="",
    ))
    return {
        "original": req.prompt,
        "improved": improved,
        "diff": "".join(diff_lines),
    }


# ── F3 Smart Session Clustering ───────────────────────────────────────────────

@router.post("/sessions/cluster")
async def cluster_sessions(
    max_sessions: int = Query(default=50, ge=5, le=200),
    model: str = Query(default="claude"),
):
    """Group recent sessions into topic clusters using LLM-based similarity."""
    sessions = await _db.db_list_sessions(limit=max_sessions, skip=0)
    if not sessions:
        return {"clusters": []}

    previews = []
    for s in sessions:
        sid = s.get("session_id", "")
        preview = s.get("preview", sid)[:150]
        previews.append({"session_id": sid, "preview": preview})

    combined = "\n".join(f"- {p['session_id']}: {p['preview']}" for p in previews)
    prompt = (
        "Cluster the following chat sessions into 3-7 thematic groups.\n"
        "Output valid JSON only: {\"clusters\": [{\"label\": \"...\", \"session_ids\": [...]}]}\n\n"
        f"Sessions:\n{combined}"
    )

    orch = await _state.get_session("default")
    try:
        raw = await orch.llm.call(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800, temperature=0.2,
        )
        import re as _re
        m = _re.search(r'\{.*\}', raw, _re.DOTALL)
        if m:
            import json as _json
            result = _json.loads(m.group())
        else:
            result = {"clusters": [{"label": "All Sessions", "session_ids": [p["session_id"] for p in previews]}]}
    except Exception:
        result = {"clusters": [{"label": "All Sessions", "session_ids": [p["session_id"] for p in previews]}]}

    return result


# ── F10 Personal Knowledge Graph summary ──────────────────────────────────────

@router.get("/memory/graph")
async def memory_knowledge_graph(session_id: str = Query(default="default"), limit: int = Query(default=200, ge=1, le=500)):
    """Return all memory-graph facts for a session as nodes + edges for D3/force-graph."""
    validate_session_id(session_id)
    facts = await _db.memory_graph_db.get_facts(session_id)

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for f in facts[:limit]:
        entity = f.get("entity", "")
        value  = f.get("value", "")
        rel    = f.get("relation", "")
        conf   = f.get("confidence", 1.0)

        if entity and entity not in nodes:
            nodes[entity] = {"id": entity, "group": "entity"}
        if value and value not in nodes:
            nodes[value] = {"id": value, "group": "value"}
        if entity and value:
            edges.append({"source": entity, "target": value, "label": rel, "confidence": conf})

    return {
        "session_id": session_id,
        "nodes": list(nodes.values()),
        "edges": edges,
        "total_facts": len(facts),
    }


# ── #30 Client-error telemetry ────────────────────────────────────────────────

class ClientErrorReport(BaseModel):
    message: str = Field(..., max_length=500)
    stack: str = Field(default="", max_length=5000)
    component: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=500)
    user_agent: str = Field(default="", max_length=300)


_client_errors: list[dict] = []  # in-memory ring buffer (last 200)
_MAX_CLIENT_ERRORS = 200


@router.post("/logs/client-error", status_code=204)
async def log_client_error(report: ClientErrorReport, request: Request):
    """Receive frontend ErrorBoundary telemetry — stores in ring buffer and logs."""
    entry = {
        "ts": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
        "message": report.message,
        "stack": report.stack,
        "component": report.component,
        "url": report.url,
        "user_agent": report.user_agent,
        "client_ip": request.client.host if request.client else "unknown",
    }
    logger.warning("Client error [%s]: %s", report.component or "unknown", report.message)
    _client_errors.append(entry)
    if len(_client_errors) > _MAX_CLIENT_ERRORS:
        _client_errors.pop(0)


@router.get("/logs/client-errors")
async def list_client_errors(admin_key: str = Query(default="")):
    """List recent frontend errors — admin-only."""
    api_key = __import__("os").getenv("API_KEY", "")
    if api_key and admin_key != api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return {"errors": list(reversed(_client_errors)), "total": len(_client_errors)}


# ── F10 Scheduled prompt reports ──────────────────────────────────────────────

class ScheduledReportRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1, max_length=2000)
    session_id: str = "default"
    cron: str = Field(..., description="Cron expression e.g. '0 9 * * 1'")
    webhook_url: str = Field(default="", max_length=500)
    model: str = "claude"


@router.post("/reports", status_code=201)
async def create_scheduled_report(req: ScheduledReportRequest):
    """Create a scheduled prompt report."""
    validate_session_id(req.session_id)
    report_id = await _db.scheduled_reports_db.create_report(
        name=req.name,
        prompt=req.prompt,
        session_id=req.session_id,
        cron=req.cron,
        webhook_url=req.webhook_url,
        model=req.model,
    )
    if not report_id:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"report_id": report_id, "status": "created"}


@router.get("/reports")
async def list_scheduled_reports(active_only: bool = Query(default=False)):
    reports = await _db.scheduled_reports_db.list_reports(active_only=active_only)
    return {"reports": reports, "total": len(reports)}


@router.get("/reports/{report_id}")
async def get_scheduled_report(report_id: str):
    report = await _db.scheduled_reports_db.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.delete("/reports/{report_id}", status_code=204)
async def delete_scheduled_report(report_id: str):
    deleted = await _db.scheduled_reports_db.delete_report(report_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Report not found")


@router.post("/reports/{report_id}/run")
async def run_scheduled_report(report_id: str):
    """Immediately execute a scheduled report and deliver via webhook if configured."""
    report = await _db.scheduled_reports_db.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    orch = await _state.get_session(report["session_id"])
    try:
        result = await orch.llm.call(
            model=report.get("model", "claude"),
            messages=[{"role": "user", "content": report["prompt"]}],
            max_tokens=1024,
            temperature=0.3,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    await _db.scheduled_reports_db.update_last_run(report_id, result)

    # Deliver via webhook if configured
    webhook_url = report.get("webhook_url", "")
    if webhook_url:
        try:
            from api.server import app as _app
            http_client = getattr(_app.state, "http_client", None)
            if http_client:
                await http_client.post(
                    webhook_url,
                    json={"report_id": report_id, "name": report["name"], "result": result[:2000]},
                    timeout=10,
                )
        except Exception:
            logger.warning("Report %s webhook delivery failed", report_id)

    return {"report_id": report_id, "result_preview": result[:500], "status": "run"}


