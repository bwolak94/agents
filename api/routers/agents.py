"""Agent management — system prompts, personas, macros, collaboration graph."""
from fastapi import APIRouter, HTTPException

import api.db as _db
import api.state as _state
from api.models import (
    AgentSystemPromptRequest, PersonaRequest,
    MacroRequest, WebhookToolRequest, PromptVersionRequest,
)

router = APIRouter()


# ── Agent system prompts ──────────────────────────────────────────────────────

@router.put("/agents/{agent_name}/system-prompt")
async def set_agent_system_prompt(agent_name: str, req: AgentSystemPromptRequest):
    from agents.agents import AGENT_REGISTRY, set_agent_system_prompt as _set
    if agent_name not in AGENT_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_name}' not found. Available: {list(AGENT_REGISTRY.keys())}",
        )
    _set(agent_name, req.system_prompt)
    for _, orch in _state.session_manager.iter_orchestrators():
        orch._agent_cache.pop(agent_name, None)
    return {"status": "updated", "agent": agent_name}


@router.delete("/agents/{agent_name}/system-prompt")
async def reset_agent_system_prompt(agent_name: str):
    from agents.agents import _system_prompt_overrides
    _system_prompt_overrides.pop(agent_name, None)
    for _, orch in _state.session_manager.iter_orchestrators():
        orch._agent_cache.pop(agent_name, None)
    return {"status": "reset", "agent": agent_name}


# ── Prompt versioning ─────────────────────────────────────────────────────────

@router.get("/agents/{agent_name}/prompt-versions")
async def list_prompt_versions(agent_name: str):
    return {"agent_name": agent_name, "versions": await _db.prompt_versions_db.list_versions(agent_name)}


@router.post("/agents/{agent_name}/prompt-versions")
async def save_prompt_version(agent_name: str, req: PromptVersionRequest):
    from agents.agents import AGENT_REGISTRY, set_agent_system_prompt
    if agent_name not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
    version = await _db.prompt_versions_db.save_version(
        agent_name, req.system_prompt, req.bump, req.author, req.changelog
    )
    set_agent_system_prompt(agent_name, req.system_prompt)
    for _, orch in _state.session_manager.iter_orchestrators():
        orch._agent_cache.pop(agent_name, None)
    return {"status": "saved", "agent_name": agent_name, "version": version}


@router.post("/agents/{agent_name}/prompt-versions/{version}/rollback")
async def rollback_prompt_version(agent_name: str, version: str):
    rolled = await _db.prompt_versions_db.rollback_to(agent_name, version)
    if not rolled:
        raise HTTPException(status_code=404, detail="Version not found")
    active = await _db.prompt_versions_db.get_active_version(agent_name)
    if active:
        from agents.agents import set_agent_system_prompt
        set_agent_system_prompt(agent_name, active["system_prompt"])
        for _, orch in _state.session_manager.iter_orchestrators():
            orch._agent_cache.pop(agent_name, None)
    return {"status": "rolled_back", "agent_name": agent_name, "version": version}


# ── Collaboration graph ───────────────────────────────────────────────────────

@router.get("/agents/collab-graph")
async def agent_collab_graph(session_id: str | None = None):
    from db.collab_graph import get_summary, get_graph
    summary_data = await get_summary()
    return {
        "summary": summary_data.get("edges", []),
        "recent": await get_graph(session_id),
    }


# ── Personas ──────────────────────────────────────────────────────────────────

@router.get("/personas")
async def list_personas():
    return {"personas": await _db.personas_db.list_personas()}


@router.post("/personas")
async def save_persona(req: PersonaRequest):
    await _db.personas_db.save_persona(req.name, req.system_prompt, req.description)
    return {"status": "saved", "name": req.name}


@router.delete("/personas/{name}")
async def delete_persona(name: str):
    deleted = await _db.personas_db.delete_persona(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Persona not found")
    return {"status": "deleted"}


# ── Macros ────────────────────────────────────────────────────────────────────

@router.get("/macros")
async def list_macros():
    return {"macros": await _db.macros_db.list_macros()}


@router.post("/macros")
async def save_macro(req: MacroRequest):
    await _db.macros_db.save_macro(req.name, req.template, req.description)
    return {"status": "saved", "name": req.name}


@router.delete("/macros/{name}")
async def delete_macro(name: str):
    deleted = await _db.macros_db.delete_macro(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Macro not found or is a builtin (cannot delete builtins)")
    return {"status": "deleted", "name": name}


@router.post("/macros/expand")
async def expand_macro_preview(body: dict):
    message = body.get("message", "")
    variables = body.get("variables", {})
    import api.preprocessor as _preprocessor
    processed, model_override = await _preprocessor.preprocess(message)
    if variables:
        from db.macros import expand_macro
        processed = expand_macro(processed, variables)
    return {"original": message, "expanded": processed, "model_override": model_override}


# ── Custom webhook tools ──────────────────────────────────────────────────────

@router.post("/tools/custom")
async def register_webhook_tool(req: WebhookToolRequest):
    from tools.tools import WebhookTool
    orch = await _state.get_session("default")
    orch.tools.register(req.name, WebhookTool(req.url, req.method))
    return {"status": "registered", "tool_name": req.name}
