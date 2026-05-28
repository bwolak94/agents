"""Intelligence endpoints: dynamic tools (#4), agent delegation (#5), prompt playground (#12)."""
import asyncio
import logging
import textwrap
import time

from fastapi import APIRouter, HTTPException

import api.db as _db
import api.state as _state
from api.models import DynamicToolRequest, DelegateRequest, PlaygroundRequest

logger = logging.getLogger(__name__)
router = APIRouter()


# ── #4 Dynamic tool generation ────────────────────────────────────────────────

@router.post("/tools/dynamic")
async def create_dynamic_tool(req: DynamicToolRequest):
    """LLM writes a Python function at runtime; it becomes a callable tool."""
    system = textwrap.dedent("""
        You are a Python tool author. Write a single async Python function named `tool_fn`
        that accepts one string argument `message` and returns a string result.
        Output ONLY the raw Python code — no markdown fences, no explanation.
        The function must be safe: no file system access, no network calls, no subprocess.
        Example:
            async def tool_fn(message: str) -> str:
                return message.upper()
    """).strip()

    orch = await _state.get_session("default")
    code = await orch.llm.call(
        model="claude",
        messages=[{"role": "user", "content": f"Tool name: {req.name}\nDescription: {req.description}\n\nWrite the tool_fn."}],
        system_prompt=system,
        max_tokens=512,
        temperature=0.2,
    )

    # Strip fences
    import re
    code = re.sub(r"^```python\s*", "", code.strip(), flags=re.MULTILINE)
    code = re.sub(r"```$", "", code.strip(), flags=re.MULTILINE).strip()

    # Validate and compile
    try:
        globs: dict = {}
        exec(compile(code, "<dynamic_tool>", "exec"), globs)  # noqa: S102
        if "tool_fn" not in globs or not asyncio.iscoroutinefunction(globs["tool_fn"]):
            raise ValueError("Generated code must define async def tool_fn(message: str) -> str")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Code validation failed: {exc}")

    # Register as a tool in all live sessions
    fn = globs["tool_fn"]

    class _DynamicTool:
        _fn = fn
        async def run(self, message: str) -> str:
            return await self._fn(message)

    tool_instance = _DynamicTool()
    for _, orch in _state.session_manager.iter_orchestrators():
        orch.tools.register(req.name, tool_instance)

    return {"status": "registered", "tool_name": req.name, "code": code}


# ── #5 Agent delegation chain ─────────────────────────────────────────────────

@router.post("/chat/delegate")
async def chat_delegate(req: DelegateRequest):
    """Explicit agent-to-agent delegation: agent A processes task, passes result to agent B."""
    from agents.agents import AGENT_REGISTRY
    for name in (req.from_agent, req.to_agent):
        if name not in AGENT_REGISTRY:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    orch = await _state.get_session(req.session_id)
    t_start = time.time()

    # Step 1: from_agent processes the task
    from_response = await orch._run_agent_with_events(
        agent_name=req.from_agent,
        model=req.model or "claude",
        tools=[],
        message=req.message,
        agent_id=f"delegate-{req.from_agent}",
        session_id=req.session_id,
    )

    # Step 2: to_agent receives from_agent's output + original context
    handoff_message = (
        f"[Delegated from {req.from_agent}]\n\n"
        f"Original task: {req.message}\n\n"
        f"Previous analysis:\n{from_response}"
    )
    to_response = await orch._run_agent_with_events(
        agent_name=req.to_agent,
        model=req.model or "claude",
        tools=[],
        message=handoff_message,
        agent_id=f"delegate-{req.from_agent}-{req.to_agent}",
        session_id=req.session_id,
    )

    return {
        "from_agent": req.from_agent,
        "from_response": from_response,
        "to_agent": req.to_agent,
        "final_response": to_response,
        "duration_ms": int((time.time() - t_start) * 1000),
    }


# ── #12 Prompt playground ─────────────────────────────────────────────────────

@router.post("/prompts/compare")
async def prompt_compare(req: PlaygroundRequest):
    """Run the same prompt across N agents in parallel and return all responses."""
    from agents.agents import AGENT_REGISTRY
    agents = req.agents or list(AGENT_REGISTRY.keys())[:4]
    models = req.models or ["claude"]
    orch = await _state.get_session(req.session_id)

    async def _run_one(agent_name: str, model: str) -> dict:
        t = time.time()
        try:
            resp = await orch._run_agent_with_events(
                agent_name=agent_name,
                model=model,
                tools=[],
                message=req.prompt,
                agent_id=f"playground-{agent_name}-{model}",
                session_id=req.session_id,
            )
            return {"agent": agent_name, "model": model, "response": resp,
                    "duration_ms": int((time.time() - t) * 1000), "error": None}
        except Exception as e:
            return {"agent": agent_name, "model": model, "response": None,
                    "duration_ms": int((time.time() - t) * 1000), "error": str(e)}

    tasks = [_run_one(a, m) for a in agents for m in models]
    results = await asyncio.gather(*tasks)

    return {
        "prompt": req.prompt,
        "session_id": req.session_id,
        "results": list(results),
        "total_runs": len(results),
    }
