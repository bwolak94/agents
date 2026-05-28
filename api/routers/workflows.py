"""Workflow / experiment / tenant / marketplace endpoints."""
import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query

import api.db as _db
import api.state as _state
from api.models import (
    WorkflowRequest, WorkflowRunRequest, HumanResumeRequest,
    ExperimentRequest, TenantRequest,
)
from core.events import event_bus

router = APIRouter()

# ── Marketplace catalog (OCP: extend by appending, not modifying handlers) ───
_MARKETPLACE_CATALOG: list[dict] = [
    {"name": "code_agent",     "description": "Expert Python/JS developer",     "category": "dev",      "builtin": True},
    {"name": "research_agent", "description": "Web search and summarization",    "category": "research", "builtin": True},
    {"name": "data_agent",     "description": "Data analysis and visualization", "category": "data",     "builtin": True},
    {"name": "document_agent", "description": "RAG-powered document Q&A",        "category": "rag",      "builtin": True},
    {"name": "general_agent",  "description": "Generalist assistant",            "category": "general",  "builtin": True},
    {"name": "security_agent", "description": "Security audit and hardening",    "category": "security", "builtin": False,
     "system_prompt": "You are a security expert. Analyse code and configurations for vulnerabilities. Follow OWASP guidelines. Never provide working exploit code."},
    {"name": "devops_agent",   "description": "CI/CD, Docker, Kubernetes",       "category": "devops",   "builtin": False,
     "system_prompt": "You are a DevOps engineer specializing in CI/CD pipelines, Docker, Kubernetes, and cloud infrastructure. Prefer IaC approaches."},
    {"name": "sql_agent",      "description": "Natural language to SQL queries", "category": "data",     "builtin": False,
     "system_prompt": "You are a SQL expert. Convert natural language questions to efficient, correct SQL queries. Always explain the query you generate."},
    {"name": "test_agent",     "description": "Test generation specialist",      "category": "dev",      "builtin": False,
     "system_prompt": "You are a testing expert. Write comprehensive unit tests, integration tests, and test plans. Prefer pytest for Python, Jest for JS."},
    {"name": "writer_agent",   "description": "Technical writing and docs",      "category": "writing",  "builtin": False,
     "system_prompt": "You are a technical writer. Produce clear, concise documentation, READMEs, API docs, and tutorials."},
]


# ── LangGraph Workflows ────────────────────────────────────────────────────────

@router.post("/workflows")
async def save_workflow(req: WorkflowRequest):
    wid = await _db.workflows_db.save_workflow(req.workflow_id, req.name, req.definition)
    return {"status": "saved", "workflow_id": wid}


@router.get("/workflows")
async def list_workflows():
    return {"workflows": await _db.workflows_db.list_workflows()}


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    wf = await _db.workflows_db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    deleted = await _db.workflows_db.delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"status": "deleted", "workflow_id": workflow_id}


