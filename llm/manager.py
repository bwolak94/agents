"""
LLM Manager - unified interface to all models.
Supports: Claude (Anthropic), Gemini (Google), Ollama (local models)
"""
import os
import asyncio
import random
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


class LLMManager:
    def __init__(self, config: dict):
        self.config = config
        self.clients = {}
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
    ) -> str:
        """
        Call any model through a unified interface.

        model: "claude" | "claude-haiku" | "gemini" | "ollama/llama3" | "ollama/mistral" | "ollama/phi3"
        """
        if model in ("claude", "claude-haiku"):
            if "claude" not in self.clients:
                raise ValueError("Brak klucza API Anthropic! Ustaw ANTHROPIC_API_KEY")
            variant = "haiku" if model == "claude-haiku" else "sonnet"
            return await self.clients["claude"].call(messages, system_prompt, max_tokens, temperature, stream, variant)

        elif model == "gemini":
            if "gemini" not in self.clients:
                raise ValueError("Brak klucza API Google! Ustaw GEMINI_API_KEY")
            return await self.clients["gemini"].call(messages, system_prompt, max_tokens, temperature, stream)

        elif model.startswith("ollama/"):
            ollama_model = model.split("/", 1)[1]
            return await self.clients["ollama"].call(ollama_model, messages, system_prompt, max_tokens, temperature, stream)

        else:
            raise ValueError(f"Nieznany model: {model}")

    def get_cost_stats(self) -> dict:
        """Return cost statistics for Claude."""
        if "claude" in self.clients:
            return self.clients["claude"].cost_tracker.summary()
        return {}

    def available_models(self) -> list[str]:
        """Return list of available models."""
        models = []
        if "claude" in self.clients:
            models.extend(["claude", "claude-haiku"])
        if "gemini" in self.clients:
            models.extend(["gemini"])
        models.extend(["ollama/llama3", "ollama/mistral", "ollama/phi3"])
        return models


# ─────────────────────────────────────────
# CLAUDE (Anthropic)
# ─────────────────────────────────────────
class AnthropicClient:
    BASE_URL = "https://api.anthropic.com/v1/messages"
    MODELS = {
        "sonnet": "claude-sonnet-4-6",
        "haiku": "claude-haiku-4-5-20251001",
    }

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cost_tracker = CostTracker()

    async def call(self, messages, system_prompt, max_tokens, temperature, stream, model_variant: str = "sonnet") -> str:
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
        # Prompt caching - system prompt is static, cache saves up to 90% of tokens
        if system_prompt:
            payload["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        if stream:
            async with httpx.AsyncClient(timeout=60.0) as client:
                return await self._stream(client, headers, payload)

        resp = await self._post_with_retry(headers, payload)
        data = resp.json()
        self.cost_tracker.record(model_variant, data.get("usage", {}))
        return data["content"][0]["text"]

    async def _post_with_retry(self, headers: dict, payload: dict, max_retries: int = 3) -> httpx.Response:
        """POST with exponential backoff on 429 (rate limit) and 529 (overload)."""
        last_resp = None
        for attempt in range(max_retries):
            async with httpx.AsyncClient(timeout=60.0) as client:
                last_resp = await client.post(self.BASE_URL, json=payload, headers=headers)
            if last_resp.status_code in (429, 529) and attempt < max_retries - 1:
                wait = (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(wait)
                continue
            last_resp.raise_for_status()
            return last_resp
        last_resp.raise_for_status()
        return last_resp

    async def _stream(self, client, headers, payload):
        payload["stream"] = True
        full_text = ""
        async with client.stream("POST", self.BASE_URL, json=payload, headers=headers) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    import json
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        if data.get("type") == "content_block_delta":
                            text = data["delta"].get("text", "")
                            full_text += text
                            print(text, end="", flush=True)
                    except Exception:
                        pass
        print()  # newline after stream
        return full_text


# ─────────────────────────────────────────
# GEMINI (Google)
# ─────────────────────────────────────────
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

    async def call(self, messages, system_prompt, max_tokens, temperature, stream) -> str:
        url = f"{self.BASE_URL}?key={self.api_key}"
        payload = {
            "contents": self._convert_messages(messages, system_prompt),
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]


# ─────────────────────────────────────────
# OLLAMA (lokalne modele)
# ─────────────────────────────────────────
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
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["response"]

    async def list_models(self) -> list[str]:
        """List available models in Ollama."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
