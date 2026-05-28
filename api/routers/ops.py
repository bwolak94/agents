"""Operational endpoints — health, analytics, models, schedule, memory, prompts,
feedback, tags, checkpoints, admin, batch, briefing."""
import asyncio
import csv
import io
import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

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

    status_code = 200 if overall == "ok" else 207
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={"status": overall, "checks": checks},
    )


# ── Stats / Analytics ─────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(session_id: str = "default"):
    orch = await _state.get_session(session_id)
    return orch.get_stats()


@router.get("/analytics")
@router.get("/analytics/summary")
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
from fastapi import Request  # noqa: E402
