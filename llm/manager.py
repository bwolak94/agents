"""
LLM Manager - unified interface to all models.
Supports: Claude (Anthropic), Gemini (Google), Ollama (local models)
"""
import os
import asyncio
import logging
import random
import sys
import time
from typing import Optional
import httpx

_mgr_logger = logging.getLogger("llm.manager")

# L23 — module-level cache imports (safe: db.cache guards on _db is None)
try:
    from db.cache import get as _cache_get, put as _cache_put
except ImportError:
    _cache_get = _cache_put = None  # type: ignore[assignment]

# L16 — per-model RPM throttle: track request timestamps per model
import json as _json
from collections import deque as _deque

_model_rpm_limits: dict[str, int] = {}
try:
    _model_rpm_limits = _json.loads(os.getenv("MODEL_RPM_LIMITS", "{}"))
except Exception:
    pass
_model_req_windows: dict[str, _deque] = {}

# L17 — usage webhook URL (optional)
_USAGE_WEBHOOK_URL = os.getenv("USAGE_WEBHOOK_URL", "")

# L19 — global flag to control whether low-confidence retry actually fires
_RETRY_ON_LOW_CONFIDENCE = os.getenv("RETRY_ON_LOW_CONFIDENCE", "true").lower() == "true"


# ─────────────────────────────────────────
# COST TRACKER
# ─────────────────────────────────────────
class CostTracker:
    """Tracks token usage and estimated costs for Anthropic API calls."""

    # Prices per 1M tokens (USD), as of 2025
    PRICES = {
        "sonnet": {"input": 3.0,  "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
        "haiku":  {"input": 0.80, "output": 4.0,  "cache_write": 1.00, "cache_read": 0.08},
    }

    def __init__(self):
        self.total_cost = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
        self.call_count = 0

    def record(self, model_variant: str, usage: dict) -> float:
        p = self.PRICES.get(model_variant, self.PRICES["sonnet"])
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        cw  = usage.get("cache_creation_input_tokens", 0)
        cr  = usage.get("cache_read_input_tokens", 0)

        cost = (
            inp / 1_000_000 * p["input"] +
            out / 1_000_000 * p["output"] +
            cw  / 1_000_000 * p["cache_write"] +
            cr  / 1_000_000 * p["cache_read"]
        )
        self.total_cost      += cost
        self.input_tokens    += inp
        self.output_tokens   += out
        self.cache_write_tokens += cw
        self.cache_read_tokens  += cr
        self.call_count      += 1
        return cost

    def summary(self) -> dict:
        return {
            "total_cost_usd":      round(self.total_cost, 6),
            "input_tokens":        self.input_tokens,
            "output_tokens":       self.output_tokens,
            "cache_read_tokens":   self.cache_read_tokens,
            "cache_write_tokens":  self.cache_write_tokens,
            "call_count":          self.call_count,
        }


# ── Circuit Breaker ───────────────────────────────────────────────────────────
import enum
import logging as _logging

_cb_logger = _logging.getLogger("llm.circuit_breaker")

class _CBState(enum.Enum):
    CLOSED    = "closed"     # normal operation — calls pass through
    OPEN      = "open"       # circuit tripped — all calls blocked
    HALF_OPEN = "half_open"  # test phase — one call allowed

_CB_FAILURE_THRESHOLD = int(os.getenv("CB_FAILURE_THRESHOLD", "3"))
_CB_RESET_TIMEOUT     = int(os.getenv("CB_RESET_TIMEOUT", "60"))   # secs before HALF_OPEN


class LLMManager:
    # Model health tracking (Imp 6): unhealthy models are skipped for _HEALTH_COOLDOWN seconds
    _HEALTH_COOLDOWN = 300  # 5 minutes

    def __init__(self, config: dict):
        self.config = config
        self.clients = {}
        self._unhealthy: dict[str, float] = {}  # model -> timestamp marked unhealthy
        # Circuit breaker state per model
        self._cb_failures: dict[str, int] = {}
        self._cb_open_at: dict[str, float] = {}
        self._cb_state: dict[str, _CBState] = {}
        self._init_clients()

    def _init_clients(self):
        """Initialize API clients."""
        # Anthropic (Claude)
        if self.config.get("anthropic_api_key"):
            self.clients["claude"] = AnthropicClient(self.config["anthropic_api_key"])

        # Google (Gemini)
        if self.config.get("gemini_api_key"):
            self.clients["gemini"] = GeminiClient(self.config["gemini_api_key"])

        # Ollama (local models)
        ollama_url = self.config.get("ollama_url", "http://ollama:11434")
        self.clients["ollama"] = OllamaClient(ollama_url)

    async def call(
        self,
        model: str,
        messages: list,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        stream: bool = False,
        stream_callback=None,
    ) -> str:
        """
        Call any model through a unified interface.

        model: "claude" | "claude-haiku" | "gemini" | "ollama/llama3" | "ollama/mistral" | "ollama/phi3"
        stream_callback: optional callable(token: str) invoked for each streamed token
        """
        self.check_token_budget(messages, system_prompt, max_tokens, model)

        # Check response cache (skip for streaming requests) — L23: use module-level import
        if not stream and not stream_callback:
            try:
                if _cache_get is not None:
                    cached = await _cache_get(model, messages, system_prompt)
                    if cached is not None:
                        return cached
            except Exception:
                pass

        from config.constants import LLM_TIMEOUT_SECONDS, LLM_FALLBACK_CHAIN, CONTEXT_LIMITS
        timeout = LLM_TIMEOUT_SECONDS
        t_start = time.perf_counter()

        # B14 — OTel span per LLM call (no-op when OTEL not enabled)
        _otel_tracer = None
        try:
            import os as _os
            if _os.getenv("OTEL_ENABLED", "false").lower() == "true":
                from opentelemetry import trace as _trace
                _otel_tracer = _trace.get_tracer("llm.manager")
        except Exception:
            pass

        async def _call_model(m: str) -> str:
            async with asyncio.timeout(timeout):
                if m in ("claude", "claude-haiku"):
                    if "claude" not in self.clients:
                        raise ValueError("Anthropic API key not configured")
                    variant = "haiku" if m == "claude-haiku" else "sonnet"
                    return await self.clients["claude"].call(
                        messages, system_prompt, max_tokens, temperature, stream, variant,
                        stream_callback=stream_callback,
                    )
                elif m == "gemini":
                    if "gemini" not in self.clients:
                        raise ValueError("Google API key not configured")
                    return await self.clients["gemini"].call(
                        messages, system_prompt, max_tokens, temperature, stream
                    )
                elif m.startswith("ollama/"):
                    ollama_model = m.split("/", 1)[1]
                    return await self.clients["ollama"].call(
                        ollama_model, messages, system_prompt, max_tokens, temperature, stream
                    )
                else:
                    raise ValueError(f"Unknown model: {m}")

        # #33 — Per-model cost cap (pre-flight, best-effort)
        _max_request_cost = float(os.getenv("MAX_REQUEST_COST_USD", "0"))
        if _max_request_cost > 0 and "claude" in model:
            _est_cost = self.estimate_tokens(messages, system_prompt) / 1_000_000 * 15.0
            if _est_cost > _max_request_cost:
                raise ValueError(
                    f"Estimated request cost ${_est_cost:.4f} exceeds MAX_REQUEST_COST_USD=${_max_request_cost:.4f}"
                )

        # 3-level fallback: try requested model, then fallback chain
        fallback_chain = [model] + [m for m in LLM_FALLBACK_CHAIN if m != model]
        last_exc: Exception = ValueError(f"No models available for fallback")
        result: str = ""

        for attempt_model in fallback_chain:
            # L16 — per-model RPM throttle: delay if approaching the model's rate limit
            if attempt_model in _model_rpm_limits:
                _rpm = _model_rpm_limits[attempt_model]
                _win = _model_req_windows.setdefault(attempt_model, _deque())
                _now = time.time()
                while _win and _win[0] < _now - 60:
                    _win.popleft()
                if len(_win) >= _rpm:
                    _wait = 60 - (_now - _win[0]) + 0.1
                    _mgr_logger.debug("Model %s RPM limit %d reached; waiting %.1fs", attempt_model, _rpm, _wait)
                    await asyncio.sleep(max(0, _wait))
                _win.append(time.time())

            # #30 — skip if estimated tokens exceed this model's context window
            try:
                _limit = CONTEXT_LIMITS.get(attempt_model, 32_000)
                if self.estimate_tokens(messages, system_prompt) + max_tokens > _limit:
                    _mgr_logger.debug("Skipping %s — token estimate exceeds context limit %d", attempt_model, _limit)
                    continue
            except Exception:
                pass
            try:
                # B14 — Wrap each LLM call in an OTel span when tracing is enabled
                if _otel_tracer:
                    with _otel_tracer.start_as_current_span(f"llm.call.{attempt_model}") as span:
                        span.set_attribute("llm.model", attempt_model)
                        span.set_attribute("llm.messages", len(messages))
                        result = await _call_model(attempt_model)
                        span.set_attribute("llm.response_len", len(result))
                else:
                    result = await _call_model(attempt_model)
                if attempt_model != model:
                    _mgr_logger.warning("Fell back from %s → %s", model, attempt_model)
                self.record_cb_success(attempt_model)
                break
            except (ValueError, asyncio.TimeoutError, TimeoutError) as exc:
                last_exc = exc
                self.mark_model_unhealthy(attempt_model)
                _mgr_logger.warning("Model %s failed (%s), trying next in chain", attempt_model, exc)
                continue
            except Exception as exc:
                last_exc = exc
                self.mark_model_unhealthy(attempt_model)
                _mgr_logger.exception("Model %s error, trying next in chain", attempt_model)
                continue
        else:
            raise last_exc

        # Structured LLM call log (#18)
        duration_ms = int((time.perf_counter() - t_start) * 1000)
        _mgr_logger.info(
            "llm.call model=%s duration_ms=%d tokens_est=%d",
            model, duration_ms, len(result.split()) * 4 // 3,
        )

        # Store in cache for future identical requests — L23: module-level import
        if not stream and not stream_callback:
            try:
                if _cache_put is not None:
                    await _cache_put(model, messages, result, system_prompt)
            except Exception:
                pass

        # L17 — fire-and-forget usage webhook if configured
        if _USAGE_WEBHOOK_URL:
            try:
                _cost_stats = self.get_cost_stats()
                async def _post_usage():
                    try:
                        async with __import__("httpx").AsyncClient(timeout=5) as _hc:
                            await _hc.post(_USAGE_WEBHOOK_URL, json={
                                "model": model,
                                "input_tokens": _cost_stats.get("input_tokens", 0),
                                "output_tokens": _cost_stats.get("output_tokens", 0),
                                "cost_usd": _cost_stats.get("total_cost_usd", 0),
                            })
                    except Exception:
                        pass
                asyncio.create_task(_post_usage())
            except Exception:
                pass

        return result

    def get_cost_stats(self) -> dict:
        """Return cost statistics for Claude."""
        if "claude" in self.clients:
            return self.clients["claude"].cost_tracker.summary()
        return {}

    def available_models(self) -> list[str]:
        """Return list of available models (Ollama models are discovered at startup)."""
        models = []
        if "claude" in self.clients:
            models.extend(["claude", "claude-haiku"])
        if "gemini" in self.clients:
            models.extend(["gemini"])
        # Use discovered Ollama models; fall back to defaults if not yet populated
        ollama_models = getattr(self.clients.get("ollama"), "_discovered_models", None)
        if ollama_models:
            models.extend([f"ollama/{m}" for m in ollama_models])
        else:
            models.extend(["ollama/llama3", "ollama/mistral", "ollama/phi3"])
        return models

    def is_model_healthy(self, model: str) -> bool:
        """Return True if the circuit is CLOSED or HALF_OPEN for this model."""
        now = time.time()
        # Legacy health-cooldown check
        if model in self._unhealthy and now - self._unhealthy[model] < self._HEALTH_COOLDOWN:
            pass  # may still be overridden by CB logic below

        state = self._cb_state.get(model, _CBState.CLOSED)
        if state == _CBState.CLOSED:
            return True
        if state == _CBState.OPEN:
            elapsed = now - self._cb_open_at.get(model, now)
            if elapsed >= _CB_RESET_TIMEOUT:
                self._cb_state[model] = _CBState.HALF_OPEN
                _cb_logger.info("Circuit HALF_OPEN for %s — testing one call", model)
                return True  # allow single probe
            return False
        # HALF_OPEN: allow the one probe call
        return True

    def record_cb_success(self, model: str) -> None:
        """Reset circuit after a successful call — transitions to CLOSED."""
        prev = self._cb_state.get(model, _CBState.CLOSED)
        self._cb_failures.pop(model, None)
        self._cb_open_at.pop(model, None)
        self._cb_state.pop(model, None)
        self._unhealthy.pop(model, None)
        if prev != _CBState.CLOSED:
            _cb_logger.info("Circuit CLOSED for %s (recovered)", model)
            self._persist_cb_state()  # L22 — update persisted state on recovery

    def mark_model_unhealthy(self, model: str) -> None:
        """Record a failure; open the circuit when threshold is exceeded."""
        self._unhealthy[model] = time.time()
        self._cb_failures[model] = self._cb_failures.get(model, 0) + 1
        failures = self._cb_failures[model]
        if failures >= _CB_FAILURE_THRESHOLD:
            self._cb_state[model] = _CBState.OPEN
            self._cb_open_at[model] = time.time()
            _cb_logger.warning(
                "Circuit OPEN for %s after %d consecutive failures", model, failures
            )
            self._persist_cb_state()  # L22 — persist on state transition

    # L22 — persist/load CB state so a restart doesn't immediately retry broken models
    _CB_STATE_FILE = os.getenv("CB_STATE_FILE", "/tmp/llm_cb_state.json")

    def _persist_cb_state(self) -> None:
        """L22 — Write circuit-breaker state to a JSON file (survives restarts)."""
        import json as _json
        try:
            state = {
                m: {"failures": self._cb_failures.get(m, 0), "open_at": self._cb_open_at.get(m, 0)}
                for m, s in self._cb_state.items() if s == _CBState.OPEN
            }
            with open(self._CB_STATE_FILE, "w") as fh:
                _json.dump(state, fh)
        except Exception as exc:
            _cb_logger.debug("Could not persist CB state: %s", exc)

    def load_cb_state(self) -> None:
        """L22/#32 — Load persisted CB state; skip if file is older than CB_RESET_TIMEOUT (stale)."""
        import json as _json
        import os as _os
        try:
            f_path = self._CB_STATE_FILE
            # #32 — TTL: if the file is older than the reset window, treat it as expired
            try:
                mtime = _os.path.getmtime(f_path)
                if time.time() - mtime > _CB_RESET_TIMEOUT:
                    _cb_logger.debug("CB state file is stale (age > %ds) — ignoring", _CB_RESET_TIMEOUT)
                    _os.remove(f_path)
                    return
            except FileNotFoundError:
                return
            with open(f_path) as fh:
                state = _json.load(fh)
            now = time.time()
            for model, info in state.items():
                open_at = info.get("open_at", 0)
                if now - open_at < _CB_RESET_TIMEOUT:
                    self._cb_state[model] = _CBState.OPEN
                    self._cb_open_at[model] = open_at
                    self._cb_failures[model] = info.get("failures", _CB_FAILURE_THRESHOLD)
                    _cb_logger.info("Restored OPEN circuit for %s from persisted state", model)
        except Exception as exc:
            _cb_logger.debug("Could not load CB state: %s", exc)

    def get_health_status(self) -> dict:
        """Return health status for all models."""
        now = time.time()
        status = {}
        for m in self.available_models():
            if m in self._unhealthy and now - self._unhealthy[m] < self._HEALTH_COOLDOWN:
                status[m] = "unhealthy"
            else:
                status[m] = "healthy"
        return status

    async def refresh_ollama_models(self) -> list[str]:
        """Discover which Ollama models are actually installed and cache the list."""
        if "ollama" not in self.clients:
            return []
        models = await self.clients["ollama"].list_models()
        self.clients["ollama"]._discovered_models = models
        return [f"ollama/{m}" for m in models]

    @staticmethod
    def estimate_tokens(messages: list, system_prompt: str | None = None) -> int:
        """Rough token estimate: words × 1.3 (good enough to catch runaway prompts)."""
        text = " ".join(m.get("content", "") for m in messages)
        if system_prompt:
            text += " " + system_prompt
        return int(len(text.split()) * 1.3)

    def check_token_budget(self, messages: list, system_prompt: str | None, max_tokens: int, model: str) -> None:
        """Raise ValueError if estimated input tokens would exceed the model's context window."""
        context_limits = {
            "claude": 190_000, "claude-haiku": 190_000,
            "gemini": 1_000_000,
        }
        limit = context_limits.get(model, 32_000)
        estimated = self.estimate_tokens(messages, system_prompt)
        if estimated + max_tokens > limit:
            raise ValueError(
                f"Estimated prompt ({estimated} tokens) + max_tokens ({max_tokens}) "
                f"exceeds context window ({limit}) for model '{model}'."
            )


# ─────────────────────────────────────────
# CLAUDE (Anthropic) — shared HTTP client
# ─────────────────────────────────────────
_anthropic_http_client: Optional[httpx.AsyncClient] = None


def _get_anthropic_client() -> httpx.AsyncClient:
    global _anthropic_http_client
    if _anthropic_http_client is None or _anthropic_http_client.is_closed:
        _anthropic_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _anthropic_http_client


class AnthropicClient:
    BASE_URL = "https://api.anthropic.com/v1/messages"
    MODELS = {
        "sonnet": "claude-sonnet-4-6",
        "haiku": "claude-haiku-4-5-20251001",
    }

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cost_tracker = CostTracker()

    async def call(
        self,
        messages,
        system_prompt,
        max_tokens,
        temperature,
        stream,
        model_variant: str = "sonnet",
        stream_callback=None,
    ) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "content-type": "application/json",
        }
        payload = {
            "model": self.MODELS.get(model_variant, self.MODELS["sonnet"]),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        # Prompt caching — system prompt is static, cache saves up to 90% of tokens
        if system_prompt:
            payload["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        if stream:
            client = _get_anthropic_client()
            return await self._stream(client, headers, payload, stream_callback=stream_callback)

        resp = await self._post_with_retry(headers, payload)
        data = resp.json()
        # L21 — prefer model ID from response body; fall back to caller-supplied variant
        _resp_model = data.get("model", "")
        if _resp_model:
            _detected_variant = "haiku" if "haiku" in _resp_model.lower() else "sonnet"
        else:
            _detected_variant = model_variant  # response omitted model — trust the caller
        self.cost_tracker.record(_detected_variant, data.get("usage", {}))

        # #11 — guard against missing 'content' key (e.g. content policy blocks)
        content = data.get("content")
        if not content or not isinstance(content, list):
            stop_reason = data.get("stop_reason", "unknown")
            raise ValueError(f"Anthropic response missing content (stop_reason={stop_reason})")
        return content[0]["text"]

    async def _post_with_retry(self, headers: dict, payload: dict, max_retries: int = 3) -> httpx.Response:
        """POST with exponential backoff on 429 (rate limit) and 529 (overload)."""
        client = _get_anthropic_client()
        last_resp = None
        for attempt in range(max_retries):
            last_resp = await client.post(self.BASE_URL, json=payload, headers=headers)
            if last_resp.status_code in (429, 529) and attempt < max_retries - 1:
                wait = (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(wait)
                continue
            last_resp.raise_for_status()
            return last_resp
        last_resp.raise_for_status()
        return last_resp

    async def _stream(self, client, headers, payload, stream_callback=None) -> str:
        """Stream tokens from the API.

        #10  — uses stream_callback if provided (API/programmatic use).
        #34  — parses the ``message_stop`` event to record cost from usage block.
        """
        payload["stream"] = True
        full_text = ""
        _model_variant = "haiku" if "haiku" in payload.get("model", "").lower() else "sonnet"
        async with client.stream("POST", self.BASE_URL, json=payload, headers=headers) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    import json as _json
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        data = _json.loads(chunk)
                        evt_type = data.get("type", "")
                        if evt_type == "content_block_delta":
                            text = data["delta"].get("text", "")
                            full_text += text
                            if stream_callback is not None:
                                stream_callback(text)
                            else:
                                sys.stdout.write(text)
                                sys.stdout.flush()
                        elif evt_type == "message_delta":
                            # #34 — capture usage from the final message_delta event
                            usage = data.get("usage", {})
                            if usage:
                                self.cost_tracker.record(_model_variant, usage)
                    except Exception:
                        pass
        if stream_callback is None:
            sys.stdout.write("\n")
            sys.stdout.flush()
        return full_text


# ─────────────────────────────────────────
# GEMINI (Google) — shared HTTP client (#8)
# ─────────────────────────────────────────
_gemini_http_client: Optional[httpx.AsyncClient] = None


def _get_gemini_client() -> httpx.AsyncClient:
    global _gemini_http_client
    if _gemini_http_client is None or _gemini_http_client.is_closed:
        _gemini_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _gemini_http_client


class GeminiClient:
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _convert_messages(self, messages, system_prompt):
        """Convert OpenAI-style message format to Gemini format."""
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"[System]: {system_prompt}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood, I will follow these instructions."}]})
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        return contents

    async def _post_with_retry(self, url: str, payload: dict, max_retries: int = 3) -> dict:
        """POST with exponential backoff on 429/500."""
        import random as _random
        client = _get_gemini_client()
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code in (429, 500, 503) and attempt < max_retries - 1:
                    await asyncio.sleep((2 ** attempt) + _random.uniform(0, 0.5))
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_exc = e
                if attempt < max_retries - 1:
                    await asyncio.sleep((2 ** attempt) + _random.uniform(0, 0.5))
        raise last_exc or RuntimeError("Gemini request failed")

    async def call(
        self,
        messages,
        system_prompt,
        max_tokens,
        temperature,
        stream,
        image_data: bytes | None = None,
        image_mime: str = "image/jpeg",
    ) -> str:
        url = f"{self.BASE_URL}?key={self.api_key}"
        contents = self._convert_messages(messages, system_prompt)
        # Vision: attach image to the last user part if image_data provided
        if image_data:
            import base64
            b64 = base64.b64encode(image_data).decode()
            if contents and contents[-1]["role"] == "user":
                contents[-1]["parts"].append({
                    "inlineData": {"mimeType": image_mime, "data": b64}
                })
            else:
                contents.append({
                    "role": "user",
                    "parts": [{"inlineData": {"mimeType": image_mime, "data": b64}}],
                })
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        data = await self._post_with_retry(url, payload)
        return data["candidates"][0]["content"]["parts"][0]["text"]


