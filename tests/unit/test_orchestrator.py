"""
Unit tests for core/orchestrator.py (AgentOrchestrator).

All external dependencies (LLM, router, tools, DB) are mocked so the tests
run entirely in-process with no real I/O.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from core.router import RouterDecision


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def _make_decision(**overrides) -> RouterDecision:
    defaults = dict(
        model="claude-haiku",
        agent="general_agent",
        tools=[],
        reasoning="test decision",
        task_type="general",
        complexity="low",
        needs_internet=False,
    )
    defaults.update(overrides)
    return RouterDecision(**defaults)


def _make_orchestrator(config=None):
    """Create an AgentOrchestrator with all external dependencies mocked."""
    if config is None:
        config = {
            "anthropic_api_key": "test-key",
            "gemini_api_key": "",
            "ollama_url": "http://localhost:11434",
            "mongo_url": "mongodb://localhost:27017",
        }

    import core.orchestrator  # ensure module is in sys.modules before patching
    with patch("core.orchestrator.LLMManager") as MockLLM, \
         patch("core.orchestrator.ToolsManager") as MockTools, \
         patch("core.orchestrator.RouterAgent") as MockRouter:

        mock_llm = MagicMock()
        mock_llm.call = AsyncMock(return_value="agent response")
        mock_llm.get_cost_stats = MagicMock(return_value={"total_cost_usd": 0.001, "call_count": 1})
        mock_llm.available_models = MagicMock(return_value=["claude", "claude-haiku"])
        MockLLM.return_value = mock_llm

        mock_tools = MagicMock()
        mock_tool = MagicMock()
        mock_tool.run = AsyncMock(return_value="tool result")
        mock_tools.get = MagicMock(return_value=mock_tool)
        mock_tools.list_tools = MagicMock(return_value=["web_search"])
        MockTools.return_value = mock_tools

        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=_make_decision())
        MockRouter.return_value = mock_router

        from core.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(config)
        return orch, mock_llm, mock_tools, mock_router


# ─────────────────────────────────────────
# Initialization
# ─────────────────────────────────────────

class TestAgentOrchestratorInit:
    def test_orchestrator_initializes_with_empty_conversation_history(self):
        orch, *_ = _make_orchestrator()
        assert orch.conversation_history == []

    def test_orchestrator_initializes_with_no_last_decision(self):
        orch, *_ = _make_orchestrator()
        assert orch.last_decision is None

    def test_orchestrator_has_llm_attribute(self):
        orch, mock_llm, *_ = _make_orchestrator()
        assert orch.llm is mock_llm

    def test_orchestrator_has_tools_attribute(self):
        orch, _, mock_tools, _ = _make_orchestrator()
        assert orch.tools is mock_tools

    def test_orchestrator_has_router_attribute(self):
        orch, _, _, mock_router = _make_orchestrator()
        assert orch.router is mock_router


# ─────────────────────────────────────────
# process()
# ─────────────────────────────────────────

class TestProcess:
    @pytest.mark.asyncio
    async def test_process_calls_router_route(self):
        orch, _, _, mock_router = _make_orchestrator()
        with patch("core.orchestrator.get_agent") as mock_get_agent, \
             patch("core.orchestrator.append_message", new_callable=AsyncMock), \
             patch("core.orchestrator.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="agent answer")
            mock_get_agent.return_value = mock_agent

            await orch.process("hello world", stream=False, show_routing=False)

        mock_router.route.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_calls_agent_run_after_routing(self):
        orch, *_ = _make_orchestrator()
        with patch("core.orchestrator.get_agent") as mock_get_agent, \
             patch("core.orchestrator.append_message", new_callable=AsyncMock), \
             patch("core.orchestrator.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="the final answer")
            mock_get_agent.return_value = mock_agent

            result = await orch.process("do something", stream=False, show_routing=False)

        mock_agent.run.assert_awaited_once()
        assert result == "the final answer"

    @pytest.mark.asyncio
    async def test_process_emits_routing_event_before_agent_start_event(self):
        orch, *_ = _make_orchestrator()
        emitted_types = []

        async def capture_emit(event):
            emitted_types.append(event.get("type"))

        with patch("core.orchestrator.get_agent") as mock_get_agent, \
             patch("core.orchestrator.append_message", new_callable=AsyncMock), \
             patch("core.orchestrator.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock(side_effect=capture_emit)
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="done")
            mock_get_agent.return_value = mock_agent

            await orch.process("test task", stream=False, show_routing=False)

        assert "routing" in emitted_types
        assert "agent_start" in emitted_types
        routing_idx = emitted_types.index("routing")
        agent_start_idx = emitted_types.index("agent_start")
        assert routing_idx < agent_start_idx

    @pytest.mark.asyncio
    async def test_process_emits_agent_done_event(self):
        orch, *_ = _make_orchestrator()
        emitted_types = []

        async def capture_emit(event):
            emitted_types.append(event.get("type"))

        with patch("core.orchestrator.get_agent") as mock_get_agent, \
             patch("core.orchestrator.append_message", new_callable=AsyncMock), \
             patch("core.orchestrator.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock(side_effect=capture_emit)
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="done")
            mock_get_agent.return_value = mock_agent

            await orch.process("test", stream=False, show_routing=False)

        assert "agent_done" in emitted_types

    @pytest.mark.asyncio
    async def test_process_saves_user_message_to_conversation_history(self):
        orch, *_ = _make_orchestrator()
        with patch("core.orchestrator.get_agent") as mock_get_agent, \
             patch("core.orchestrator.append_message", new_callable=AsyncMock), \
             patch("core.orchestrator.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="reply")
            mock_get_agent.return_value = mock_agent

            await orch.process("user input text", stream=False, show_routing=False)

        user_msgs = [m for m in orch.conversation_history if m["role"] == "user"]
        assert any("user input text" in m["content"] for m in user_msgs)

    @pytest.mark.asyncio
    async def test_process_saves_assistant_response_to_conversation_history(self):
        orch, *_ = _make_orchestrator()
        with patch("core.orchestrator.get_agent") as mock_get_agent, \
             patch("core.orchestrator.append_message", new_callable=AsyncMock), \
             patch("core.orchestrator.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="assistant reply here")
            mock_get_agent.return_value = mock_agent

            await orch.process("hi", stream=False, show_routing=False)

        assistant_msgs = [m for m in orch.conversation_history if m["role"] == "assistant"]
        assert any("assistant reply here" in m["content"] for m in assistant_msgs)

    @pytest.mark.asyncio
    async def test_process_truncates_history_when_over_20_messages(self):
        orch, *_ = _make_orchestrator()
        # Pre-fill history with 20 messages
        orch.conversation_history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(20)
        ]
        with patch("core.orchestrator.get_agent") as mock_get_agent, \
             patch("core.orchestrator.append_message", new_callable=AsyncMock), \
             patch("core.orchestrator.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="new reply")
            mock_get_agent.return_value = mock_agent

            await orch.process("trigger truncation", stream=False, show_routing=False)

        # After adding 2 more items (user + assistant), truncation kicks in
        assert len(orch.conversation_history) <= 20

    @pytest.mark.asyncio
    async def test_process_sets_last_decision(self):
        orch, _, _, mock_router = _make_orchestrator()
        expected_decision = _make_decision(agent="code_agent", model="claude")
        mock_router.route = AsyncMock(return_value=expected_decision)

        with patch("core.orchestrator.get_agent") as mock_get_agent, \
             patch("core.orchestrator.append_message", new_callable=AsyncMock), \
             patch("core.orchestrator.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="done")
            mock_get_agent.return_value = mock_agent

            await orch.process("write some code", stream=False, show_routing=False)

        assert orch.last_decision is expected_decision

    @pytest.mark.asyncio
    async def test_process_uses_pre_computed_decision_when_provided(self):
        orch, _, _, mock_router = _make_orchestrator()
        pre_decision = _make_decision(agent="file_agent", model="claude")

        with patch("core.orchestrator.get_agent") as mock_get_agent, \
             patch("core.orchestrator.append_message", new_callable=AsyncMock), \
             patch("core.orchestrator.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="file content")
            mock_get_agent.return_value = mock_agent

            await orch.process("read a file", decision=pre_decision, stream=False, show_routing=False)

        # Router should NOT have been called when a decision was passed in
        mock_router.route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_process_does_not_crash_when_append_message_raises(self):
        """MongoDB failures must be swallowed — they should not abort the response."""
        orch, *_ = _make_orchestrator()
        with patch("core.orchestrator.get_agent") as mock_get_agent, \
             patch("core.orchestrator.append_message", new_callable=AsyncMock) as mock_append, \
             patch("core.orchestrator.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value="ok")
            mock_get_agent.return_value = mock_agent
            mock_append.side_effect = Exception("MongoDB down")

            result = await orch.process("test", stream=False, show_routing=False)

        assert result == "ok"

    @pytest.mark.asyncio
    async def test_process_truncates_long_response_in_history(self):
        orch, *_ = _make_orchestrator()
        long_response = "x" * 5000  # > MAX_RESPONSE_IN_HISTORY (2000)

        with patch("core.orchestrator.get_agent") as mock_get_agent, \
             patch("core.orchestrator.append_message", new_callable=AsyncMock), \
             patch("core.orchestrator.event_bus") as mock_bus:
            mock_bus.emit = AsyncMock()
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value=long_response)
            mock_get_agent.return_value = mock_agent

            result = await orch.process("give me a long answer", stream=False, show_routing=False)

        # Full response is returned to caller
        assert result == long_response
        # But in history, it should be truncated
        assistant_entry = next(
            m for m in orch.conversation_history if m["role"] == "assistant"
        )
        assert len(assistant_entry["content"]) < len(long_response)
        assert "truncated" in assistant_entry["content"]


# ─────────────────────────────────────────
# get_stats()
# ─────────────────────────────────────────

class TestGetStats:
    def test_get_stats_returns_messages_in_history_key(self):
        orch, *_ = _make_orchestrator()
        stats = orch.get_stats()
        assert "messages_in_history" in stats

    def test_get_stats_returns_last_model_key(self):
        orch, *_ = _make_orchestrator()
        stats = orch.get_stats()
        assert "last_model" in stats

    def test_get_stats_returns_last_agent_key(self):
        orch, *_ = _make_orchestrator()
        stats = orch.get_stats()
        assert "last_agent" in stats

    def test_get_stats_messages_in_history_matches_actual_history(self):
        orch, *_ = _make_orchestrator()
        orch.conversation_history = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        stats = orch.get_stats()
        assert stats["messages_in_history"] == 2

    def test_get_stats_includes_cost_data_when_llm_provides_it(self):
        orch, mock_llm, *_ = _make_orchestrator()
        mock_llm.get_cost_stats.return_value = {"total_cost_usd": 0.005, "call_count": 3}
        stats = orch.get_stats()
        assert "costs" in stats
        assert stats["costs"]["call_count"] == 3

    def test_get_stats_last_model_is_none_before_first_process(self):
        orch, *_ = _make_orchestrator()
        stats = orch.get_stats()
        assert stats["last_model"] is None

    def test_get_stats_last_model_set_after_decision(self):
        orch, *_ = _make_orchestrator()
        orch.last_decision = _make_decision(model="gemini")
        stats = orch.get_stats()
        assert stats["last_model"] == "gemini"


# ─────────────────────────────────────────
# clear_history()
# ─────────────────────────────────────────

class TestClearHistory:
    def test_clear_history_empties_conversation_history(self):
        orch, *_ = _make_orchestrator()
        orch.conversation_history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        orch.clear_history()
        assert orch.conversation_history == []

    def test_clear_history_on_empty_history_is_safe(self):
        orch, *_ = _make_orchestrator()
        orch.clear_history()  # should not raise
        assert orch.conversation_history == []

    def test_clear_history_history_remains_empty_after_multiple_calls(self):
        orch, *_ = _make_orchestrator()
        orch.conversation_history = [{"role": "user", "content": "x"}]
        orch.clear_history()
        orch.clear_history()
        assert orch.conversation_history == []
