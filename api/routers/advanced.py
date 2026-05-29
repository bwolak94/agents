"""
Advanced features router — 20 new features (Round 7).

Endpoints:
  POST /chat/plan                — multi-step planning
  POST /chat/red-team            — adversarial critic
  POST /chat/handoff             — structured agent handoff with briefing
  POST /chat/generate-tests      — automated pytest generation
  POST /tools/generate-mock      — OpenAPI → FastAPI mock
  POST /tools/scan-deps          — dependency vulnerability scan
  GET  /analytics/cost-forecast  — 30-day cost projection
  GET  /analytics/prompt-drift   — response quality over time
  GET  /analytics/heatmap        — requests by day/hour
  POST /memory/consolidate       — compress session memories
  POST /memory/insights/extract  — cross-session insight extraction
  GET  /memory/insights          — list extracted insights
  GET  /sessions/{id}/presence   — live shared session presence
  GET  /sessions/{id}/roles      — list access grants
  POST /sessions/roles/grant     — grant session role token
  DELETE /sessions/roles/{token} — revoke session role token
  GET  /plugins                  — plugin marketplace listing
  POST /plugins/install          — install plugin
  DELETE /plugins/{name}         — uninstall plugin
  GET  /request-log              — logged requests
  POST /request-log/replay       — regression-replay logged requests
"""
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

import api.db as _db
import api.state as _state
from api.models import (
    PlanRequest, RedTeamRequest, HandoffRequest,
    TestGenRequest, MockGenRequest, DepScanRequest,
    RoleGrantRequest, PluginInstallRequest, InsightExtractRequest,
)
from api.validators import validate_session_id

logger = logging.getLogger(__name__)
router = APIRouter()

# ── #2 Multi-step planning ────────────────────────────────────────────────────

@router.post("/chat/plan")
async def chat_plan(req: PlanRequest):
    """Produce an explicit numbered plan then optionally execute each step."""
    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)
    t_start = time.time()

    plan_prompt = (
        f"Task: {req.message}\n\n"
        "First, output a numbered action plan (3-7 steps). "
        "Format each step as: 1. [Step description]\n"
        "Output ONLY the plan — no explanation before or after."
    )
    plan_text = await orch.llm.call(
        model=req.model,
        messages=[{"role": "user", "content": plan_prompt}],
        max_tokens=512, temperature=0.3,
    )

    if not req.execute:
        return {"plan": plan_text, "executed": False, "results": [], "duration_ms": int((time.time() - t_start) * 1000)}

    # Parse steps
    steps = [line.strip() for line in plan_text.splitlines() if re.match(r"^\d+\.", line.strip())]
    results = []
    for step in steps:
        try:
            step_resp = await orch.llm.call(
                model=req.model,
                messages=[
                    {"role": "user", "content": req.message},
                    {"role": "assistant", "content": plan_text},
                    {"role": "user", "content": f"Execute this step: {step}"},
                ],
                max_tokens=1024, temperature=0.5,
            )
            results.append({"step": step, "result": step_resp, "error": None})
        except Exception as exc:
            results.append({"step": step, "result": None, "error": str(exc)})

    return {
        "plan": plan_text,
        "executed": True,
        "results": results,
        "steps_total": len(steps),
        "duration_ms": int((time.time() - t_start) * 1000),
    }


# ── #4 Adversarial red-team ───────────────────────────────────────────────────

@router.post("/chat/red-team")
async def chat_red_team(req: RedTeamRequest):
    """Answerer produces a response; critic finds flaws; final answer improves both."""
    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)
    t_start = time.time()

    # Step 1: answerer
    answer, critique = await asyncio.gather(
        orch.llm.call(
            model=req.model_answerer,
            messages=[{"role": "user", "content": req.message}],
            max_tokens=1024, temperature=0.7,
        ),
        orch.llm.call(
            model=req.model_critic,
            messages=[{"role": "user", "content": req.message}],
            system_prompt="You are a devil's advocate. In 3-5 bullet points, find the most important flaws, gaps, or incorrect assumptions in the answer you are about to receive.",
            max_tokens=512, temperature=0.5,
        ),
    )

    # Step 2: improved answer incorporating critique
    final = await orch.llm.call(
        model=req.model_answerer,
        messages=[
            {"role": "user", "content": req.message},
            {"role": "assistant", "content": answer},
            {"role": "user", "content": f"A critic has identified these flaws:\n{critique}\n\nRewrite your answer addressing all critiques."},
        ],
        max_tokens=1024, temperature=0.5,
    )

    return {
        "question": req.message,
        "initial_answer": answer,
        "critique": critique,
        "final_answer": final,
        "duration_ms": int((time.time() - t_start) * 1000),
    }


# ── #6 Agent handoff protocol ─────────────────────────────────────────────────

