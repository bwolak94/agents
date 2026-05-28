"""Chat endpoints — /chat/*"""
import asyncio
import json
import logging
import re
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import api.db as _db
import api.state as _state
from api.models import (
    ChatRequest, ChatResponse,
    CompareRequest, StructuredChatRequest,
    HandoffPipelineRequest, DebateRequest, FanOutRequest,
    VariantsRequest, GitDiffRequest, SupervisorRequest,
)
from api.validators import validate_session_id
import api.preprocessor as _preprocessor

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if req.request_id:
        _state.session_manager.check_request_id(req.request_id)

    _state.session_manager.check_session_rate_limit(req.session_id)

    # Max cost guard
    if float(__import__("os").getenv("MAX_REQUEST_COST_USD", "0")) > 0:
        try:
            orch_check = await _state.get_session(req.session_id)
            _state.session_manager.check_cost_limit(orch_check)
        except HTTPException:
            raise
        except Exception:
            pass

    try:
        lock = await _state.session_manager.acquire_lock(req.session_id)
        try:
            orch = await _state.get_session(req.session_id)

            if req.persona:
                try:
                    p = await _db.personas_db.get_persona(req.persona)
                    if p:
                        orch.set_persona(p.get("system_prompt", ""))
                except Exception:
                    pass

            processed_message, model_override = await _preprocessor.preprocess(req.message)
            if model_override and not req.preferred_model:
                req = req.model_copy(update={"preferred_model": model_override})

            message = processed_message
            if req.image_base64 or req.image_url:
                import base64
                if req.image_base64:
                    image_bytes = base64.b64decode(req.image_base64)
                else:
                    try:
                        import httpx as _httpx
                        async with _httpx.AsyncClient(timeout=10) as c:
                            r = await c.get(req.image_url)
                            image_bytes = r.content
                    except Exception as e:
                        image_bytes = None
                        logger.warning("Failed to fetch image from URL: %s", e)

                if image_bytes:
                    try:
                        img_response = await orch.llm.clients["gemini"].call(
                            messages=[{"role": "user", "content": message}],
                            system_prompt=None,
                            max_tokens=2048,
                            temperature=0.7,
                            stream=False,
                            image_data=image_bytes,
                        )
                        await orch._update_history(req.session_id, message, img_response)
                        orch.last_decision = type("D", (), {
                            "model": "gemini", "agent": "general_agent", "tools": [],
                            "reasoning": "multimodal vision routing", "complexity": "medium",
                        })()
                        return ChatResponse(
                            response=img_response, model_used="gemini",
                            agent_used="general_agent", tools_used=[],
                            reasoning="multimodal vision routing", duration_ms=0,
                        )
                    except Exception as e:
                        logger.warning("Vision call failed: %s — falling through to text", e)

            t_start = time.time()
            response = await orch.process(
                message=message, stream=False, show_routing=False,
                session_id=req.session_id, preferred_model=req.preferred_model,
                enable_reflection=req.enable_reflection, checkpoint_id=req.checkpoint_id,
            )
            duration_ms = int((time.time() - t_start) * 1000)
        finally:
            lock.release()

        d = orch.last_decision
        cost_stats = orch.llm.get_cost_stats()

        try:
            estimated = orch.llm.estimate_tokens(orch.conversation_history)
            context_limits = {"claude": 190_000, "claude-haiku": 190_000, "gemini": 1_000_000}
            limit = context_limits.get(d.model if d else "claude", 32_000)
            context_pct = round(estimated / limit * 100, 1)
        except Exception:
            context_pct = 0

        try:
            await _db.analytics_db.record_request(
                session_id=req.session_id,
                agent=d.agent if d else "unknown",
                model=d.model if d else "unknown",
                tools=d.tools if d else [],
                duration_ms=duration_ms,
                cost_usd=cost_stats.get("total_cost_usd", 0) if cost_stats else 0,
                context_pct=context_pct,
            )
        except Exception as exc:
            logger.warning("Failed to record analytics: %s", exc)

        asyncio.create_task(_state._auto_title_session(req.session_id, message, orch))
        asyncio.create_task(_state._auto_tag_session(req.session_id, message, response, orch))

        return ChatResponse(
            response=response,
            model_used=d.model if d else "unknown",
            agent_used=d.agent if d else "unknown",
            tools_used=d.tools if d else [],
            reasoning=d.reasoning if d else "",
            duration_ms=duration_ms,
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    async def generate():
        lock = await _state.session_manager.acquire_lock(req.session_id)
        try:
            orch = await _state.get_session(req.session_id)
            decision = await orch.router.route(req.message, orch.conversation_history)
            response = await orch.process(
                req.message, stream=False, show_routing=False,
                decision=decision, session_id=req.session_id,
            )
        finally:
            lock.release()
        yield f"data: {json.dumps({'type': 'routing', 'model': decision.model, 'agent': decision.agent, 'tools': decision.tools})}\n\n"
        yield f"data: {json.dumps({'type': 'response', 'content': response})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/chat/compare")
