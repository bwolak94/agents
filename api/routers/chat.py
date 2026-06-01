"""Chat endpoints — /chat/*"""
import asyncio
import hashlib
import json
import logging
import os
import re
import time

_CHAT_TIMEOUT  = float(os.getenv("CHAT_TIMEOUT_SECONDS", "120"))   # per-request timeout
_AGENT_TIMEOUT = float(os.getenv("AGENT_TIMEOUT_SECONDS", "30"))    # #17 per-agent in fan-out
_PII_LOG_ENABLED = os.getenv("PII_REDACTION", "false").lower() == "true"  # C15
from api.pii import scrub as _pii_scrub          # #2 shared PII module
from config.constants import CONTEXT_LIMITS       # #7 single source of truth

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

import api.db as _db
import api.state as _state
from api.models import (
    ChatRequest, ChatResponse,
    CompareRequest, StructuredChatRequest,
    HandoffPipelineRequest, DebateRequest, FanOutRequest,
    VariantsRequest, GitDiffRequest, SupervisorRequest, SimulateRequest,
)
from api.validators import validate_session_id
import api.preprocessor as _preprocessor

logger = logging.getLogger(__name__)
router = APIRouter()



# B1 — request coalescing: deduplicate identical concurrent /chat calls
# key: sha256(session_id + message) → (event, result_holder)
_coalesce_map: dict[str, tuple[asyncio.Event, list]] = {}


def _coalesce_key(session_id: str, message: str) -> str:
    return hashlib.sha256(f"{session_id}\x00{message}".encode()).hexdigest()[:32]


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    # B3/B9 — check idempotency: return cached response if key already processed
    effective_request_id = idempotency_key or req.request_id
    if effective_request_id:
        cached_resp = await _db.idempotency_db.get(effective_request_id)
        if cached_resp is not None:
            return JSONResponse(content=cached_resp, headers={"X-Idempotent-Replayed": "true", "X-Session-ID": req.session_id or ""})
        # Fall through: in-memory guard still catches same-process near-duplicate
        _state.session_manager.check_request_id(effective_request_id)

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

    # B1 — coalesce: if an identical request is already in-flight, wait for its result
    _ck = _coalesce_key(req.session_id or "", req.message)
    if _ck in _coalesce_map:
        _evt, _holder = _coalesce_map[_ck]
        await _evt.wait()
        if _holder:
            return _holder[0]

    _evt = asyncio.Event()
    _holder: list = []
    _coalesce_map[_ck] = (_evt, _holder)

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
            # F20 — UI-level system prompt override (from ABTestView, custom UIs, etc.)
            if req.system_prompt:
                orch.set_persona(req.system_prompt)

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

            # #3 — Chain-of-thought scratchpad (when requested)
            scratchpad = ""
            if req.show_scratchpad:
                scratchpad, message = await orch.get_scratchpad(message, model=req.preferred_model or "claude")

            # #14 — Smart context compression when history is large
            if len(orch.conversation_history) > 20:
                orch.conversation_history = await orch.smart_compress_history(message)

            async with asyncio.timeout(_CHAT_TIMEOUT):  # #3 per-request timeout
                response = await orch.process(
                    message=message, stream=False, show_routing=False,
                    session_id=req.session_id, preferred_model=req.preferred_model,
                    enable_reflection=req.enable_reflection, checkpoint_id=req.checkpoint_id,
                )
            duration_ms = int((time.time() - t_start) * 1000)

            # #2 — Self-evaluation + confidence-gated retry with different model
            self_eval_score = -1.0
            if req.enable_self_eval:
                self_eval_score = await orch.self_evaluate(message, response)
                import os as _os
                from llm.manager import _RETRY_ON_LOW_CONFIDENCE  # L19
                threshold = float(_os.getenv("SELF_EVAL_THRESHOLD", "0.6"))
                if _RETRY_ON_LOW_CONFIDENCE and 0 <= self_eval_score < threshold:
                    # Use a different model for the retry to get a fresh perspective
                    fallback = "gemini" if (req.preferred_model or "claude") == "claude" else "claude"
                    try:
                        response = await orch.process(
                            message=f"[Previous answer scored {self_eval_score:.2f}/1.0 — please give a significantly better response]\n\n{message}",
                            stream=False, show_routing=False,
                            session_id=req.session_id, preferred_model=fallback,
                        )
                    except Exception:
                        # Fallback model also failed — keep original response
                        pass

            # #6 — Confidence scoring (when self-eval is also on, reuse result)
            confidence = -1.0
            if req.enable_self_eval:
                confidence = self_eval_score  # self-eval IS the confidence proxy

        finally:
            lock.release()

        d = orch.last_decision
        cost_stats = orch.llm.get_cost_stats()

        try:
            estimated = orch.llm.estimate_tokens(orch.conversation_history)
            limit = CONTEXT_LIMITS.get(d.model if d else "claude", 32_000)  # #7
            context_pct = round(estimated / limit * 100, 1)
        except Exception:
            context_pct = 0

        # C12 — fire-and-forget analytics + request-log so lock is fully released first
        _agent  = d.agent  if d else "unknown"
        _model  = d.model  if d else "unknown"
        _tools  = d.tools  if d else []
        _cost   = cost_stats.get("total_cost_usd", 0) if cost_stats else 0

        async def _record_analytics():
            try:
                await _db.analytics_db.record_request(
                    session_id=req.session_id, agent=_agent, model=_model,
                    tools=_tools, duration_ms=duration_ms, cost_usd=_cost,
                    context_pct=context_pct,
                )
            except Exception as exc:
                logger.warning("Failed to record analytics: %s", exc)

        asyncio.create_task(_record_analytics())
        asyncio.create_task(_state._auto_title_session(req.session_id, message, orch))
        asyncio.create_task(_state._auto_tag_session(req.session_id, message, response, orch))

        # C12 — request log also as background task; C15 — scrub PII when enabled
        _log_msg  = _pii_scrub(message[:500])  if _PII_LOG_ENABLED else message[:500]
        _log_resp = _pii_scrub(response[:500]) if _PII_LOG_ENABLED else response[:500]

        async def _log_request():
            try:
                await _db.request_log_db.log_request(
                    session_id=req.session_id, message=_log_msg, model=_model,
                    response=_log_resp, duration_ms=duration_ms,
                )
            except Exception as exc:
                logger.debug("Request log failed: %s", exc)

        asyncio.create_task(_log_request())

        _resp = ChatResponse(
            response=response,
            model_used=d.model if d else "unknown",
            agent_used=d.agent if d else "unknown",
            tools_used=d.tools if d else [],
            reasoning=d.reasoning if d else "",
            duration_ms=duration_ms,
            scratchpad=scratchpad,
            confidence=confidence,
            self_eval_score=self_eval_score,
        )
        _holder.append(_resp)
        _resp_dict = _resp.model_dump()
        # B3 — store response for idempotent replay
        if effective_request_id:
            asyncio.create_task(_db.idempotency_db.store(effective_request_id, _resp_dict))
        # B6 — add X-Session-ID so clients can track which session was created/used
        return JSONResponse(
            content=_resp_dict,
            headers={"X-Session-ID": req.session_id or ""},
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Request timed out after {_CHAT_TIMEOUT:.0f}s")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled error in /chat")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # B1 — signal any waiters and remove from coalesce map
        _coalesce_map.pop(_ck, None)
        _evt.set()


