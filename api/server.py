"""
REST API server - FastAPI.
Run: uvicorn api.server:app --reload --port 8000
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import asyncio
import json

from core.orchestrator import AgentOrchestrator
from core.events import event_bus
from db.history import init_db, load_history, clear_history as db_clear_history, list_sessions as db_list_sessions, load_context
from config.settings import load_config

app = FastAPI(
    title="Agent System API",
    description="Multi-LLM Agent System - Claude, Gemini, Ollama",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

config = load_config()


@app.on_event("startup")
async def startup():
    await init_db(config.get("mongo_url", "mongodb://mongo:27017"))


# ─────────────────────────────────────────
# SESSION MANAGEMENT
# Each user has a separate conversation history.
# ─────────────────────────────────────────
_sessions: dict[str, tuple[AgentOrchestrator, float]] = {}
SESSION_TTL = 3600  # session expires after 1 hour of inactivity


async def get_session(session_id: str) -> AgentOrchestrator:
    """Return existing orchestrator for the session or create a new one (with history from MongoDB)."""
    now = time.time()

    # Remove expired sessions
    expired = [k for k, (_, t) in _sessions.items() if now - t > SESSION_TTL]
    for k in expired:
        del _sessions[k]

    if session_id not in _sessions:
        orch = AgentOrchestrator(config)
        # Load conversation history from MongoDB
        try:
            orch.conversation_history = await load_context(session_id)
        except Exception:
            pass
        _sessions[session_id] = (orch, now)
    else:
        orch, _ = _sessions[session_id]
        _sessions[session_id] = (orch, now)

    return _sessions[session_id][0]


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    stream: bool = False
    show_routing: bool = True


class ChatResponse(BaseModel):
    response: str
    model_used: str
    agent_used: str
    tools_used: list[str]
    reasoning: str


@app.get("/")
async def root():
    temp_orch = await get_session("default")
    return {
        "status": "running",
        "models": temp_orch.llm.available_models(),
        "active_sessions": len(_sessions),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to the agent system."""
    try:
        orch = await get_session(req.session_id)
        response = await orch.process(
            message=req.message,
            stream=False,
            show_routing=False,
            session_id=req.session_id,
        )
        d = orch.last_decision
        return ChatResponse(
            response=response,
            model_used=d.model if d else "unknown",
            agent_used=d.agent if d else "unknown",
            tools_used=d.tools if d else [],
            reasoning=d.reasoning if d else "",
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Stream the response as Server-Sent Events."""
    async def generate():
        orch = await get_session(req.session_id)

        # Route once — pass the result to process() to avoid routing twice
        decision = await orch.router.route(req.message)
        yield f"data: {json.dumps({'type': 'routing', 'model': decision.model, 'agent': decision.agent, 'tools': decision.tools, 'reasoning': decision.reasoning})}\n\n"

        response = await orch.process(
            req.message,
            stream=False,
            show_routing=False,
            decision=decision,  # pass pre-computed decision — no re-routing
        )
        yield f"data: {json.dumps({'type': 'response', 'content': response})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/history/{session_id}")
async def get_history(session_id: str):
    """Load chat history from MongoDB (used on page refresh)."""
    messages = await load_history(session_id)
    return {"session_id": session_id, "messages": messages}


@app.delete("/history/{session_id}")
async def clear_session_history(session_id: str):
    """Clear session history in MongoDB and in-memory."""
    await db_clear_history(session_id)
    if session_id in _sessions:
        orch, _ = _sessions[session_id]
        orch.clear_history()
    return {"status": "cleared", "session_id": session_id}


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Remove session from memory (MongoDB data is kept)."""
    if session_id in _sessions:
        del _sessions[session_id]
        return {"status": "deleted", "session_id": session_id}
    return {"status": "not_found", "session_id": session_id}


@app.get("/sessions")
async def list_sessions():
    """List sessions from MongoDB."""
    return {"sessions": await db_list_sessions()}


@app.get("/stats")
async def get_stats(session_id: str = "default"):
    """Session statistics (history + costs)."""
    orch = await get_session(session_id)
    return orch.get_stats()


@app.get("/models")
async def list_models():
    """List available models."""
    orch = await get_session("default")
    return {"models": orch.llm.available_models()}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time agent events - game world UI."""
    await websocket.accept()
    q = event_bus.subscribe()
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=25.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        event_bus.unsubscribe(q)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