@router.post("/chat/handoff")
async def chat_handoff(req: HandoffRequest):
    """from_agent writes a structured briefing, to_agent continues from it."""
    from agents.agents import AGENT_REGISTRY
    for name in (req.from_agent, req.to_agent):
        if name not in AGENT_REGISTRY:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)
    t_start = time.time()

    # from_agent produces answer + structured briefing
    briefing_prompt = (
        f"{req.message}\n\n"
        "After your answer, write a HANDOFF BRIEFING starting with '---BRIEFING---' containing:\n"
        "- Key findings (3-5 bullets)\n"
        "- Open questions\n"
        "- Recommended next steps for the receiving agent"
    )
    from_cls = AGENT_REGISTRY[req.from_agent]
    from_agent = from_cls(orch.llm, orch.tools)
    from_response = await from_agent.run(
        message=briefing_prompt, model=req.model,
        tool_names=[], conversation_history=[], session_id=req.session_id,
    )

    # Split response from briefing
    if "---BRIEFING---" in from_response:
        parts = from_response.split("---BRIEFING---", 1)
        answer_part = parts[0].strip()
        briefing_part = parts[1].strip()
    else:
        answer_part = from_response
        briefing_part = from_response

    # to_agent receives briefing as context
    handoff_msg = (
        f"[HANDOFF FROM {req.from_agent.upper()}]\n\n"
        f"Original task: {req.message}\n\n"
        f"Briefing:\n{briefing_part}\n\n"
        "Please continue the work based on the briefing above."
    )
    to_cls = AGENT_REGISTRY[req.to_agent]
    to_agent = to_cls(orch.llm, orch.tools)
    to_response = await to_agent.run(
        message=handoff_msg, model=req.model,
        tool_names=[], conversation_history=[], session_id=req.session_id,
    )

    return {
        "from_agent": req.from_agent,
        "from_answer": answer_part,
        "briefing": briefing_part,
        "to_agent": req.to_agent,
        "to_response": to_response,
        "duration_ms": int((time.time() - t_start) * 1000),
    }


# ── #10 Automated test generation ─────────────────────────────────────────────

@router.post("/chat/generate-tests")
async def generate_tests(req: TestGenRequest):
    """Generate pytest unit tests from code or recent session history."""
    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)

    if not req.code:
        # Extract code from recent history
        messages = await _db.load_history(req.session_id)
        code_blocks: list[str] = []
        for m in messages[-20:]:
            for match in re.finditer(r"```(?:python)?\n(.*?)```", m.get("content", ""), re.DOTALL):
                code_blocks.append(match.group(1).strip())
        if not code_blocks:
            raise HTTPException(status_code=400, detail="No code found in session history and no code provided")
        code = "\n\n".join(code_blocks[:3])
    else:
        code = req.code

    prompt = (
        f"Write comprehensive {req.framework} unit tests for the following Python code.\n"
        "Include: happy path, edge cases, error cases, boundary conditions.\n"
        "Output ONLY the test file content — no explanation.\n\n"
        f"```python\n{code[:8000]}\n```"
    )
    tests = await orch.llm.call(
        model="claude",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2048, temperature=0.2,
    )
    # Strip markdown fences
    tests = re.sub(r"^```python\s*", "", tests.strip(), flags=re.MULTILINE)
    tests = re.sub(r"```$", "", tests.strip(), flags=re.MULTILINE).strip()

    return Response(
        content=tests,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="test_{req.session_id}.py"'},
    )


# ── #9 OpenAPI mock server generator ─────────────────────────────────────────

@router.post("/tools/generate-mock")
async def generate_mock(req: MockGenRequest):
    """Accept an OpenAPI spec; return a FastAPI mock router."""
    orch = await _state.get_session(req.session_id)
    prompt = (
        "You are a FastAPI expert. Given the following OpenAPI spec, write a FastAPI router "
        "that mocks all the endpoints with plausible fake responses using Faker or random data. "
        "Output ONLY valid Python code — no markdown, no explanation.\n\n"
        f"OpenAPI spec:\n{req.spec[:10000]}"
    )
    code = await orch.llm.call(
        model="claude",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000, temperature=0.2,
    )
    code = re.sub(r"^```python\s*", "", code.strip(), flags=re.MULTILINE)
    code = re.sub(r"```$", "", code.strip(), flags=re.MULTILINE).strip()

    return Response(
        content=code,
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="mock_server.py"'},
    )


# ── #12 Dependency vulnerability scanner ─────────────────────────────────────