_SESSION_TOKEN_BUDGET = int(os.getenv("SESSION_TOKEN_BUDGET", "0"))  # L13: 0 = unlimited
_SSE_KEEPALIVE_INTERVAL = float(os.getenv("SSE_KEEPALIVE_SECONDS", "15"))  # B1


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    async def generate():
        # #18 — detect client disconnect before acquiring lock
        if await req.is_disconnected():
            return

        # B4 — refuse new streams when server is draining
        try:
            from api.server import _shutting_down
            if _shutting_down:
                yield f"data: {json.dumps({'type': 'error', 'code': 'SHUTTING_DOWN', 'message': 'Server is shutting down'})}\n\n"
                return
        except ImportError:
            pass

        # L13 — session token budget pre-flight
        if _SESSION_TOKEN_BUDGET > 0:
            try:
                from db.analytics import _db as _adb
                if _adb is not None:
                    rows = await _adb["analytics"].aggregate([
                        {"$match": {"session_id": req.session_id}},
                        {"$group": {"_id": None, "total": {"$sum": {"$add": ["$input_tokens", "$output_tokens"]}}}},
                    ]).to_list(1)
                    session_tokens = rows[0]["total"] if rows else 0
                    if session_tokens >= _SESSION_TOKEN_BUDGET:
                        yield f"data: {json.dumps({'type': 'error', 'code': 'SESSION_BUDGET_EXCEEDED', 'detail': f'Session token budget {_SESSION_TOKEN_BUDGET} exceeded'})}\n\n"
                        return
            except Exception:
                pass

        # B1 — run LLM work in a background task; yield SSE keepalive comments while waiting
        _result_q: asyncio.Queue = asyncio.Queue()

        async def _do_work():
            lock = await _state.session_manager.acquire_lock(req.session_id)
            t0 = time.time()
            try:
                # W21 — emit typing indicator on the event bus
                from core.events import event_bus as _eb
                asyncio.create_task(_eb.emit_typing(req.session_id or ""))
                orch = await _state.get_session(req.session_id)
                decision = await orch.router.route(req.message, orch.conversation_history)
                async with asyncio.timeout(_CHAT_TIMEOUT):
                    resp = await orch.process(
                        req.message, stream=False, show_routing=False,
                        decision=decision, session_id=req.session_id,
                    )
                await _result_q.put({"ok": True, "response": resp, "decision": decision, "orch": orch, "duration_ms": int((time.time() - t0) * 1000)})
            except asyncio.TimeoutError:
                await _result_q.put({"ok": False, "timeout": True, "partial": ""})
            except Exception as exc:
                await _result_q.put({"ok": False, "timeout": False, "error": str(exc)})
            finally:
                lock.release()

        asyncio.create_task(_do_work())

        # Poll with keepalive comments until the result arrives
        while True:
            try:
                result = await asyncio.wait_for(_result_q.get(), timeout=_SSE_KEEPALIVE_INTERVAL)
                break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"  # B1 — SSE comment; proxies reset their timeout

        if not result["ok"]:
            if result.get("timeout"):
                yield f"data: {json.dumps({'type': 'error', 'code': 'TIMEOUT', 'detail': f'Request timed out after {_CHAT_TIMEOUT:.0f}s'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'code': 'ERROR', 'detail': result.get('error', 'Unknown error')})}\n\n"
            return

        response = result["response"]
        decision = result["decision"]
        orch = result["orch"]
        duration_ms = result["duration_ms"]

        # Record analytics
        try:
            cost_stats = orch.llm.get_cost_stats()
            cost_usd = cost_stats.get("total_cost_usd", 0) if cost_stats else 0
            est_tokens = orch.llm.estimate_tokens(orch.conversation_history)
            limit = CONTEXT_LIMITS.get(decision.model, 32_000)
            context_pct = round(est_tokens / limit * 100, 1)
            await _db.analytics_db.record_request(
                session_id=req.session_id, agent=decision.agent, model=decision.model,
                tools=decision.tools, duration_ms=duration_ms, cost_usd=cost_usd, context_pct=context_pct,
            )
        except Exception as exc:
            logger.warning("Analytics failed in /chat/stream: %s", exc)

        yield f"data: {json.dumps({'type': 'routing', 'model': decision.model, 'agent': decision.agent, 'tools': decision.tools})}\n\n"
        yield f"data: {json.dumps({'type': 'response', 'content': response, 'duration_ms': duration_ms})}\n\n"
        # #14 — emit cost event
        try:
            cost_stats = orch.llm.get_cost_stats()
            yield f"data: {json.dumps({'type': 'cost', 'usd': cost_stats.get('total_cost_usd', 0), 'model': decision.model})}\n\n"
        except Exception:
            pass
        # B6 — session ID in stream too (as a data event so clients can read it)
        yield f"data: {json.dumps({'type': 'session_id', 'session_id': req.session_id})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"X-Session-ID": req.session_id or ""})


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
    t_start = time.time()
    result = await orch.run_fan_out(message=req.message, agents=agents, session_id=req.session_id, model=req.model)
    # #21 Deduplicate fan-out responses by content hash before returning
    if isinstance(result, dict) and "responses" in result:
        seen_hashes: set[str] = set()
        deduped = []
        for r in result["responses"]:
            h = hashlib.md5(str(r.get("response", "")).strip().encode()).hexdigest()  # C14
            if h not in seen_hashes:
                seen_hashes.add(h)
                deduped.append(r)
        result = {**result, "responses": deduped, "deduped": len(result["responses"]) - len(deduped)}
    # #15 — record analytics
    try:
        await _db.analytics_db.record_request(
            session_id=req.session_id, agent="fan_out", model=req.model,
            tools=[], duration_ms=int((time.time() - t_start) * 1000), cost_usd=0, context_pct=0,
        )
    except Exception as exc:
        logger.warning("Analytics failed in /chat/fan-out: %s", exc)
    return result


