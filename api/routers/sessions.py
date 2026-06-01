"""Session / history endpoints — /sessions/*, /history/*, /search, /broadcast"""
import asyncio
import hashlib
import json
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

import api.db as _db
import api.state as _state
from api.models import (
    SessionFindRequest, ImportContextRequest, IncrementalContextRequest,
    SessionTitleRequest, BroadcastRequest, SessionForkRequest, SessionMergeRequest,
)
from api.validators import validate_session_id

router = APIRouter()


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/history/{session_id}")
async def get_history(session_id: str, request: Request):
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    body = json.dumps({"session_id": session_id, "messages": messages}, sort_keys=True, default=str)
    etag = f'"{hashlib.md5(body.encode()).hexdigest()}"'
    # B5 — X-Cache: HIT when client sends matching ETag
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "X-Cache": "HIT"})
    # #19 Last-Modified header
    last_modified = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "ETag": etag,
            "Cache-Control": "private, max-age=0, must-revalidate",
            "Last-Modified": last_modified,
            "X-Cache": "MISS",
        },
    )


@router.delete("/history/{session_id}")
async def clear_session_history(session_id: str):
    validate_session_id(session_id)
    await _db.db_clear_history(session_id)
    _state.session_manager.clear_history(session_id)
    return {"status": "cleared", "session_id": session_id}


