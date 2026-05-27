"""
Unit tests for core/router.py (RouterAgent).
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.router import RouterAgent, RouterDecision
import core.router as _router_module


@pytest.fixture(autouse=True)
def clear_router_cache():
    """Clear the LRU routing cache before every test to prevent order-dependent
    results (#29 — tests must be fully isolated from each other)."""
    _router_module._ROUTE_CACHE.clear()
    _router_module._ROUTE_CACHE_ORDER.clear()
    _router_module._ROUTE_CACHE_LOCK = None
    yield
    _router_module._ROUTE_CACHE.clear()
    _router_module._ROUTE_CACHE_ORDER.clear()
    _router_module._ROUTE_CACHE_LOCK = None


# ---------------------------------------------------------------------------
# RouterDecision dataclass
# ---------------------------------------------------------------------------

class TestRouterDecision:
    def test_creation_with_all_fields(self):
        d = RouterDecision(
            model="claude",
            agent="code_agent",
            tools=["web_search"],
            reasoning="needs the internet",
            task_type="research",
            complexity="high",
            needs_internet=True,
        )
        assert d.model == "claude"
        assert d.agent == "code_agent"
        assert d.tools == ["web_search"]
        assert d.reasoning == "needs the internet"
        assert d.task_type == "research"
        assert d.complexity == "high"
        assert d.needs_internet is True

    def test_creation_with_empty_tools(self):
        d = RouterDecision(
            model="claude-haiku",
            agent="general_agent",
            tools=[],
            reasoning="simple query",
            task_type="general",
            complexity="low",
            needs_internet=False,
        )
        assert d.tools == []
        assert d.needs_internet is False

    def test_dataclass_equality(self):
        d1 = RouterDecision("claude", "code_agent", [], "r", "coding", "medium", False)
        d2 = RouterDecision("claude", "code_agent", [], "r", "coding", "medium", False)
        assert d1 == d2


# ---------------------------------------------------------------------------
# _heuristic_route
# ---------------------------------------------------------------------------

class TestHeuristicRoute:
    @pytest.fixture
    def router(self):
        llm = MagicMock()
        return RouterAgent(llm)

    # --- search keywords ---
    @pytest.mark.parametrize("msg", [
        "search for python tutorials",
        "find the latest news on AI",
        "look up current events",
        "google this for me",
        "news about AI",
        "latest twitter trends",
    ])
    def test_search_keywords_route_to_research_agent(self, router, msg):
        d = router._heuristic_route(msg)
        assert d.agent == "research_agent"
        assert d.task_type == "research"
        assert d.needs_internet is True
        assert "web_search" in d.tools

    # --- code keywords ---
    @pytest.mark.parametrize("msg", [
        "write a function in Python",
        "debug this error",
        "implement class MyClass",
        "import os and def my_func",
        "fix the bug in the code",
        "refactor this function",
    ])
    def test_code_keywords_route_to_code_agent(self, router, msg):
        d = router._heuristic_route(msg)
        assert d.agent == "code_agent"
        assert d.task_type == "coding"
        assert d.needs_internet is False

    # --- learn keywords ---
    @pytest.mark.parametrize("msg", [
        "explain how TCP/IP works",
        "what is recursion",
        "how does gradient descent work",
        "teach me about networking",
        "give me an example of a design pattern",
        "tutorial on async await",
    ])
    def test_learn_keywords_route_to_learn_agent(self, router, msg):
        d = router._heuristic_route(msg)
        assert d.agent == "learn_agent"
        assert d.task_type == "learning"

    # --- file keywords ---
    @pytest.mark.parametrize("msg", [
        "read this txt file",
        "open this csv file",
        "read this json file",
        "analyse this pdf document",
    ])
    def test_file_keywords_route_to_file_agent(self, router, msg):
        d = router._heuristic_route(msg)
        assert d.agent == "file_agent"
        assert d.task_type == "file"
        assert "file_read" in d.tools

    # --- default fallback ---
    def test_default_routes_to_general_agent(self, router):
        d = router._heuristic_route("hello, how are you?")
        assert d.agent == "general_agent"
        assert d.task_type == "general"
        assert d.model == "claude-haiku"
        assert d.complexity == "low"

    def test_empty_message_routes_to_general_agent(self, router):
        d = router._heuristic_route("")
        assert d.agent == "general_agent"


# ---------------------------------------------------------------------------
# route() — async, calls LLM
# ---------------------------------------------------------------------------

class TestRouteAsync:
    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.call = AsyncMock()
        return llm

    @pytest.fixture
    def router(self, mock_llm):
        return RouterAgent(mock_llm)

    @pytest.mark.asyncio
    async def test_route_returns_router_decision(self, router, mock_llm):
        mock_llm.call.return_value = json.dumps({
            "model": "claude",
            "agent": "code_agent",
            "tools": ["code_exec"],
            "reasoning": "user asked for code",
            "task_type": "coding",
            "complexity": "medium",
            "needs_internet": False,
        })
        decision = await router.route("Write a python function")
        assert isinstance(decision, RouterDecision)
        assert decision.agent == "code_agent"
        assert decision.model == "claude"
        assert decision.task_type == "coding"

    @pytest.mark.asyncio
    async def test_route_calls_llm_with_haiku_model(self, router, mock_llm):
        mock_llm.call.return_value = json.dumps({
            "model": "claude",
            "agent": "general_agent",
            "tools": [],
            "reasoning": "simple",
            "task_type": "general",
            "complexity": "low",
            "needs_internet": False,
        })
        await router.route("hello")
        call_kwargs = mock_llm.call.call_args
        assert call_kwargs.kwargs.get("model") == "claude-haiku" or \
               call_kwargs.args[0] == "claude-haiku" or \
               call_kwargs.kwargs.get("model", call_kwargs.args[0] if call_kwargs.args else None) == "claude-haiku"

    @pytest.mark.asyncio
    async def test_route_falls_back_to_heuristic_on_invalid_json(self, router, mock_llm):
        mock_llm.call.return_value = "Sorry, I cannot provide JSON right now."
        decision = await router.route("napisz funkcję w python def hello")
        # Heuristic should have picked up "python" and "def " keywords → code_agent
        assert decision.agent == "code_agent"

    @pytest.mark.asyncio
    async def test_route_strips_markdown_backticks(self, router, mock_llm):
        raw = json.dumps({
            "model": "gemini",
            "agent": "research_agent",
            "tools": ["web_search"],
            "reasoning": "research task",
            "task_type": "research",
            "complexity": "medium",
            "needs_internet": True,
        })
        mock_llm.call.return_value = f"```json\n{raw}\n```"
        decision = await router.route("Find the latest news about AI")
        assert decision.agent == "research_agent"
        assert decision.model == "gemini"

    @pytest.mark.asyncio
    async def test_route_extracts_json_embedded_in_prose(self, router, mock_llm):
        payload = {
            "model": "claude-haiku",
            "agent": "general_agent",
            "tools": [],
            "reasoning": "simple question",
            "task_type": "general",
            "complexity": "low",
            "needs_internet": False,
        }
        # LLM wraps JSON in surrounding prose text
        mock_llm.call.return_value = (
            f"Sure, here is my analysis: {json.dumps(payload)} "
            "Hope that helps!"
        )
        decision = await router.route("What is 2+2?")
        assert decision.agent == "general_agent"
        assert decision.complexity == "low"

    @pytest.mark.asyncio
    async def test_route_uses_default_values_for_missing_json_keys(self, router, mock_llm):
        # Partial JSON — missing most keys
        mock_llm.call.return_value = '{"model": "claude"}'
        decision = await router.route("something")
        assert decision.model == "claude"
        # Defaults should be applied
        assert decision.agent == "general_agent"
        assert decision.tools == []
        assert decision.task_type == "general"
        assert decision.complexity == "medium"
        assert decision.needs_internet is False

    @pytest.mark.asyncio
    async def test_route_passes_system_prompt_to_llm(self, router, mock_llm):
        mock_llm.call.return_value = json.dumps({
            "model": "claude",
            "agent": "general_agent",
            "tools": [],
            "reasoning": "x",
            "task_type": "general",
            "complexity": "low",
            "needs_internet": False,
        })
        await router.route("hi")
        call_kwargs = mock_llm.call.call_args
        # system_prompt must be passed in kwargs
        system_prompt = call_kwargs.kwargs.get("system_prompt")
        assert system_prompt is not None
        assert "JSON" in system_prompt

    @pytest.mark.asyncio
    async def test_route_with_context_passes_history_in_messages(self, router, mock_llm):
        mock_llm.call.return_value = json.dumps({
            "model": "claude",
            "agent": "general_agent",
            "tools": [],
            "reasoning": "x",
            "task_type": "general",
            "complexity": "low",
            "needs_internet": False,
        })
        await router.route("follow-up question", context=[{"role": "user", "content": "prev"}])
        # The messages passed to LLM should at least contain the new user message
        call_kwargs = mock_llm.call.call_args
        messages = call_kwargs.kwargs.get("messages", [])
        assert any(m["role"] == "user" for m in messages)