# ─────────────────────────────────────────
# OLLAMA (local models) — shared HTTP client (#9)
# ─────────────────────────────────────────
_ollama_http_client: Optional[httpx.AsyncClient] = None


def _get_ollama_client() -> httpx.AsyncClient:
    global _ollama_http_client
    if _ollama_http_client is None or _ollama_http_client.is_closed:
        _ollama_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _ollama_http_client


class OllamaClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _build_prompt(self, messages, system_prompt) -> str:
        """Build prompt string for Ollama."""
        parts = []
        if system_prompt:
            parts.append(f"<|system|>\n{system_prompt}")
        for msg in messages:
            role = "user" if msg["role"] == "user" else "assistant"
            parts.append(f"<|{role}|>\n{msg['content']}")
        parts.append("<|assistant|>")
        return "\n".join(parts)

    async def call(self, model, messages, system_prompt, max_tokens, temperature, stream) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": self._build_prompt(messages, system_prompt),
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        client = _get_ollama_client()
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code in (429, 500, 503) and attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return resp.json()["response"]
            except Exception as e:
                last_exc = e
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise last_exc or RuntimeError("Ollama request failed")

    async def list_models(self) -> list[str]:
        """List available models in Ollama."""
        try:
            client = _get_ollama_client()
            resp = await client.get(f"{self.base_url}/api/tags")
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