@router.get("/history/{session_id}/export")
async def export_session(
    session_id: str,
    format: str = Query(default="json", pattern="^(json|md)$"),
):
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    if format == "md":
        lines = [f"# Chat Export — {session_id}\n"]
        for m in messages:
            role = m.get("role", "unknown").capitalize()
            ts = m.get("ts", "")
            lines.append(f"## {role} {f'({ts[:19]})' if ts else ''}\n\n{m.get('content', '')}\n")
        content = "\n---\n\n".join(lines)
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{session_id}.md"'},
        )
    return Response(
        content=json.dumps({"session_id": session_id, "messages": messages}, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{session_id}.json"'},
    )


@router.get("/history/{session_id}/export/jsonl")
async def export_session_jsonl(session_id: str):
    """#21 — Export session as JSONL (one message object per line)."""
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    lines = [json.dumps(m, ensure_ascii=False) for m in messages]
    return Response(
        content="\n".join(lines) + "\n",
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{session_id}.jsonl"'},
    )


# ── #13 Session forking ───────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/fork")
async def fork_session(session_id: str, req: SessionForkRequest):
    """Create a new session pre-loaded with history from session_id up to at_message_index."""
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Source session has no history")

    # Slice history
    if req.at_message_index >= 0:
        messages = messages[:req.at_message_index]
    if not messages:
        raise HTTPException(status_code=400, detail="No messages to fork (index too small)")

    # Write messages to new session
    from db.history import append_message
    for msg in messages:
        await append_message(
            req.new_session_id,
            msg.get("role", "user"),
            msg.get("content", ""),
        )

    # Preload the in-process orchestrator
    new_orch = await _state.get_session(req.new_session_id)
    new_orch.conversation_history = [
        {"role": m["role"], "content": m["content"]} for m in messages
    ]

    return {
        "status": "forked",
        "source_session_id": session_id,
        "new_session_id": req.new_session_id,
        "messages_copied": len(messages),
    }


@router.post("/history/{session_id}/replay")
async def replay_session(session_id: str, model: str = Query(...)):
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    user_messages = [m for m in messages if m.get("role") == "user"]
    if not user_messages:
        raise HTTPException(status_code=404, detail="No user messages to replay")

    orch = await _state.get_session("default")
    results = []
    history: list = []
    for msg in user_messages:
        try:
            response = await orch.llm.call(
                model=model,
                messages=history + [{"role": "user", "content": msg["content"]}],
                max_tokens=1024,
            )
            results.append({"user": msg["content"][:200], "response": response, "error": None})
            history.append({"role": "user", "content": msg["content"]})
            history.append({"role": "assistant", "content": response})
        except Exception as e:
            results.append({"user": msg["content"][:200], "response": None, "error": str(e)})
    return {"session_id": session_id, "model": model, "replay": results}


# ── Sessions ──────────────────────────────────────────────────────────────────

@router.get("/sessions", response_model_exclude_none=True)
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
):
    return {"sessions": await _db.db_list_sessions(limit=limit, skip=skip)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    validate_session_id(session_id)
    deleted = _state.session_manager.delete(session_id)
    return {"status": "deleted" if deleted else "not_found", "session_id": session_id}


@router.post("/sessions/find")
async def find_session(req: SessionFindRequest):
    from db.history import _db as hist_db
    if hist_db is None:
        return {"session_id": None, "sessions": []}
    try:
        cursor = hist_db["conversations"].find(
            {"$text": {"$search": req.query}},
            {"_id": 0, "session_id": 1, "preview": 1, "title": 1, "updated_at": 1,
             "score": {"$meta": "textScore"}},
        ).sort([("score", {"$meta": "textScore"})]).limit(5)
        results = await cursor.to_list(5)
        return {
            "query": req.query,
            "best_match": results[0]["session_id"] if results else None,
            "sessions": results,
        }
    except Exception:
        return {"session_id": None, "sessions": []}


@router.post("/sessions/{session_id}/import-context/{source_id}")
async def import_context(session_id: str, source_id: str, req: ImportContextRequest):
    validate_session_id(session_id)
    validate_session_id(source_id)
    source_history = await _db.load_history(source_id)
    if not source_history:
        raise HTTPException(status_code=404, detail="Source session has no history")

    orch = await _state.get_session(session_id)
    if req.summary_only:
        combined = "\n".join(
            f"{m['role'].upper()}: {m['content'][:200]}"
            for m in source_history[-20:]
        )
        try:
            summary = await orch.llm.call(
                model="claude-haiku",
                messages=[{"role": "user", "content": combined}],
                system_prompt="Summarize this conversation in 5 key bullet points. Output ONLY the bullets.",
                max_tokens=300, temperature=0.2,
            )
            context_block = f"<imported_context from='{source_id}'>\n{summary}\n</imported_context>"
        except Exception:
            context_block = f"<imported_context from='{source_id}'>\n{combined[:500]}\n</imported_context>"
        orch.conversation_history.insert(0, {"role": "user", "content": context_block})
        orch.conversation_history.insert(1, {"role": "assistant", "content": "Understood. I have the context from the imported session."})
    else:
        msgs = [{"role": m["role"], "content": m["content"]} for m in source_history[-10:]]
        orch.conversation_history = msgs + orch.conversation_history

    return {"status": "imported", "session_id": session_id, "source_id": source_id, "messages_imported": len(source_history)}


@router.post("/sessions/{session_id}/context")
async def add_incremental_context(session_id: str, req: IncrementalContextRequest):
    validate_session_id(session_id)
    orch = await _state.get_session(session_id)
    orch.conversation_history.append({"role": "user", "content": f"<context_addition>\n{req.context}\n</context_addition>"})
    orch.conversation_history.append({"role": "assistant", "content": "Context noted."})
    total = _state.session_manager.add_context(session_id, req.context)
    return {"status": "added", "session_id": session_id, "total_additions": total}


@router.get("/sessions/{session_id}/context")
async def get_incremental_context(session_id: str):
    validate_session_id(session_id)
    return {"session_id": session_id, "context_additions": _state.session_manager.get_context(session_id)}


@router.get("/sessions/{session_id}/title")
async def get_title(session_id: str):
    validate_session_id(session_id)
    title = await _db.get_session_title(session_id)
    return {"session_id": session_id, "title": title}


@router.put("/sessions/{session_id}/title")
async def set_title(session_id: str, req: SessionTitleRequest):
    validate_session_id(session_id)
    await _db.set_session_title(session_id, req.title)
    return {"status": "updated", "session_id": session_id, "title": req.title}


@router.post("/sessions/{session_id}/focus")
async def enable_focus(session_id: str):
    validate_session_id(session_id)
    _state.session_manager.enable_focus(session_id)
    return {"status": "focus_enabled", "session_id": session_id}


@router.delete("/sessions/{session_id}/focus")
async def disable_focus(session_id: str):
    validate_session_id(session_id)
    _state.session_manager.disable_focus(session_id)
    return {"status": "focus_disabled", "session_id": session_id}


@router.post("/sessions/{session_id}/persona/{persona_name}")
async def activate_persona(session_id: str, persona_name: str):
    validate_session_id(session_id)
    p = await _db.personas_db.get_persona(persona_name)
    if not p:
        raise HTTPException(status_code=404, detail="Persona not found")
    orch = await _state.get_session(session_id)
    orch.set_persona(p["system_prompt"])
    return {"status": "activated", "session_id": session_id, "persona": persona_name}


@router.delete("/sessions/{session_id}/persona")
async def deactivate_persona(session_id: str):
    validate_session_id(session_id)
    orch = await _state.get_session(session_id)
    orch.set_persona("")
    return {"status": "deactivated", "session_id": session_id}


# ── Search & Broadcast ────────────────────────────────────────────────────────

@router.get("/search")
async def search_conversations(q: str = Query(..., min_length=1)):
    from db.history import _db as hist_db
    if hist_db is None:
        return {"results": []}
    try:
        cursor = hist_db["conversations"].find(
            {"$text": {"$search": q}},
            {"_id": 0, "session_id": 1, "preview": 1, "updated_at": 1, "score": {"$meta": "textScore"}},
        ).sort([("score", {"$meta": "textScore"})]).limit(20)
        results = await cursor.to_list(length=20)
        return {"results": results}
    except Exception:
        cursor = hist_db["conversations"].find(
            {"messages.content": {"$regex": q, "$options": "i"}},
            {"_id": 0, "session_id": 1, "preview": 1, "updated_at": 1},
        ).limit(20)
        results = await cursor.to_list(length=20)
        return {"results": results}


@router.post("/sessions/merge")
async def merge_sessions(req: SessionMergeRequest):
    """Merge all messages from source_session_id into target_session_id."""
    if req.source_session_id == req.target_session_id:
        raise HTTPException(status_code=400, detail="Source and target sessions must differ")

    source_msgs = await _db.load_history(req.source_session_id)
    if not source_msgs:
        raise HTTPException(status_code=404, detail="Source session has no history")

    if req.deduplicate:
        target_msgs = await _db.load_history(req.target_session_id)
        target_contents = {(m.get("role"), m.get("content")) for m in target_msgs}
        source_msgs = [m for m in source_msgs if (m.get("role"), m.get("content")) not in target_contents]

    from db.history import append_message
    for msg in source_msgs:
        await append_message(req.target_session_id, msg.get("role", "user"), msg.get("content", ""))

    return {
        "status": "merged",
        "source_session_id": req.source_session_id,
        "target_session_id": req.target_session_id,
        "messages_merged": len(source_msgs),
    }


@router.post("/broadcast")
async def broadcast(req: BroadcastRequest):
    async def _send(session_id: str):
        try:
            orch = await _state.get_session(session_id)
            result = await orch.process(message=req.message, stream=False, session_id=session_id)
            return {"session_id": session_id, "response": result, "error": None}
        except Exception as e:
            return {"session_id": session_id, "response": None, "error": str(e)}

    results = await asyncio.gather(*[_send(sid) for sid in req.session_ids])
    return {"message": req.message, "results": list(results)}


# ── F2 Session summarization ──────────────────────────────────────────────────

@router.post("/sessions/{session_id}/summarize")
async def summarize_session(session_id: str, model: str = Query(default="claude")):
    """Chunk conversation history and produce a rolling summary."""
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="No history for session")

    orch = await _state.get_session(session_id)
    # Process in chunks of 20 messages
    chunk_size = 20
    summaries = []
    for i in range(0, len(messages), chunk_size):
        chunk = messages[i:i + chunk_size]
        combined = "\n".join(
            f"{m['role'].upper()}: {m.get('content', '')[:400]}" for m in chunk
        )
        try:
            summary = await orch.llm.call(
                model=model,
                messages=[{"role": "user", "content": f"Summarize this conversation chunk in 2-3 sentences:\n\n{combined}"}],
                max_tokens=200, temperature=0.3,
            )
            summaries.append({"chunk": i // chunk_size + 1, "summary": summary})
        except Exception as exc:
            summaries.append({"chunk": i // chunk_size + 1, "summary": f"[error: {exc}]"})

    # Final rolling summary
    all_summaries = "\n".join(s["summary"] for s in summaries)
    try:
        final = await orch.llm.call(
            model=model,
            messages=[{"role": "user", "content": f"Create a single coherent summary from these chunk summaries:\n\n{all_summaries}"}],
            max_tokens=400, temperature=0.3,
        )
    except Exception:
        final = all_summaries

    return {
        "session_id": session_id,
        "total_messages": len(messages),
        "chunks": len(summaries),
        "chunk_summaries": summaries,
        "final_summary": final,
    }


# ── F7 Conversation sentiment analysis ────────────────────────────────────────

@router.get("/sessions/{session_id}/sentiment")
async def session_sentiment(session_id: str, model: str = Query(default="claude")):
    """Analyse rolling sentiment across the conversation (positive/neutral/negative per turn)."""
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="No history for session")

    orch = await _state.get_session(session_id)
    # Sample up to 20 most recent user+assistant pairs
    pairs = []
    for i in range(0, len(messages) - 1, 2):
        if len(pairs) >= 10:
            break
        u = messages[i]
        a = messages[i + 1] if i + 1 < len(messages) else {}
        pairs.append((u.get("content", "")[:200], a.get("content", "")[:200]))

    results = []
    for idx, (user_msg, asst_msg) in enumerate(pairs):
        prompt = (
            f"Rate the sentiment of this exchange as one of: positive, neutral, negative.\n"
            f"User: {user_msg}\nAssistant: {asst_msg}\n"
            "Output ONLY one word: positive, neutral, or negative."
        )
        try:
            sentiment = await orch.llm.call(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=5, temperature=0.1,
            )
            sentiment = sentiment.strip().lower()
            if sentiment not in ("positive", "neutral", "negative"):
                sentiment = "neutral"
        except Exception:
            sentiment = "neutral"
        results.append({"turn": idx + 1, "sentiment": sentiment})

    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for r in results:
        counts[r["sentiment"]] = counts.get(r["sentiment"], 0) + 1
    dominant = max(counts, key=counts.__getitem__)

    return {
        "session_id": session_id,
        "overall": dominant,
        "breakdown": counts,
        "turns": results,
    }


# ── F8 Auto-generated session card ────────────────────────────────────────────

@router.get("/sessions/{session_id}/card")
async def session_card(session_id: str):
    """Return an auto-generated session summary card with title, tags, stats."""
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)

    # Gather metadata in parallel
    title = await _db.get_session_title(session_id) or "Untitled"
    tags = await _db.tags_db.get_tags(session_id)
    stats: dict = {}
    orch_loaded = False
    try:
        orch = await _state.get_session(session_id)
        stats = orch.llm.get_cost_stats() or {}
        orch_loaded = True
    except Exception:
        pass

    user_msgs = [m for m in messages if m.get("role") == "user"]
    asst_msgs = [m for m in messages if m.get("role") == "assistant"]
    first_msg = user_msgs[0].get("content", "")[:100] if user_msgs else ""
    last_msg = user_msgs[-1].get("content", "")[:100] if user_msgs else ""

    return {
        "session_id": session_id,
        "title": title,
        "tags": tags,
        "message_count": len(messages),
        "user_turns": len(user_msgs),
        "assistant_turns": len(asst_msgs),
        "first_message_preview": first_msg,
        "last_message_preview": last_msg,
        "cost_stats": stats,
    }


# ── F10 Session snapshot ───────────────────────────────────────────────────────

# ── B13 Token count ───────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/token-count")
async def session_token_count(session_id: str):
    """Return total estimated token count across all messages in a session."""
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    # ~4 chars per token (rough estimate)
    total_chars = sum(len(m.get("content", "")) for m in messages)
    total_tokens = total_chars // 4
    return {
        "session_id": session_id,
        "message_count": len(messages),
        "estimated_tokens": total_tokens,
        "total_chars": total_chars,
        "summarize_recommended": total_tokens > 50_000,
    }


class SnapshotRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


@router.post("/sessions/{session_id}/snapshot", status_code=201)
async def create_session_snapshot(
    session_id: str,
    req: SnapshotRequest,
    include_resume: bool = True,
    model: str = Query(default="claude"),
):
    """Freeze current conversation state as a named snapshot. Generates a resume prompt."""
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="No history to snapshot")

    # F9 — Generate a resume prompt summarising where we left off
    resume_prompt = ""
    if include_resume and messages:
        recent = messages[-30:]
        combined = "\n".join(f"{m['role'].upper()}: {m.get('content','')[:300]}" for m in recent)
        try:
            orch = await _state.get_session(session_id)
            resume_prompt = await orch.llm.call(
                model=model,
                messages=[{"role": "user", "content":
                    f"Write a 'resume prompt' for continuing this conversation later. "
                    "It should capture: what we were working on, what was decided, and what comes next. "
                    f"Max 150 words.\n\n{combined}"}],
                max_tokens=250, temperature=0.3,
            )
        except Exception:
            resume_prompt = ""

    from db.agent_checkpoints import save_checkpoint
    snapshot_id = await save_checkpoint(
        session_id=session_id,
        agent_type="snapshot",
        data={
            "name": req.name,
            "description": req.description,
            "messages": messages,
            "message_count": len(messages),
            "resume_prompt": resume_prompt,
            "created_at": __import__("datetime").datetime.utcnow().isoformat(),
        },
    )
    return {
        "session_id": session_id,
        "snapshot_id": snapshot_id,
        "name": req.name,
        "messages_captured": len(messages),
        "resume_prompt": resume_prompt,
        "status": "created",
    }