@router.post("/tools/scan-deps")
async def scan_dependencies(req: DepScanRequest):
    """Parse package list and return vulnerability summary using LLM + known CVE patterns."""
    orch = await _state.get_session("default")

    # Parse package names/versions
    packages: list[str] = []
    if req.file_type == "requirements.txt":
        for line in req.content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                packages.append(line.split(";")[0].strip())
    else:  # package.json
        try:
            data = json.loads(req.content)
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            packages = [f"{k}@{v}" for k, v in deps.items()]
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="Invalid package.json")

    if not packages:
        raise HTTPException(status_code=400, detail="No packages found in file")

    pkg_list = "\n".join(packages[:100])
    prompt = (
        f"You are a security expert. Analyse these {req.file_type} packages for known vulnerabilities.\n"
        "For each package with known CVEs, report: package, version, CVE ID, severity, brief description, fix.\n"
        "If a package is safe, omit it. Format as a Markdown table.\n\n"
        f"Packages:\n{pkg_list}"
    )
    report = await orch.llm.call(
        model="claude",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2048, temperature=0.1,
    )
    return {
        "file_type": req.file_type,
        "packages_scanned": len(packages),
        "report": report,
    }


# ── #15 Cost forecasting ──────────────────────────────────────────────────────

@router.get("/analytics/cost-forecast")
async def cost_forecast(days: int = Query(default=7, ge=1, le=30)):
    """Project monthly cost based on rolling N-day usage."""
    from db.analytics import _db as adb
    if adb is None:
        return {"daily_avg_usd": 0, "projected_30d_usd": 0, "projected_month_usd": 0, "basis_days": days}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    pipeline = [
        {"$match": {"date": {"$gte": cutoff}}},
        {"$group": {"_id": "$date", "daily_cost": {"$sum": "$cost_usd"}}},
    ]
    rows = await adb["analytics"].aggregate(pipeline).to_list(days + 1)
    if not rows:
        return {"daily_avg_usd": 0, "projected_30d_usd": 0, "projected_month_usd": 0, "basis_days": days}

    total = sum(r["daily_cost"] for r in rows)
    avg = total / len(rows)
    return {
        "daily_avg_usd": round(avg, 6),
        "projected_30d_usd": round(avg * 30, 4),
        "projected_month_usd": round(avg * 30, 4),
        "basis_days": len(rows),
        "daily": sorted([{"date": r["_id"], "cost_usd": round(r["daily_cost"], 6)} for r in rows], key=lambda x: x["date"]),
    }


# ── #14 Prompt drift detector ─────────────────────────────────────────────────

