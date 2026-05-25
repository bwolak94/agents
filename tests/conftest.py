"""
Shared pytest fixtures for the agent system test suite.
"""
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock

# Ensure the agents source root is on sys.path so imports resolve without
# installing the package.
_agents_root = str(Path(__file__).parent.parent)
if _agents_root not in sys.path:
    sys.path.insert(0, _agents_root)

# Stub out motor (async MongoDB driver) so tests run without it installed.
_motor_stub = MagicMock()
sys.modules.setdefault("motor", _motor_stub)
sys.modules.setdefault("motor.motor_asyncio", _motor_stub)

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# mock_llm
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_llm():
    """An AsyncMock that stands in for LLMManager.call().

    Returns a plain string by default so agents/router tests can work without
    a real API key.
    """
    llm = MagicMock()
    llm.call = AsyncMock(return_value="Mocked LLM response")
    llm.get_cost_stats = MagicMock(return_value={
        "total_cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "call_count": 0,
    })
    llm.available_models = MagicMock(return_value=["claude", "claude-haiku"])
    return llm


# ---------------------------------------------------------------------------
# mock_tools_manager
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_tools_manager():
    """A MagicMock that stands in for ToolsManager."""
    manager = MagicMock()
    mock_tool = MagicMock()
    mock_tool.run = AsyncMock(return_value="Tool result")
    manager.get = MagicMock(return_value=mock_tool)
    manager.list_tools = MagicMock(return_value=[
        "web_search", "code_exec", "file_read", "file_write", "shell"
    ])
    return manager


# ---------------------------------------------------------------------------
# mock_config
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_config():
    """Minimal configuration dict, no real credentials."""
    return {
        "anthropic_api_key": "test-anthropic-key",
        "gemini_api_key": "",
        "brave_api_key": "",
        "mongo_url": "mongodb://localhost:27017",
        "ollama_url": "http://localhost:11434",
        "stream": False,
        "default_model": "claude",
        "api_host": "0.0.0.0",
        "api_port": 8000,
        "web_port": 3000,
    }


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------
@pytest.fixture
def orchestrator(mock_config):
    """AgentOrchestrator with a mocked LLMManager so no real calls are made."""
    from core.orchestrator import AgentOrchestrator
    from unittest.mock import patch, AsyncMock, MagicMock

    with patch("core.orchestrator.LLMManager") as MockLLM, \
         patch("core.orchestrator.ToolsManager") as MockTools, \
         patch("core.orchestrator.RouterAgent") as MockRouter:

        mock_llm_instance = MagicMock()
        mock_llm_instance.call = AsyncMock(return_value="Orchestrator mock response")
        mock_llm_instance.get_cost_stats = MagicMock(return_value={})
        mock_llm_instance.available_models = MagicMock(return_value=["claude", "claude-haiku"])
        MockLLM.return_value = mock_llm_instance

        mock_tools_instance = MagicMock()
        mock_tool = MagicMock()
        mock_tool.run = AsyncMock(return_value="tool result")
        mock_tools_instance.get = MagicMock(return_value=mock_tool)
        mock_tools_instance.list_tools = MagicMock(return_value=["web_search"])
        MockTools.return_value = mock_tools_instance

        mock_router_instance = MagicMock()
        from core.router import RouterDecision
        mock_router_instance.route = AsyncMock(return_value=RouterDecision(
            model="claude-haiku",
            agent="general_agent",
            tools=[],
            reasoning="test routing",
            task_type="general",
            complexity="low",
            needs_internet=False,
        ))
        MockRouter.return_value = mock_router_instance

        orch = AgentOrchestrator(mock_config)
        yield orch