@router.post("/chat/pipeline")
async def chat_pipeline(req: HandoffPipelineRequest):
    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)
    t_start = time.time()
    result = await orch.run_pipeline(message=req.message, pipeline=req.pipeline, session_id=req.session_id)
    # #15 — record analytics
    try:
        await _db.analytics_db.record_request(
            session_id=req.session_id, agent="pipeline", model="",
            tools=[], duration_ms=int((time.time() - t_start) * 1000), cost_usd=0, context_pct=0,
        )
    except Exception as exc:
        logger.warning("Analytics failed in /chat/pipeline: %s", exc)
    return {"response": result, "steps": len(req.pipeline)}


@router.post("/chat/debate")
async def chat_debate(req: DebateRequest):
    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)
    t_start = time.time()
    result = await orch.run_debate(
        topic=req.topic, session_id=req.session_id,
        rounds=req.rounds, model_a=req.model_a, model_b=req.model_b,
    )
    # #15 — record analytics
    try:
        await _db.analytics_db.record_request(
            session_id=req.session_id, agent="debate", model=f"{req.model_a}/{req.model_b}",
            tools=[], duration_ms=int((time.time() - t_start) * 1000), cost_usd=0, context_pct=0,
        )
    except Exception as exc:
        logger.warning("Analytics failed in /chat/debate: %s", exc)
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