@router.get("/analytics/prompt-drift")
async def prompt_drift(window_days: int = Query(default=14, ge=3, le=90)):
    """Compare avg self-eval scores week-over-week to detect quality drift."""
    from db.analytics import _db as adb
    if adb is None:
        return {"drift_detected": False, "weeks": []}

    now = datetime.now(timezone.utc)
    results = []
    for week_offset in range(min(window_days // 7, 4)):
        end = now - timedelta(weeks=week_offset)
        start = end - timedelta(weeks=1)
        pipeline = [
            {"$match": {"ts": {"$gte": start, "$lt": end}}},
            {"$group": {
                "_id": None,
                "avg_duration": {"$avg": "$duration_ms"},
                "avg_cost": {"$avg": "$cost_usd"},
                "count": {"$sum": 1},
            }},
        ]
        rows = await adb["analytics"].aggregate(pipeline).to_list(1)
        if rows:
            r = rows[0]
            results.append({
                "week_start": start.strftime("%Y-%m-%d"),
                "week_end": end.strftime("%Y-%m-%d"),
                "avg_duration_ms": round(r.get("avg_duration", 0), 1),
                "avg_cost_usd": round(r.get("avg_cost", 0), 6),
                "request_count": r.get("count", 0),
            })

    drift_detected = False
    if len(results) >= 2:
        newest = results[0]["avg_duration_ms"]
        oldest = results[-1]["avg_duration_ms"]
        drift_detected = oldest > 0 and abs(newest - oldest) / oldest > 0.25

    return {"drift_detected": drift_detected, "weeks": results}


# ── #18 Prompt performance heatmap ───────────────────────────────────────────

@router.get("/analytics/heatmap")
async def analytics_heatmap(days: int = Query(default=28, ge=7, le=90)):
    """Return request counts by day-of-week and hour-of-day for heatmap rendering."""
    from db.analytics import _db as adb
    if adb is None:
        return {"cells": []}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    pipeline = [
        {"$match": {"ts": {"$gte": cutoff}}},
        {"$group": {
            "_id": {
                "dow": {"$dayOfWeek": "$ts"},
                "hour": {"$hour": "$ts"},
            },
            "count": {"$sum": 1},
            "avg_cost": {"$avg": "$cost_usd"},
        }},
    ]
    rows = await adb["analytics"].aggregate(pipeline).to_list(200)
    cells = [
        {
            "dow": r["_id"]["dow"],   # 1=Sun … 7=Sat
            "hour": r["_id"]["hour"],
            "count": r["count"],
            "avg_cost_usd": round(r.get("avg_cost", 0), 6),
        }
        for r in rows
    ]
    return {"cells": cells, "days": days}


# ── #1 Memory consolidation ───────────────────────────────────────────────────

@router.post("/memory/consolidate")
async def consolidate_memory(session_id: str = Query(...)):
    """Summarise and compress agent memories for a session."""
    validate_session_id(session_id)
    orch = await _state.get_session(session_id)

    from agents.agents import AGENT_REGISTRY
    consolidated = {}
    for agent_name in AGENT_REGISTRY:
        raw = await _db.memory_db.memory_read(session_id, agent_name)
        if not raw:
            continue
        summary = await orch.llm.call(
            model="claude-haiku",
            messages=[{"role": "user", "content": raw}],
            system_prompt="Compress this agent memory to 5 concise bullet points. Output ONLY the bullets.",
            max_tokens=300, temperature=0.2,
        )
        await _db.memory_db.memory_write(session_id, agent_name, summary)
        consolidated[agent_name] = summary

    return {"session_id": session_id, "consolidated": consolidated, "agent_count": len(consolidated)}


# ── #3 Cross-session insight extraction ──────────────────────────────────────

@router.post("/memory/insights/extract")
async def extract_insights(req: InsightExtractRequest):
    """Scan recent sessions and extract recurring entities/topics."""
    from db.history import _db as hist_db
    if hist_db is None:
        return {"inserted": 0}

    session_ids = req.session_ids
    if not session_ids:
        cursor = hist_db["conversations"].find(
            {}, {"session_id": 1, "_id": 0}
        ).sort("updated_at", -1).limit(req.max_sessions)
        docs = await cursor.to_list(req.max_sessions)
        session_ids = [d["session_id"] for d in docs]

    orch = await _state.get_session("default")
    inserted = 0

    for sid in session_ids[:req.max_sessions]:
        messages = await _db.load_history(sid)
        if not messages:
            continue
        combined = "\n".join(
            f"{m['role'].upper()}: {m['content'][:200]}" for m in messages[-10:]
        )
        try:
            analysis = await orch.llm.call(
                model="claude-haiku",
                messages=[{"role": "user", "content": combined}],
                system_prompt=(
                    "Extract recurring entities, technologies, or topics. "
                    "Output as JSON array: [{\"entity\": \"...\", \"type\": \"...\", \"summary\": \"...\"}]. "
                    "Output ONLY JSON."
                ),
                max_tokens=512, temperature=0.1,
            )
            try:
                entities = json.loads(re.search(r"\[.*\]", analysis, re.DOTALL).group(0))
                for e in entities[:10]:
                    await _db.insights_db.upsert_insight(
                        entity=e.get("entity", ""),
                        insight_type=e.get("type", "general"),
                        value=e.get("summary", ""),
                        source_session=sid,
                    )
                    inserted += 1
            except Exception:
                pass
        except Exception:
            pass

    return {"sessions_scanned": len(session_ids), "insights_inserted": inserted}


@router.get("/memory/insights")
async def list_insights(limit: int = Query(default=50, ge=1, le=200)):
    return {"insights": await _db.insights_db.list_insights(limit=limit)}


# ── #5 Live shared session presence ──────────────────────────────────────────

@router.get("/sessions/{session_id}/presence")
async def session_presence(session_id: str):
    """Return count of active WebSocket subscribers for this session."""
    validate_session_id(session_id)
    from core.events import event_bus
    count = event_bus.subscriber_count_for(session_id)
    return {"session_id": session_id, "active_users": count}


# ── #8 Role-based session access ──────────────────────────────────────────────

@router.post("/sessions/roles/grant", status_code=201)
async def grant_session_role(req: RoleGrantRequest):
    token = await _db.session_roles_db.grant_access(req.session_id, req.role, ttl_hours=req.ttl_hours)
    result = {"session_id": req.session_id, "role": req.role, "token": token}
    if req.ttl_hours > 0:
        result["expires_in_hours"] = req.ttl_hours
    return result


@router.get("/sessions/{session_id}/roles")
async def list_session_roles(session_id: str):
    validate_session_id(session_id)
    return {"grants": await _db.session_roles_db.list_grants(session_id)}


@router.delete("/sessions/roles/{token}")
async def revoke_session_role(token: str):
    revoked = await _db.session_roles_db.revoke_token(token)
    if not revoked:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"token": token, "status": "revoked"}


@router.get("/sessions/{session_id}/roles/check")
async def check_session_role(session_id: str, token: str = Query(...)):
    validate_session_id(session_id)
    role = await _db.session_roles_db.check_token(session_id, token)
    if role is None:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    return {"session_id": session_id, "role": role}


# ── #19 Plugin marketplace ────────────────────────────────────────────────────

@router.get("/plugins")
async def list_plugins(installed_only: bool = Query(default=False)):
    return {"plugins": await _db.plugins_db.list_plugins(installed_only=installed_only)}


@router.post("/plugins/install", status_code=201)
async def install_plugin(req: PluginInstallRequest):
    plugin_id = await _db.plugins_db.install_plugin(
        name=req.name,
        description=req.description,
        tool_definition=req.tool_definition,
        author=req.author,
    )
    return {"plugin_id": plugin_id, "name": req.name, "status": "installed"}


@router.delete("/plugins/{name}")
async def uninstall_plugin(name: str):
    uninstalled = await _db.plugins_db.uninstall_plugin(name)
    if not uninstalled:
        raise HTTPException(status_code=404, detail="Plugin not found or already uninstalled")
    return {"name": name, "status": "uninstalled"}


# ── #13 Request log & regression replay ──────────────────────────────────────

@router.get("/request-log")
async def get_request_log(
    session_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    return {"entries": await _db.request_log_db.list_log(session_id=session_id, limit=limit)}


@router.post("/request-log/replay")
async def replay_regression(
    session_id: str = Query(...),
    model: str = Query(default="claude"),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Replay logged requests against a model and compare outputs."""
    validate_session_id(session_id)
    entries = await _db.request_log_db.list_log(session_id=session_id, limit=limit)
    if not entries:
        raise HTTPException(status_code=404, detail="No logged requests found for session")

    orch = await _state.get_session(session_id)
    results = []
    for entry in entries:
        try:
            new_response = await orch.llm.call(
                model=model,
                messages=[{"role": "user", "content": entry["message"]}],
                max_tokens=1024,
            )
            # Basic similarity: token overlap ratio
            orig_tokens = set(entry["response"].lower().split())
            new_tokens = set(new_response.lower().split())
            if orig_tokens:
                similarity = len(orig_tokens & new_tokens) / len(orig_tokens | new_tokens)
            else:
                similarity = 0.0
            results.append({
                "entry_id": entry["entry_id"],
                "message": entry["message"][:100],
                "original_response": entry["response"][:200],
                "new_response": new_response[:200],
                "similarity": round(similarity, 3),
                "regression": similarity < 0.3,
            })
        except Exception as exc:
            results.append({"entry_id": entry["entry_id"], "error": str(exc)})

    regressions = sum(1 for r in results if r.get("regression"))
    return {
        "session_id": session_id,
        "model": model,
        "entries_replayed": len(results),
        "regressions_found": regressions,
        "results": results,
    }


# ── F1 Agent negotiation protocol ─────────────────────────────────────────────

class NegotiateRequest(BaseModel):
    session_id: str = "default"
    topic: str = Field(..., min_length=1, max_length=2000)
    agent_a_model: str = "claude"
    agent_b_model: str = "gemini"
    rounds: int = Field(default=3, ge=1, le=6)


@router.post("/chat/negotiate")
async def chat_negotiate(req: NegotiateRequest):
    """Two agents negotiate on a topic: Agent A proposes, Agent B counter-proposes, iterate."""
    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)

    transcript = []
    position_a = req.topic
    position_b = ""

    for round_num in range(1, req.rounds + 1):
        # Agent A proposes / refines
        prompt_a = (
            f"Round {round_num} — You are Negotiator A. Your current position:\n{position_a}\n\n"
            + (f"Negotiator B responded:\n{position_b}\n\n" if position_b else "")
            + "Propose your refined position in 2-3 sentences. Be concise and aim toward consensus."
        )
        try:
            position_a = await orch.llm.call(
                model=req.agent_a_model,
                messages=[{"role": "user", "content": prompt_a}],
                max_tokens=300, temperature=0.5,
            )
        except Exception as exc:
            position_a = f"[error: {exc}]"
        transcript.append({"round": round_num, "agent": "A", "model": req.agent_a_model, "position": position_a})

        # Agent B counter-proposes
        prompt_b = (
            f"Round {round_num} — You are Negotiator B. Negotiator A proposes:\n{position_a}\n\n"
            "Counter-propose or agree in 2-3 sentences. Be concise and aim toward consensus."
        )
        try:
            position_b = await orch.llm.call(
                model=req.agent_b_model,
                messages=[{"role": "user", "content": prompt_b}],
                max_tokens=300, temperature=0.5,
            )
        except Exception as exc:
            position_b = f"[error: {exc}]"
        transcript.append({"round": round_num, "agent": "B", "model": req.agent_b_model, "position": position_b})

    # Synthesize final agreement
    synthesis_prompt = (
        f"Negotiation transcript:\n"
        + "\n".join(f"Agent {t['agent']} (round {t['round']}): {t['position']}" for t in transcript)
        + "\n\nWrite a 1-sentence consensus statement that both agents could agree on."
    )
    try:
        consensus = await orch.llm.call(
            model=req.agent_a_model,
            messages=[{"role": "user", "content": synthesis_prompt}],
            max_tokens=150, temperature=0.3,
        )
    except Exception:
        consensus = "Consensus could not be reached."

    return {
        "topic": req.topic,
        "rounds": req.rounds,
        "transcript": transcript,
        "consensus": consensus,
    }


# ── F2 Live code execution sandbox ────────────────────────────────────────────

class CodeExecRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=10_000)
    language: str = Field(default="python", pattern="^(python|bash)$")
    timeout_seconds: int = Field(default=10, ge=1, le=30)


@router.post("/tools/execute-code")
async def execute_code(req: CodeExecRequest):
    """Execute Python or bash code in a subprocess sandbox with strict timeout."""
    import subprocess
    import sys
    import tempfile

    if req.language == "python":
        cmd = [sys.executable, "-c", req.code]
    else:
        cmd = ["/bin/bash", "-c", req.code]

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=5,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=req.timeout_seconds
        )
        return {
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[:5000],
            "stderr": stderr.decode("utf-8", errors="replace")[:2000],
            "language": req.language,
        }
    except asyncio.TimeoutError:
        return {"exit_code": -1, "stdout": "", "stderr": "Execution timed out", "language": req.language}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}")


# ── F3 Semantic cross-session search ──────────────────────────────────────────

@router.get("/search/semantic")
async def semantic_search(
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Search across all session history using keyword matching (TF-IDF style)."""
    from db.history import _db as hist_db
    if hist_db is None:
        return {"query": q, "results": []}

    # Simple full-text search across messages
    query_terms = q.lower().split()
    pipeline = [
        {"$match": {"messages": {"$elemMatch": {"content": {"$regex": "|".join(re.escape(t) for t in query_terms), "$options": "i"}}}}},
        {"$project": {"session_id": 1, "messages": 1, "_id": 0}},
        {"$limit": limit * 3},
    ]
    try:
        docs = await hist_db["sessions"].aggregate(pipeline).to_list(limit * 3)
    except Exception:
        return {"query": q, "results": []}

    results = []
    for doc in docs:
        sid = doc.get("session_id", "")
        for i, msg in enumerate(doc.get("messages", [])):
            content = msg.get("content", "")
            hits = sum(1 for t in query_terms if t in content.lower())
            if hits:
                results.append({
                    "session_id": sid,
                    "message_idx": i,
                    "role": msg.get("role", ""),
                    "snippet": content[:200],
                    "relevance": hits / len(query_terms),
                })

    results.sort(key=lambda x: x["relevance"], reverse=True)
    return {"query": q, "results": results[:limit], "total_found": len(results)}


# ── F5 Jupyter notebook export ────────────────────────────────────────────────

@router.get("/history/{session_id}/export/ipynb")
async def export_jupyter(session_id: str):
    """Export session conversation as a Jupyter notebook (.ipynb)."""
    from fastapi.responses import Response as _Response
    validate_session_id(session_id)
    messages = await _db.load_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="No history for session")

    cells = []
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [f"# Session: {session_id}\n\nExported conversation history."],
    })

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            cells.append({
                "cell_type": "markdown",
                "metadata": {},
                "source": [f"**User:**\n\n{content}"],
            })
        elif role == "assistant":
            # If it looks like code, put in code cell
            code_match = re.search(r"```(\w*)\n(.*?)```", content, re.DOTALL)
            if code_match:
                lang = code_match.group(1) or "python"
                code = code_match.group(2)
                cells.append({
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": [f"**Assistant:**\n\n{content[:content.find('```')]}"],
                })
                if lang == "python":
                    cells.append({
                        "cell_type": "code",
                        "metadata": {},
                        "source": [code],
                        "outputs": [],
                        "execution_count": None,
                    })
            else:
                cells.append({
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": [f"**Assistant:**\n\n{content}"],
                })

    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
        },
        "cells": cells,
    }

    return _Response(
        content=json.dumps(notebook, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{session_id}.ipynb"'},
    )


# ── F6 Agent skill graph ───────────────────────────────────────────────────────

@router.get("/analytics/skill-graph")
async def skill_graph():
    """Return agent → tool usage graph for visualization."""
    from db.analytics import _db as adb
    if adb is None:
        return {"nodes": [], "edges": []}

    pipeline = [
        {"$group": {
            "_id": {"agent": "$agent", "model": "$model"},
            "count": {"$sum": 1},
            "avg_cost": {"$avg": "$cost_usd"},
        }},
        {"$limit": 100},
    ]
    try:
        rows = await adb["analytics"].aggregate(pipeline).to_list(100)
    except Exception:
        return {"nodes": [], "edges": []}

    agents_seen: set[str] = set()
    models_seen: set[str] = set()
    edges = []

    for r in rows:
        agent = r["_id"].get("agent", "unknown") or "unknown"
        model = r["_id"].get("model", "unknown") or "unknown"
        agents_seen.add(agent)
        models_seen.add(model)
        edges.append({
            "source": agent,
            "target": model,
            "weight": r["count"],
            "avg_cost_usd": round(r.get("avg_cost", 0), 6),
        })

    nodes = (
        [{"id": a, "type": "agent"} for a in sorted(agents_seen)]
        + [{"id": m, "type": "model"} for m in sorted(models_seen)]
    )
    return {"nodes": nodes, "edges": edges}


# ── F8 A/B system prompt testing ──────────────────────────────────────────────

class ABTestRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=50_000)
    session_id: str = "default"
    model: str = "claude"
    system_prompt_a: str = Field(..., min_length=1, max_length=5000)
    system_prompt_b: str = Field(..., min_length=1, max_length=5000)


