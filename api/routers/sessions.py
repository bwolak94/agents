"""Session / history endpoints — /sessions/*, /history/*, /search, /broadcast"""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

import api.db as _db
import api.state as _state
from api.models import (
    SessionFindRequest, ImportContextRequest, IncrementalContextRequest,
    SessionTitleRequest, BroadcastRequest, SessionForkRequest,
)
from api.validators import validate_session_id

router = APIRouter()


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/history/{session_id}")
async def get_history(session_id: str):
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    return {"session_id": session_id, "messages": messages}


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

@router.get("/sessions")
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