async def chat_compare(req: CompareRequest):
    orch = await _state.get_session(req.session_id)
    models = req.models or orch.llm.available_models()[:3]

    async def _call_model(model: str):
        try:
            t_start = time.time()
            response = await orch.llm.call(
                model=model,
                messages=[{"role": "user", "content": req.message}],
                max_tokens=1024,
            )
            return {"model": model, "response": response, "duration_ms": int((time.time() - t_start) * 1000), "error": None}
        except Exception as e:
            return {"model": model, "response": None, "duration_ms": 0, "error": str(e)}

    results = await asyncio.gather(*[_call_model(m) for m in models])
    return {"message": req.message, "results": list(results)}


@router.post("/chat/structured")
async def chat_structured(req: StructuredChatRequest):
    orch = await _state.get_session(req.session_id)
    schema_str = json.dumps(req.response_schema, indent=2) if req.response_schema else ""
    prompt = (
        f"{req.message}\n\nRespond with ONLY valid JSON matching this schema:\n{schema_str}"
        if schema_str else req.message
    )
    model = req.model or "claude"
    try:
        response = await orch.llm.call(
            model=model, messages=[{"role": "user", "content": prompt}],
            max_tokens=2048, temperature=0.2,
        )
        cleaned = re.sub(r"```(?:json)?\s*", "", response).strip()
        json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if json_match:
            cleaned = json_match.group(0)
        parsed = json.loads(cleaned)
        return {"response": parsed, "model_used": model, "valid": True}
    except json.JSONDecodeError:
        return {"response": response, "model_used": model, "valid": False, "error": "Response was not valid JSON"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/rag")
async def chat_rag(req: ChatRequest):
    validate_session_id(req.session_id)
    chunks = await _db.rag_db.search(req.session_id, req.message, limit=5)
    if not chunks:
        return {"response": "No relevant documents found in the knowledge base for this session.", "chunks_used": 0}
    ctx = "\n\n".join(f"[{c['title']}]\n{c['content']}" for c in chunks)
    orch = await _state.get_session(req.session_id)
    from agents.agents import DocumentAgent
    doc_agent = DocumentAgent(orch.llm, orch.tools)
    response = await doc_agent.run(
        message=req.message, model="claude", tool_names=[], conversation_history=[],
        session_id=req.session_id, active_persona=f"<context>\n{ctx}\n</context>",
    )
    return {"response": response, "chunks_used": len(chunks)}


@router.post("/chat/fan-out")
async def chat_fan_out(req: FanOutRequest):
    validate_session_id(req.session_id)
    from agents.agents import AGENT_REGISTRY
    agents = req.agents or list(AGENT_REGISTRY.keys())[:4]
    orch = await _state.get_session(req.session_id)
    return await orch.run_fan_out(message=req.message, agents=agents, session_id=req.session_id, model=req.model)


@router.post("/chat/pipeline")
async def chat_pipeline(req: HandoffPipelineRequest):
    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)
    result = await orch.run_pipeline(message=req.message, pipeline=req.pipeline, session_id=req.session_id)
    return {"response": result, "steps": len(req.pipeline)}