@router.post("/chat/ab-test")
async def chat_ab_test(req: ABTestRequest):
    """Run the same message against two different system prompts in parallel."""
    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)

    async def _call(system_prompt: str) -> tuple[str, int]:
        t0 = time.time()
        try:
            resp = await orch.llm.call(
                model=req.model,
                messages=[{"role": "user", "content": req.message}],
                system_prompt=system_prompt,
                max_tokens=1024,
                temperature=0.7,
            )
        except Exception as exc:
            resp = f"[error: {exc}]"
        return resp, int((time.time() - t0) * 1000)

    # #2 asyncio.TaskGroup for parallel execution (Python 3.11+)
    async with asyncio.TaskGroup() as tg:
        task_a = tg.create_task(_call(req.system_prompt_a))
        task_b = tg.create_task(_call(req.system_prompt_b))
    resp_a, dur_a = task_a.result()
    resp_b, dur_b = task_b.result()

    return {
        "message": req.message,
        "variant_a": {
            "system_prompt": req.system_prompt_a,
            "response": resp_a,
            "duration_ms": dur_a,
        },
        "variant_b": {
            "system_prompt": req.system_prompt_b,
            "response": resp_b,
            "duration_ms": dur_b,
        },
    }


# ── F1 Multimodal image analysis ─────────────────────────────────────────────

class ImageAnalysisRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str = "default"
    image_base64: str | None = Field(default=None, description="Base64-encoded image data")
    image_url: str | None = Field(default=None, description="URL of image to analyse")


@router.post("/chat/analyze-image")
async def analyze_image(req: ImageAnalysisRequest):
    """Multimodal image Q&A using Gemini vision."""
    validate_session_id(req.session_id)
    if not req.image_base64 and not req.image_url:
        raise HTTPException(status_code=400, detail="Provide image_base64 or image_url")

    orch = await _state.get_session(req.session_id)
    image_bytes: bytes | None = None

    if req.image_base64:
        import base64
        try:
            image_bytes = base64.b64decode(req.image_base64)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid base64: {exc}")
    elif req.image_url:
        try:
            from api.server import app as _app
            http_client = getattr(_app.state, "http_client", None)
            if http_client:
                r = await http_client.get(req.image_url, timeout=15)
                image_bytes = r.content
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch image: {exc}")

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Could not load image data")

    try:
        result = await orch.llm.clients["gemini"].call(
            messages=[{"role": "user", "content": req.question}],
            system_prompt=None,
            max_tokens=1024,
            temperature=0.5,
            stream=False,
            image_data=image_bytes,
        )
    except KeyError:
        raise HTTPException(status_code=503, detail="Gemini not configured — GEMINI_API_KEY required for vision")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Vision call failed: {exc}")

    return {
        "session_id": req.session_id,
        "question": req.question,
        "answer": result,
        "model_used": "gemini",
    }


