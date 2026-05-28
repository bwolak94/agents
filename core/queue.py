"""#27 — Async job queue for horizontal scaling.

Uses an in-process asyncio queue by default.
If REDIS_URL is set, uses Redis Streams for multi-process/multi-node support.

Usage:
    POST /chat/async          — enqueue a job, returns {job_id}
    GET  /chat/async/{job_id} — poll for result

Workers:
    Run workers/chat_worker.py to process jobs from Redis Streams.
"""
import asyncio
import json
import logging
import os
import time
import uuid
from enum import Enum

logger = logging.getLogger(__name__)

_REDIS_URL = os.getenv("REDIS_URL", "")
_STREAM_KEY = "agent:jobs"
_RESULT_TTL = 3600  # 1 hour


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


# ── In-process queue (no Redis) ───────────────────────────────────────────────

_in_memory_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
_in_memory_results: dict[str, dict] = {}


async def enqueue(session_id: str, message: str, preferred_model: str = "") -> str:
    """Add a chat job to the queue. Returns job_id."""
    job_id = str(uuid.uuid4())
    payload = {
        "job_id": job_id,
        "session_id": session_id,
        "message": message,
        "preferred_model": preferred_model,
        "enqueued_at": time.time(),
        "status": JobStatus.PENDING,
    }

    if _REDIS_URL:
        await _redis_enqueue(job_id, payload)
    else:
        _in_memory_results[job_id] = {"job_id": job_id, "status": JobStatus.PENDING, "result": None}
        await _in_memory_queue.put(payload)

    return job_id


async def get_result(job_id: str) -> dict | None:
    """Poll for job result. Returns None if job not found."""
    if _REDIS_URL:
        return await _redis_get_result(job_id)
    return _in_memory_results.get(job_id)


async def _set_result(job_id: str, result: str, error: str | None = None) -> None:
    status = JobStatus.FAILED if error else JobStatus.DONE
    if _REDIS_URL:
        await _redis_set_result(job_id, result, error, status)
    else:
        _in_memory_results[job_id] = {
            "job_id": job_id,
            "status": status,
            "result": result,
            "error": error,
            "completed_at": time.time(),
        }


async def process_next(orchestrator_fn) -> bool:
    """Process one job from the queue. Returns True if a job was processed."""
    if _REDIS_URL:
        return await _redis_process_next(orchestrator_fn)
    try:
        payload = _in_memory_queue.get_nowait()
    except asyncio.QueueEmpty:
        return False

    job_id = payload["job_id"]
    _in_memory_results[job_id] = {"job_id": job_id, "status": JobStatus.PROCESSING, "result": None}
    try:
        result = await orchestrator_fn(
            message=payload["message"],
            session_id=payload["session_id"],
            preferred_model=payload.get("preferred_model", ""),
        )
        await _set_result(job_id, result)
    except Exception as exc:
        logger.error("Job %s failed: %s", job_id, exc)
        await _set_result(job_id, "", str(exc))
    return True


# ── Redis backend ─────────────────────────────────────────────────────────────

async def _get_redis():
    try:
        import redis.asyncio as aioredis
        return aioredis.from_url(_REDIS_URL, decode_responses=True)
    except ImportError:
        raise RuntimeError("redis package not installed. Run: pip install redis")


async def _redis_enqueue(job_id: str, payload: dict) -> None:
    r = await _get_redis()
    await r.xadd(_STREAM_KEY, {"data": json.dumps(payload)})
    await r.setex(f"job:{job_id}", _RESULT_TTL, json.dumps({"job_id": job_id, "status": JobStatus.PENDING}))
    await r.aclose()


async def _redis_get_result(job_id: str) -> dict | None:
    r = await _get_redis()
    raw = await r.get(f"job:{job_id}")
    await r.aclose()
    return json.loads(raw) if raw else None


async def _redis_set_result(job_id: str, result: str, error: str | None, status: JobStatus) -> None:
    r = await _get_redis()
    doc = {"job_id": job_id, "status": status, "result": result, "error": error}
    await r.setex(f"job:{job_id}", _RESULT_TTL, json.dumps(doc))
    await r.aclose()


async def _redis_process_next(orchestrator_fn) -> bool:
    r = await _get_redis()
    msgs = await r.xreadgroup("workers", "worker-1", {_STREAM_KEY: ">"}, count=1, block=1000)
    if not msgs:
        await r.aclose()
        return False
    for _stream, entries in msgs:
        for msg_id, data in entries:
            payload = json.loads(data["data"])
            job_id = payload["job_id"]
            await r.setex(f"job:{job_id}", _RESULT_TTL, json.dumps({"job_id": job_id, "status": JobStatus.PROCESSING}))
            try:
                result = await orchestrator_fn(
                    message=payload["message"],
                    session_id=payload["session_id"],
                    preferred_model=payload.get("preferred_model", ""),
                )
                await _redis_set_result(job_id, result, None, JobStatus.DONE)
            except Exception as exc:
                await _redis_set_result(job_id, "", str(exc), JobStatus.FAILED)
            await r.xack(_STREAM_KEY, "workers", msg_id)
    await r.aclose()
    return True


def queue_depth() -> int:
    """Return approximate number of pending jobs (in-process queue)."""
    return _in_memory_queue.qsize()