@router.post("/chat/debate")
async def chat_debate(req: DebateRequest):
    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)
    result = await orch.run_debate(
        topic=req.topic, session_id=req.session_id,
        rounds=req.rounds, model_a=req.model_a, model_b=req.model_b,
    )
    return {"response": result, "topic": req.topic, "rounds": req.rounds}


@router.post("/chat/variants")
async def chat_variants(req: VariantsRequest):
    orch = await _state.get_session(req.session_id)
    processed, model_override = await _preprocessor.preprocess(req.message)
    model = req.model or model_override or "claude"

    async def _call_once(idx: int) -> dict:
        try:
            result = await orch.llm.call(
                model=model, messages=[{"role": "user", "content": processed}],
                max_tokens=1024, temperature=req.temperature,
            )
            return {"variant": idx + 1, "response": result, "error": None}
        except Exception as e:
            return {"variant": idx + 1, "response": None, "error": str(e)}

    results = await asyncio.gather(*[_call_once(i) for i in range(req.count)])
    return {"message": req.message, "model": model, "variants": list(results)}


@router.post("/chat/git-diff")
async def chat_git_diff(req: GitDiffRequest):
    if not req.diff.strip():
        raise HTTPException(status_code=400, detail="diff must not be empty")
    focus_hint = f"\n\nFocus especially on: {req.focus}." if req.focus else ""
    prompt = (
        f"Review the following git diff carefully.{focus_hint}\n\n"
        "Provide structured feedback with these sections:\n"
        "1. **Summary** — what changed and why (inferred)\n"
        "2. **Correctness** — logic bugs, off-by-one errors, missing edge cases\n"
        "3. **Security** — injection risks, auth issues, exposed secrets, unsafe operations\n"
        "4. **Performance** — N+1 queries, unnecessary allocations, blocking calls\n"
        "5. **Style** — naming, readability, dead code\n"
        "6. **Tests needed** — what test cases should be added\n"
        "7. **Verdict** — LGTM / Needs changes / Major issues\n\n"
        f"```diff\n{req.diff[:8000]}\n```"
    )
    orch = await _state.get_session(req.session_id)
    response = await orch.llm.call(
        model="claude", messages=[{"role": "user", "content": prompt}],
        max_tokens=2048, temperature=0.2,
    )
    return {"review": response, "session_id": req.session_id}


@router.post("/chat/supervisor")
async def chat_supervisor(req: SupervisorRequest):
    validate_session_id(req.session_id)
    from core.supervisor import SupervisorAgent
    orch = await _state.get_session(req.session_id)
    supervisor = SupervisorAgent(orch, model=req.model or "claude")
    result = await supervisor.run(req.message, session_id=req.session_id)
    return {"response": result, "session_id": req.session_id}


@router.post("/chat/experiment/{experiment_id}")
async def chat_with_experiment(experiment_id: str, req: ChatRequest):
    variant = await _db.experiments_db.assign_variant(experiment_id, req.session_id)
    if not variant:
        raise HTTPException(status_code=404, detail="Experiment not found or inactive")

    agent_override = variant.get("agent", "general_agent")
    model_override = variant.get("model") or req.preferred_model

    orch = await _state.get_session(req.session_id)
    t_start = time.time()
    try:
        response = await orch.process(
            message=req.message, session_id=req.session_id,
            preferred_model=model_override, agent_override=agent_override,
        )
        duration_ms = int((time.time() - t_start) * 1000)
        await _db.experiments_db.record_result(
            experiment_id, variant["name"], req.session_id, "latency_ms", duration_ms
        )
        return {"response": response, "variant": variant["name"], "duration_ms": duration_ms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
