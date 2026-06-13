"""
Unit tests for llm/manager.py (CostTracker, LLMManager, AnthropicClient, GeminiClient).

All external HTTP calls are patched so no real network traffic is generated.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from llm.manager import (
    CostTracker,
    LLMManager,
    AnthropicClient,
    GeminiClient,
    OllamaClient,
)


# ─────────────────────────────────────────
# CostTracker
# ─────────────────────────────────────────

class TestCostTracker:
    def test_record_calculates_correct_cost_for_sonnet(self):
        tracker = CostTracker()
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
        cost = tracker.record("sonnet", usage)
        # sonnet: input $3.0/M, output $15.0/M  →  $18.0 total
        assert abs(cost - 18.0) < 1e-6

    def test_record_calculates_correct_cost_for_haiku(self):
        tracker = CostTracker()
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
        cost = tracker.record("haiku", usage)
        # haiku: input $0.80/M, output $4.0/M  →  $4.80 total
        assert abs(cost - 4.80) < 1e-6

    def test_record_includes_cache_write_tokens(self):
        tracker = CostTracker()
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 1_000_000,
        }
        cost = tracker.record("sonnet", usage)
        # sonnet cache_write: $3.75/M
        assert abs(cost - 3.75) < 1e-6

    def test_record_includes_cache_read_tokens(self):
        tracker = CostTracker()
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 1_000_000,
        }
        cost = tracker.record("sonnet", usage)
        # sonnet cache_read: $0.30/M
        assert abs(cost - 0.30) < 1e-6

    def test_record_accumulates_total_cost_across_calls(self):
        tracker = CostTracker()
        usage = {"input_tokens": 1_000_000, "output_tokens": 0}
        tracker.record("haiku", usage)  # $0.80
        tracker.record("haiku", usage)  # $0.80
        assert abs(tracker.total_cost - 1.60) < 1e-6

    def test_record_increments_call_count(self):
        tracker = CostTracker()
        assert tracker.call_count == 0
        tracker.record("sonnet", {"input_tokens": 0, "output_tokens": 0})
        tracker.record("sonnet", {"input_tokens": 0, "output_tokens": 0})
        assert tracker.call_count == 2

    def test_record_accumulates_token_counts(self):
        tracker = CostTracker()
        tracker.record("sonnet", {"input_tokens": 500, "output_tokens": 300})
        tracker.record("sonnet", {"input_tokens": 200, "output_tokens": 100})
        assert tracker.input_tokens == 700
        assert tracker.output_tokens == 400

    def test_record_uses_sonnet_prices_for_unknown_variant(self):
        tracker = CostTracker()
        usage = {"input_tokens": 1_000_000, "output_tokens": 0}
        cost = tracker.record("unknown_model", usage)
        # Falls back to sonnet: $3.0/M
        assert abs(cost - 3.0) < 1e-6

    def test_summary_returns_all_expected_fields(self):
        tracker = CostTracker()
        tracker.record("sonnet", {"input_tokens": 100, "output_tokens": 50})
        summary = tracker.summary()
        expected_keys = {
            "total_cost_usd",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "call_count",
        }
        assert set(summary.keys()) == expected_keys

    def test_summary_total_cost_is_rounded_to_6_decimals(self):
        tracker = CostTracker()
        tracker.record("sonnet", {"input_tokens": 1, "output_tokens": 1})
        summary = tracker.summary()
        # round() with 6 decimals produces a float; verify it has at most 6 decimal places
        cost_str = str(summary["total_cost_usd"])
        if "." in cost_str:
            decimals = len(cost_str.split(".")[1])
            assert decimals <= 6

    def test_summary_on_fresh_tracker_shows_zero_values(self):
        tracker = CostTracker()
        summary = tracker.summary()
        assert summary["total_cost_usd"] == 0.0
        assert summary["call_count"] == 0
        assert summary["input_tokens"] == 0


# ─────────────────────────────────────────
# LLMManager
# ─────────────────────────────────────────

class TestLLMManager:
    def test_available_models_includes_claude_when_anthropic_key_set(self):
        config = {"anthropic_api_key": "sk-test", "gemini_api_key": "", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        models = mgr.available_models()
        assert "claude" in models
        assert "claude-haiku" in models

    def test_available_models_excludes_claude_when_no_anthropic_key(self):
        config = {"anthropic_api_key": "", "gemini_api_key": "", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        models = mgr.available_models()
        assert "claude" not in models
        assert "claude-haiku" not in models

    def test_available_models_includes_gemini_when_gemini_key_set(self):
        config = {"anthropic_api_key": "", "gemini_api_key": "gkey", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        models = mgr.available_models()
        assert "gemini" in models

    def test_available_models_always_includes_ollama_models(self):
        config = {"anthropic_api_key": "", "gemini_api_key": "", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        models = mgr.available_models()
        assert "ollama/llama3" in models
        assert "ollama/mistral" in models
        assert "ollama/phi3" in models

    @pytest.mark.asyncio
    async def test_call_raises_value_error_for_unknown_model(self):
        config = {"anthropic_api_key": "key", "gemini_api_key": "", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        with pytest.raises(ValueError, match="Unknown model"):
            await mgr.call(model="gpt-99-turbo", messages=[{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_call_raises_value_error_when_claude_key_missing(self):
        config = {"anthropic_api_key": "", "gemini_api_key": "", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        with pytest.raises(ValueError, match="Anthropic API key not configured"):
            await mgr.call(model="claude", messages=[{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_call_routes_claude_to_anthropic_client(self):
        config = {"anthropic_api_key": "sk-key", "gemini_api_key": "", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        mgr.clients["claude"] = MagicMock()
        mgr.clients["claude"].call = AsyncMock(return_value="claude answer")

        result = await mgr.call(model="claude", messages=[{"role": "user", "content": "hi"}])
        mgr.clients["claude"].call.assert_awaited_once()
        assert result == "claude answer"

    @pytest.mark.asyncio
    async def test_call_routes_claude_haiku_to_anthropic_client_with_haiku_variant(self):
        config = {"anthropic_api_key": "sk-key", "gemini_api_key": "", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        mgr.clients["claude"] = MagicMock()
        mgr.clients["claude"].call = AsyncMock(return_value="haiku answer")

        await mgr.call(model="claude-haiku", messages=[{"role": "user", "content": "hi"}])
        call_args = mgr.clients["claude"].call.call_args
        # The last positional argument should be the variant string "haiku"
        assert "haiku" in call_args.args or call_args.kwargs.get("model_variant") == "haiku"

    @pytest.mark.asyncio
    async def test_call_routes_gemini_to_gemini_client(self):
        config = {"anthropic_api_key": "", "gemini_api_key": "gkey", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        mgr.clients["gemini"] = MagicMock()
        mgr.clients["gemini"].call = AsyncMock(return_value="gemini answer")

        result = await mgr.call(model="gemini", messages=[{"role": "user", "content": "hi"}])
        mgr.clients["gemini"].call.assert_awaited_once()
        assert result == "gemini answer"

    @pytest.mark.asyncio
    async def test_call_routes_ollama_model_to_ollama_client(self):
        config = {"anthropic_api_key": "", "gemini_api_key": "", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        mgr.clients["ollama"] = MagicMock()
        mgr.clients["ollama"].call = AsyncMock(return_value="ollama answer")

        result = await mgr.call(model="ollama/llama3", messages=[{"role": "user", "content": "hi"}])
        mgr.clients["ollama"].call.assert_awaited_once()
        assert result == "ollama answer"

    def test_get_cost_stats_returns_empty_dict_when_no_claude_client(self):
        config = {"anthropic_api_key": "", "gemini_api_key": "", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        stats = mgr.get_cost_stats()
        assert stats == {}

    def test_get_cost_stats_returns_summary_when_claude_client_exists(self):
        config = {"anthropic_api_key": "key", "gemini_api_key": "", "ollama_url": "http://localhost:11434"}
        mgr = LLMManager(config)
        stats = mgr.get_cost_stats()
        assert "total_cost_usd" in stats
        assert "call_count" in stats


# ─────────────────────────────────────────
# AnthropicClient
# ─────────────────────────────────────────

class TestAnthropicClient:
    def test_init_creates_cost_tracker(self):
        client = AnthropicClient("sk-test")
        assert isinstance(client.cost_tracker, CostTracker)

    @pytest.mark.asyncio
    async def test_call_builds_payload_with_system_prompt_caching(self):
        """When system_prompt is provided, the payload must include a system block
        with cache_control=ephemeral."""
        client = AnthropicClient("sk-test")

        fake_response = MagicMock()
        fake_response.json = MagicMock(return_value={
            "content": [{"text": "response text"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })
        fake_response.raise_for_status = MagicMock()

        captured_payload = {}

        async def fake_post(self_inner, url, json, headers):
            captured_payload.update(json)
            return fake_response

        with patch.object(client, "_post_with_retry", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = fake_response
            await client.call(
                messages=[{"role": "user", "content": "hello"}],
                system_prompt="You are helpful.",
                max_tokens=100,
                temperature=0.7,
                stream=False,
                model_variant="sonnet",
            )

        call_args = mock_post.call_args
        payload = call_args.kwargs.get("payload") or call_args.args[1]
        assert "system" in payload
        system_block = payload["system"]
        assert isinstance(system_block, list)
        assert system_block[0]["type"] == "text"
        assert system_block[0]["cache_control"]["type"] == "ephemeral"
        assert "You are helpful." in system_block[0]["text"]

    @pytest.mark.asyncio
    async def test_call_without_system_prompt_omits_system_field(self):
        client = AnthropicClient("sk-test")

        fake_response = MagicMock()
        fake_response.json = MagicMock(return_value={
            "content": [{"text": "answer"}],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        })

        with patch.object(client, "_post_with_retry", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = fake_response
            await client.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt=None,
                max_tokens=100,
                temperature=0.5,
                stream=False,
                model_variant="haiku",
            )

        payload = mock_post.call_args.args[1]
        assert "system" not in payload

    @pytest.mark.asyncio
    async def test_call_uses_correct_model_for_sonnet_variant(self):
        client = AnthropicClient("sk-test")
        fake_response = MagicMock()
        fake_response.json = MagicMock(return_value={
            "content": [{"text": "ok"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

        with patch.object(client, "_post_with_retry", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = fake_response
            await client.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt=None,
                max_tokens=100,
                temperature=0.5,
                stream=False,
                model_variant="sonnet",
            )

        payload = mock_post.call_args.args[1]
        assert "sonnet" in payload["model"].lower()

    @pytest.mark.asyncio
    async def test_call_records_cost_from_usage(self):
        client = AnthropicClient("sk-test")
        fake_response = MagicMock()
        fake_response.json = MagicMock(return_value={
            "content": [{"text": "answer"}],
            "usage": {"input_tokens": 1_000_000, "output_tokens": 0},
        })

        with patch.object(client, "_post_with_retry", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = fake_response
            await client.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt=None,
                max_tokens=100,
                temperature=0.5,
                stream=False,
                model_variant="haiku",
            )

        # haiku input: $0.80/M → 1M tokens = $0.80
        assert abs(client.cost_tracker.total_cost - 0.80) < 1e-6

    @pytest.mark.asyncio
    async def test_call_returns_text_from_content_block(self):
        client = AnthropicClient("sk-test")
        fake_response = MagicMock()
        fake_response.json = MagicMock(return_value={
            "content": [{"text": "The final answer"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })

        with patch.object(client, "_post_with_retry", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = fake_response
            result = await client.call(
                messages=[{"role": "user", "content": "question"}],
                system_prompt=None,
                max_tokens=100,
                temperature=0.5,
                stream=False,
                model_variant="sonnet",
            )

        assert result == "The final answer"


# ─────────────────────────────────────────
# GeminiClient
# ─────────────────────────────────────────

class TestGeminiClient:
    def test_convert_messages_maps_user_role_correctly(self):
        client = GeminiClient("gkey")
        messages = [{"role": "user", "content": "Hello Gemini"}]
        contents = client._convert_messages(messages, system_prompt=None)
        user_msg = next(c for c in contents if c["role"] == "user")
        assert user_msg["parts"][0]["text"] == "Hello Gemini"

    def test_convert_messages_maps_assistant_role_to_model(self):
        client = GeminiClient("gkey")
        messages = [{"role": "assistant", "content": "I can help"}]
        contents = client._convert_messages(messages, system_prompt=None)
        model_msg = next(c for c in contents if c["role"] == "model")
        assert model_msg["parts"][0]["text"] == "I can help"

    def test_convert_messages_prepends_system_prompt(self):
        client = GeminiClient("gkey")
        messages = [{"role": "user", "content": "question"}]
        contents = client._convert_messages(messages, system_prompt="Be helpful.")
        # First two items should be the system prompt pair
        assert contents[0]["role"] == "user"
        assert "[System]" in contents[0]["parts"][0]["text"]
        assert "Be helpful." in contents[0]["parts"][0]["text"]
        assert contents[1]["role"] == "model"  # acknowledgement

    def test_convert_messages_without_system_prompt_starts_directly(self):
        client = GeminiClient("gkey")
        messages = [{"role": "user", "content": "hi"}]
        contents = client._convert_messages(messages, system_prompt=None)
        assert len(contents) == 1
        assert contents[0]["role"] == "user"

    def test_convert_messages_preserves_message_order(self):
        client = GeminiClient("gkey")
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second"},
        ]
        contents = client._convert_messages(messages, system_prompt=None)
        assert len(contents) == 3
        assert contents[0]["parts"][0]["text"] == "first"
        assert contents[1]["parts"][0]["text"] == "response"
        assert contents[2]["parts"][0]["text"] == "second"

    @pytest.mark.asyncio
    async def test_call_posts_to_correct_url_with_api_key(self):
        client = GeminiClient("my-gkey")

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(return_value={
            "candidates": [{"content": {"parts": [{"text": "Gemini says hi"}]}}]
        })

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=fake_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("llm.manager.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.call(
                messages=[{"role": "user", "content": "hello"}],
                system_prompt=None,
                max_tokens=100,
                temperature=0.5,
                stream=False,
            )

        assert result == "Gemini says hi"
        post_call = mock_http_client.post.call_args
        url = post_call.args[0]
        assert "my-gkey" in url