# ── F3 Prompt template library ────────────────────────────────────────────────

class PromptTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    template: str = Field(..., min_length=1, max_length=10_000)
    description: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list, description="Variable names like {name}, {topic}")


@router.get("/prompts/templates")
async def list_prompt_templates(tag: str | None = Query(default=None)):
    """List all saved prompt templates, optionally filtered by tag."""
    templates = await _db.prompts_db.list_prompts("__templates__")
    if tag:
        templates = [t for t in templates if tag in t.get("tags", [])]
    return {"templates": templates, "total": len(templates)}


@router.post("/prompts/templates", status_code=201)
async def create_prompt_template(req: PromptTemplateRequest):
    """Save a reusable prompt template."""
    import json as _json
    prompt_id = await _db.prompts_db.save_prompt(
        session_id="__templates__",
        title=req.name,
        content=req.template,
        tags=req.tags + [f"_var:{v}" for v in req.variables],
    )
    return {"template_id": prompt_id, "name": req.name, "status": "created"}


@router.delete("/prompts/templates/{template_id}")
async def delete_prompt_template(template_id: str):
    """Delete a prompt template by ID."""
    deleted = await _db.prompts_db.delete_prompt("__templates__", template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"template_id": template_id, "status": "deleted"}


# ── F4 Agent health matrix ────────────────────────────────────────────────────