@router.post("/chat/fan-out/stream")
async def chat_fan_out_stream(req: FanOutRequest):
    """Streaming fan-out: yields each agent result as it completes (SSE)."""
    validate_session_id(req.session_id)
    from agents.agents import AGENT_REGISTRY
    agents = req.agents or list(AGENT_REGISTRY.keys())[:4]
    orch = await _state.get_session(req.session_id)

    # B7 — bounded queue decouples producer tasks from SSE consumer
    _queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    _SENTINEL = object()

    async def _produce():
        async def _call_agent(agent_name: str) -> dict:
            t0 = time.time()
            try:
                agent_cls = AGENT_REGISTRY.get(agent_name)
                if not agent_cls:
                    return {"agent": agent_name, "error": "unknown agent", "response": None, "duration_ms": 0}
                agent = agent_cls(orch.llm, orch.tools)
                async with asyncio.timeout(_AGENT_TIMEOUT):  # #17 per-agent timeout
                    resp = await agent.run(
                        message=req.message, model=req.model,
                        tool_names=[], conversation_history=[], session_id=req.session_id,
                    )
                return {"agent": agent_name, "response": resp, "error": None, "duration_ms": int((time.time() - t0) * 1000)}
            except asyncio.TimeoutError:
                return {"agent": agent_name, "response": None, "error": f"timed out after {_AGENT_TIMEOUT:.0f}s", "duration_ms": int(_AGENT_TIMEOUT * 1000)}
            except Exception as exc:
                return {"agent": agent_name, "response": None, "error": str(exc), "duration_ms": 0}

        tasks = {asyncio.create_task(_call_agent(a)): a for a in agents}
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                await _queue.put(t.result())
        await _queue.put(_SENTINEL)

    asyncio.create_task(_produce())

    async def _generate():
        token_total = 0
        while True:
            item = await _queue.get()
            if item is _SENTINEL:
                break
            resp_text = item.get("response") or ""
            # L14 — emit running token count progress event
            token_total += len(resp_text.split()) * 4 // 3
            yield f"data: {json.dumps({'type': 'progress', 'tokens': token_total})}\n\n"
            yield f"data: {json.dumps(item)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@router.post("/chat/simulate")
async def chat_simulate(req: SimulateRequest):
    """Sandboxed simulation — runs without saving to conversation history."""
    validate_session_id(req.session_id)
    orch = await _state.get_session(req.session_id)
    model = req.model or "claude"

    messages: list[dict] = []
    current_msg = req.message
    results = []

    for turn in range(req.turns):
        try:
            response = await orch.llm.call(
                model=model,
                messages=messages + [{"role": "user", "content": current_msg}],
                system_prompt=req.system_prompt or None,
                max_tokens=1024,
                temperature=0.7,
            )
            messages.append({"role": "user", "content": current_msg})
            messages.append({"role": "assistant", "content": response})
            results.append({"turn": turn + 1, "user": current_msg, "assistant": response})
            current_msg = f"[Continue turn {turn + 2}]"
        except Exception as exc:
            results.append({"turn": turn + 1, "user": current_msg, "assistant": None, "error": str(exc)})
            break

    return {
        "session_id": req.session_id,
        "model": model,
        "system_prompt": req.system_prompt,
        "turns_completed": len(results),
        "results": results,
    }


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