@router.post("/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, req: WorkflowRunRequest):
    wf = await _db.workflows_db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    from core.graph import StateGraph, END
    run_id = str(uuid.uuid4())
    orch = await _state.get_session(req.session_id)

    graph = StateGraph()
    defn = wf.get("definition", {})

    for node_spec in defn.get("nodes", []):
        name = node_spec["name"]
        node_type = node_spec.get("type", "llm")
        if node_type == "llm":
            from core.graph import make_llm_node
            graph.add_node(
                name,
                make_llm_node(orch, node_spec.get("prompt_key", "message"), node_spec.get("output_key", f"{name}_result"), node_spec.get("model", "")),
                False,
            )
        elif node_type == "human":
            from core.graph import make_human_node
            graph.add_node(name, make_human_node(node_spec.get("prompt", "Please provide input:")), True)
        else:
            from core.graph import make_transform_node
            graph.add_node(name, make_transform_node(lambda s: s), False)

    for edge_spec in defn.get("edges", []):
        src, dst = edge_spec["src"], edge_spec["dst"]
        ckey = edge_spec.get("condition_key")
        if ckey:
            mapping = edge_spec.get("mapping", {})
            graph.add_conditional_edge(src, lambda s, k=ckey: s.get(k, END), mapping)
        else:
            graph.add_edge(src, dst)

    async def _ws_event(event_type: str, node_name: str, state: dict) -> None:
        await event_bus.publish({
            "type": f"workflow_{event_type}", "run_id": run_id,
            "workflow_id": workflow_id, "node": node_name, "state_keys": list(state.keys()),
        }, session_id=req.session_id)

    graph.set_event_callback(_ws_event)

    initial = dict(req.initial_data)
    initial["__session_id__"] = req.session_id

    async def _run():
        result = await graph.run(initial, run_id=run_id, session_id=req.session_id, persist=req.persist)
        await event_bus.publish(
            {"type": "workflow_done", "run_id": run_id, "final_state": result.to_dict()},
            session_id=req.session_id,
        )

    asyncio.create_task(_run())
    return {"run_id": run_id, "workflow_id": workflow_id, "status": "started"}


@router.get("/workflows/runs/{run_id}")
async def get_workflow_run(run_id: str):
    run = await _db.workflows_db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/workflows/runs/{run_id}/resume")
async def resume_workflow(run_id: str, req: HumanResumeRequest):
    state = await _db.workflows_db.resume_run(run_id, req.human_response)
    if state is None:
        raise HTTPException(status_code=400, detail="Run not paused or not found")
    return {"status": "resumed", "run_id": run_id}


# ── A/B Experiments ───────────────────────────────────────────────────────────

@router.post("/experiments")
async def create_experiment(req: ExperimentRequest):
    eid = await _db.experiments_db.create_experiment(
        req.experiment_id, req.name, req.variants, req.traffic_split
    )
    return {"status": "created", "experiment_id": eid}


@router.get("/experiments")
async def list_experiments(status: str = ""):
    return {"experiments": await _db.experiments_db.list_experiments(status)}


@router.get("/experiments/{experiment_id}")
async def get_experiment(experiment_id: str):
    exp = await _db.experiments_db.get_experiment(experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return exp


@router.get("/experiments/{experiment_id}/summary")
async def experiment_summary(experiment_id: str):
    return {
        "experiment_id": experiment_id,
        "results": await _db.experiments_db.get_experiment_summary(experiment_id),
    }


@router.post("/experiments/{experiment_id}/stop")
async def stop_experiment(experiment_id: str):
    stopped = await _db.experiments_db.stop_experiment(experiment_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return {"status": "stopped", "experiment_id": experiment_id}


# ── Multi-tenant management ───────────────────────────────────────────────────

@router.post("/tenants")
async def create_tenant(req: TenantRequest):
    tid = await _db.tenants_db.create_tenant(req.tenant_id, req.name, req.plan, req.api_key)
    return {"status": "created", "tenant_id": tid}


@router.get("/tenants")
async def list_tenants():
    return {"tenants": await _db.tenants_db.list_tenants()}


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: str):
    t = await _db.tenants_db.get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return t


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str):
    deleted = await _db.tenants_db.delete_tenant(tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"status": "deleted", "tenant_id": tenant_id}


@router.get("/tenants/{tenant_id}/usage")
async def tenant_usage(tenant_id: str, days: int = Query(default=30, ge=1, le=90)):
    return {"tenant_id": tenant_id, "usage": await _db.tenants_db.get_usage(tenant_id, days)}


# ── Agent marketplace ─────────────────────────────────────────────────────────

@router.get("/marketplace")
async def marketplace_list(category: str = ""):
    catalog = _MARKETPLACE_CATALOG if not category else [a for a in _MARKETPLACE_CATALOG if a.get("category") == category]
    return {"agents": catalog, "total": len(catalog)}


@router.post("/marketplace/{agent_name}/install")
async def marketplace_install(agent_name: str):
    entry = next((a for a in _MARKETPLACE_CATALOG if a["name"] == agent_name), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Agent not in marketplace")
    if entry.get("builtin"):
        return {"status": "already_available", "agent_name": agent_name}
    sp = entry.get("system_prompt", "")
    if sp:
        from agents.agents import set_agent_system_prompt
        set_agent_system_prompt(agent_name, sp)
        for _, orch in _state.session_manager.iter_orchestrators():
            orch._agent_cache.pop(agent_name, None)
    return {"status": "installed", "agent_name": agent_name, "category": entry.get("category")}
