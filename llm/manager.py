"""
LLM Manager - unified interface to all models.
Supports: Claude (Anthropic), Gemini (Google), Ollama (local models)
"""
import os
import asyncio
import random
import sys
import time
from typing import Optional
import httpx


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

        # Check response cache (skip for streaming requests)
        if not stream and not stream_callback:
            try:
                from db.cache import get as cache_get, put as cache_put
                cached = await cache_get(model, messages, system_prompt)
                if cached is not None:
                    return cached
            except Exception:
                cached = None
                cache_get = cache_put = None  # type: ignore

        result: str
        if model in ("claude", "claude-haiku"):
            if "claude" not in self.clients:
                raise ValueError("Anthropic API key not set. Configure ANTHROPIC_API_KEY.")
            variant = "haiku" if model == "claude-haiku" else "sonnet"
            result = await self.clients["claude"].call(
                messages, system_prompt, max_tokens, temperature, stream, variant,
                stream_callback=stream_callback,
            )

        elif model == "gemini":
            if "gemini" not in self.clients:
                raise ValueError("Google API key not set. Configure GEMINI_API_KEY.")
            result = await self.clients["gemini"].call(messages, system_prompt, max_tokens, temperature, stream)

        elif model.startswith("ollama/"):
            ollama_model = model.split("/", 1)[1]
            result = await self.clients["ollama"].call(ollama_model, messages, system_prompt, max_tokens, temperature, stream)

        else:
            raise ValueError(f"Unknown model: {model}")

        # Store in cache for future identical requests
        if not stream and not stream_callback:
            try:
                from db.cache import put as cache_put
                await cache_put(model, messages, result, system_prompt)
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
        self.cost_tracker.record(model_variant, data.get("usage", {}))

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

        #10 — uses stream_callback if provided (API/programmatic use),
        otherwise writes directly to stdout (CLI use).
        """
        payload["stream"] = True
        full_text = ""
        async with client.stream("POST", self.BASE_URL, json=payload, headers=headers) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    import json as _json
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        data = _json.loads(chunk)
                        if data.get("type") == "content_block_delta":
                            text = data["delta"].get("text", "")
                            full_text += text
                            if stream_callback is not None:
                                stream_callback(text)
                            else:
                                sys.stdout.write(text)
                                sys.stdout.flush()
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
