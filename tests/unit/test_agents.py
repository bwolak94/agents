"""
Unit tests for agents/agents.py (all specialist agent classes and get_agent()).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.agents import (
    BaseAgent,
    CodeAgent,
    ResearchAgent,
    LearnAgent,
    FileAgent,
    GeneralAgent,
    get_agent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(cls):
    """Instantiate an agent with mock dependencies."""
    llm = MagicMock()
    llm.call = AsyncMock(return_value="LLM answer")
    tools = MagicMock()
    tools.get = MagicMock(return_value=None)
    return cls(llm, tools), llm, tools


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

class TestSystemPrompts:
    def test_code_agent_prompt_contains_software_engineer(self):
        agent, _, _ = _make_agent(CodeAgent)
        assert "software engineer" in agent.system_prompt.lower()

    def test_research_agent_prompt_contains_research(self):
        agent, _, _ = _make_agent(ResearchAgent)
        assert "research" in agent.system_prompt.lower()

    def test_learn_agent_prompt_contains_educator(self):
        agent, _, _ = _make_agent(LearnAgent)
        assert "educator" in agent.system_prompt.lower()

    def test_file_agent_prompt_contains_document_analyst(self):
        agent, _, _ = _make_agent(FileAgent)
        assert "document analyst" in agent.system_prompt.lower()

    def test_general_agent_prompt_contains_versatile(self):
        agent, _, _ = _make_agent(GeneralAgent)
        assert "versatile" in agent.system_prompt.lower()

    def test_each_agent_has_non_empty_system_prompt(self):
        for cls in (CodeAgent, ResearchAgent, LearnAgent, FileAgent, GeneralAgent):
            agent, _, _ = _make_agent(cls)
            assert len(agent.system_prompt.strip()) > 50


# ---------------------------------------------------------------------------
# get_agent() registry
# ---------------------------------------------------------------------------

class TestGetAgent:
    @pytest.mark.parametrize("name,expected_cls", [
        ("code_agent", CodeAgent),
        ("research_agent", ResearchAgent),
        ("learn_agent", LearnAgent),
        ("file_agent", FileAgent),
        ("general_agent", GeneralAgent),
    ])
    def test_get_agent_returns_correct_class(self, name, expected_cls):
        llm = MagicMock()
        tools = MagicMock()
        agent = get_agent(name, llm, tools)
        assert isinstance(agent, expected_cls)

    def test_get_agent_falls_back_to_general_agent_for_unknown_name(self):
        llm = MagicMock()
        tools = MagicMock()
        agent = get_agent("nonexistent_agent_xyz", llm, tools)
        assert isinstance(agent, GeneralAgent)

    def test_get_agent_falls_back_to_general_agent_for_empty_string(self):
        llm = MagicMock()
        tools = MagicMock()
        agent = get_agent("", llm, tools)
        assert isinstance(agent, GeneralAgent)

    def test_get_agent_passes_llm_and_tools_to_instance(self):
        llm = MagicMock()
        tools = MagicMock()
        agent = get_agent("code_agent", llm, tools)
        assert agent.llm is llm
        assert agent.tools is tools


# ---------------------------------------------------------------------------
# BaseAgent.run()
# ---------------------------------------------------------------------------

class TestBaseAgentRun:
    @pytest.mark.asyncio
    async def test_run_calls_llm_call(self):
        agent, llm, _ = _make_agent(GeneralAgent)
        llm.call = AsyncMock(return_value="Hello from LLM")
        result = await agent.run(
            message="hello",
            model="claude",
            tool_names=[],
            conversation_history=[],
        )
        llm.call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_passes_model_to_llm(self):
        agent, llm, _ = _make_agent(GeneralAgent)
        llm.call = AsyncMock(return_value="answer")
        await agent.run(
            message="test",
            model="claude-haiku",
            tool_names=[],
            conversation_history=[],
        )
        call_kwargs = llm.call.call_args.kwargs
        assert call_kwargs.get("model") == "claude-haiku"

    @pytest.mark.asyncio
    async def test_run_passes_system_prompt_to_llm(self):
        agent, llm, _ = _make_agent(CodeAgent)
        llm.call = AsyncMock(return_value="code answer")
        await agent.run(
            message="write a sort algorithm",
            model="claude",
            tool_names=[],
            conversation_history=[],
        )
        call_kwargs = llm.call.call_args.kwargs
        assert "software engineer" in call_kwargs.get("system_prompt", "").lower()

    @pytest.mark.asyncio
    async def test_run_returns_llm_response_string(self):
        agent, llm, _ = _make_agent(GeneralAgent)
        llm.call = AsyncMock(return_value="the expected answer")
        result = await agent.run(
            message="anything",
            model="claude",
            tool_names=[],
            conversation_history=[],
        )
        assert result == "the expected answer"

    @pytest.mark.asyncio
    async def test_run_includes_conversation_history_in_messages(self):
        agent, llm, _ = _make_agent(GeneralAgent)
        llm.call = AsyncMock(return_value="yes")
        history = [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ]
        await agent.run(
            message="follow-up",
            model="claude",
            tool_names=[],
            conversation_history=history,
        )
        call_kwargs = llm.call.call_args.kwargs
        messages = call_kwargs.get("messages", [])
        # History + current message = 3 items
        assert len(messages) == 3
        assert messages[0]["content"] == "previous question"
        assert messages[-1]["content"] == "follow-up"

    @pytest.mark.asyncio
    async def test_run_injects_tool_results_into_message(self):
        """When LLM returns a <tool_call>, agent should execute the tool and inject
        <tool_result> into the next message, then call LLM again for final answer."""
        agent, llm, tools = _make_agent(ResearchAgent)
        mock_tool = MagicMock()
        mock_tool.run = AsyncMock(return_value="Search result text")
        tools.get = MagicMock(return_value=mock_tool)
        # First LLM call returns a tool call; second returns final answer
        llm.call = AsyncMock(side_effect=[
            '<tool_call>{"name": "web_search", "args": "latest news"}</tool_call>',
            "research answer",
        ])

        result = await agent.run(
            message="find news",
            model="claude",
            tool_names=["web_search"],
            conversation_history=[],
        )
        # Second LLM call's messages should include the tool result
        second_call_kwargs = llm.call.call_args_list[1].kwargs
        messages = second_call_kwargs.get("messages", [])
        # Find the tool_result message injected by the ReAct loop
        tool_result_messages = [m for m in messages if "<tool_result>" in m.get("content", "")]
        assert len(tool_result_messages) == 1
        assert "Search result text" in tool_result_messages[0]["content"]
        assert result == "research answer"

    @pytest.mark.asyncio
    async def test_run_with_max_tokens_passed_to_llm(self):
        agent, llm, _ = _make_agent(GeneralAgent)
        llm.call = AsyncMock(return_value="ok")
        await agent.run(
            message="hi",
            model="claude",
            tool_names=[],
            conversation_history=[],
            max_tokens=1024,
        )
        call_kwargs = llm.call.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 1024


# ---------------------------------------------------------------------------
# ReAct loop — tool call parsing and execution
# ---------------------------------------------------------------------------

class TestReActLoop:
    @pytest.mark.asyncio
    async def test_run_without_tool_call_returns_immediately(self):
        """When LLM response has no <tool_call>, agent returns it as final answer."""
        agent, llm, _ = _make_agent(GeneralAgent)
        llm.call = AsyncMock(return_value="plain answer without tool call")
        result = await agent.run("hi", "claude", [], [])
        assert result == "plain answer without tool call"
        assert llm.call.call_count == 1

    @pytest.mark.asyncio
    async def test_unknown_tool_name_results_in_error_message_injected(self):
        """If LLM calls an unknown tool, the ReAct loop injects an error and continues."""
        agent, llm, tools = _make_agent(GeneralAgent)
        tools.get = MagicMock(return_value=None)  # all tools unknown
        llm.call = AsyncMock(side_effect=[
            '<tool_call>{"name": "nonexistent", "args": "query"}</tool_call>',
            "final answer after error",
        ])
        result = await agent.run("hi", "claude", ["nonexistent"], [])
        assert result == "final answer after error"
        # Second call's messages should mention the unknown tool
        second_msgs = llm.call.call_args_list[1].kwargs["messages"]
        error_msgs = [m for m in second_msgs if "Unknown tool" in m.get("content", "")]
        assert len(error_msgs) == 1

    @pytest.mark.asyncio
    async def test_tool_error_is_injected_gracefully(self):
        """If a tool raises an exception, the error is injected as tool_result, not re-raised."""
        agent, llm, tools = _make_agent(GeneralAgent)
        broken_tool = MagicMock()
        broken_tool.run = AsyncMock(side_effect=RuntimeError("network failure"))
        tools.get = MagicMock(return_value=broken_tool)
        llm.call = AsyncMock(side_effect=[
            '<tool_call>{"name": "web_search", "args": "query"}</tool_call>',
            "final answer",
        ])
        result = await agent.run("query", "claude", ["web_search"], [])
        assert result == "final answer"
        second_msgs = llm.call.call_args_list[1].kwargs["messages"]
        error_msgs = [m for m in second_msgs if "Tool error" in m.get("content", "")]
        assert len(error_msgs) == 1

    @pytest.mark.asyncio
    async def test_tool_args_passed_to_tool_run(self):
        """Tool args from the LLM <tool_call> are forwarded to tool.run()."""
        agent, llm, tools = _make_agent(GeneralAgent)
        mock_tool = MagicMock()
        mock_tool.run = AsyncMock(return_value="result")
        tools.get = MagicMock(return_value=mock_tool)
        llm.call = AsyncMock(side_effect=[
            '<tool_call>{"name": "web_search", "args": "search for cats"}</tool_call>',
            "done",
        ])
        await agent.run("query", "claude", ["web_search"], [])
        mock_tool.run.assert_awaited_once_with("search for cats")