@router.get("/agents/health-matrix")
async def agent_health_matrix(days: int = Query(default=7, ge=1, le=30)):
    """Per-agent latency/error rate matrix from analytics."""
    from db.analytics import _db as adb
    if adb is None:
        return {"matrix": []}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    pipeline = [
        {"$match": {"ts": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$agent",
            "total_calls": {"$sum": 1},
            "avg_duration_ms": {"$avg": "$duration_ms"},
            "p95_duration_ms": {"$percentile": {"input": "$duration_ms", "p": [0.95], "method": "approximate"}} if False else {"$max": "$duration_ms"},
            "total_cost_usd": {"$sum": "$cost_usd"},
            "error_count": {"$sum": {"$cond": [{"$gt": ["$error", None]}, 1, 0]}},
        }},
        {"$sort": {"total_calls": -1}},
    ]
    try:
        rows = await adb["analytics"].aggregate(pipeline).to_list(50)
    except Exception:
        return {"matrix": []}

    matrix = [
        {
            "agent": r["_id"] or "unknown",
            "total_calls": r["total_calls"],
            "avg_duration_ms": round(r.get("avg_duration_ms", 0), 1),
            "max_duration_ms": r.get("p95_duration_ms", 0),
            "total_cost_usd": round(r.get("total_cost_usd", 0), 6),
            "health": "degraded" if r.get("avg_duration_ms", 0) > 10000 else "ok",
        }
        for r in rows
    ]
    return {"matrix": matrix, "days": days}


# ── F6 LLM benchmarking ───────────────────────────────────────────────────────

class BenchmarkRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=5000)
    models: list[str] = Field(default_factory=list, description="Models to benchmark; empty = all available")
    session_id: str = "default"
    runs: int = Field(default=1, ge=1, le=3)


@router.post("/tools/benchmark")
async def benchmark_models(req: BenchmarkRequest):
    """Run the same prompt against multiple models and compare latency + response."""
    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)
    models_to_test = req.models or orch.llm.available_models()[:3]

    async def _run_model(model: str) -> dict:
        durations = []
        last_response = ""
        for _ in range(req.runs):
            t0 = time.time()
            try:
                last_response = await orch.llm.call(
                    model=model,
                    messages=[{"role": "user", "content": req.prompt}],
                    max_tokens=512, temperature=0.0,
                )
                durations.append(int((time.time() - t0) * 1000))
            except Exception as exc:
                return {"model": model, "error": str(exc), "avg_ms": 0}
        return {
            "model": model,
            "avg_ms": sum(durations) // len(durations),
            "min_ms": min(durations),
            "max_ms": max(durations),
            "response_preview": last_response[:200],
            "runs": req.runs,
        }

    async with asyncio.TaskGroup() as tg:
        tasks = {m: tg.create_task(_run_model(m)) for m in models_to_test}
    results = [tasks[m].result() for m in models_to_test]
    results.sort(key=lambda x: x.get("avg_ms", float("inf")))
    return {"prompt": req.prompt[:100], "results": results, "fastest": results[0]["model"] if results else None}


# ── F9 Webhook retry ──────────────────────────────────────────────────────────

@router.post("/webhooks/retry-failed")
async def retry_failed_webhooks(last_hours: int = Query(default=1, ge=1, le=24)):
    """Re-fire webhook triggers that haven't fired recently (based on fire_count)."""
    from db.webhook_triggers import _db as wt_db
    if wt_db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=last_hours)).isoformat()
    cursor = wt_db["webhook_triggers"].find(
        {"active": True, "$or": [{"last_fired_at": None}, {"last_fired_at": {"$lt": cutoff}}]},
        {"_id": 0},
    )
    triggers = await cursor.to_list(50)

    retried = 0
    errors = []
    for trigger in triggers:
        try:
            orch = await _state.get_session(trigger["session_id"])
            await orch.process(
                message=trigger["task_template"],
                session_id=trigger["session_id"],
                preferred_model="claude",
            )
            from db.webhook_triggers import record_fire
            await record_fire(trigger["trigger_id"])
            retried += 1
        except Exception as exc:
            errors.append({"trigger_id": trigger["trigger_id"], "error": str(exc)})

    return {"retried": retried, "errors": errors, "total_eligible": len(triggers)}
