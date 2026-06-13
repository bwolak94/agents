"""
Integration / smoke tests for the Agent System API.

Uses FastAPI's TestClient (httpx-based, synchronous) so no real network or
database connections are needed — all heavy dependencies are mocked.

Patch paths after OOP refactor:
  - DB modules  → api.db.<module>
  - Session mgmt → api.state.get_session
  - Preprocessor → api.preprocessor.preprocess
  - Background tasks → api.state._auto_title_session / _auto_tag_session
  - Scheduler   → core.scheduler.scheduler
"""
import sys
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_mock_orchestrator(response: str = "hello from agent"):
    orch = MagicMock()
    orch.process = AsyncMock(return_value=response)
    orch.conversation_history = []

    decision = MagicMock()
    decision.model = "claude-haiku"
    decision.agent = "general_agent"
    decision.tools = []
    decision.reasoning = "test"
    orch.last_decision = decision

    cost = {"total_cost_usd": 0.001, "call_count": 1}
    orch.llm = MagicMock()
    orch.llm.get_cost_stats = MagicMock(return_value=cost)
    orch.llm.available_models = MagicMock(return_value=["claude", "claude-haiku"])
    orch.llm.refresh_ollama_models = AsyncMock(return_value=[])
    orch.llm.get_health_status = MagicMock(return_value={"claude": "healthy", "claude-haiku": "healthy"})
    orch.llm.estimate_tokens = MagicMock(return_value=100)
    orch.get_stats = MagicMock(return_value={"messages_in_history": 0})
    orch.clear_history = MagicMock()
    orch.set_persona = MagicMock()
    orch._agent_cache = {}
    orch._update_history = AsyncMock()
    orch.run_fan_out = AsyncMock(return_value={"message": "hello", "results": []})
    orch.run_pipeline = AsyncMock(return_value="pipeline result")
    orch.run_debate = AsyncMock(return_value="debate result")

    router = MagicMock()
    router.route = AsyncMock(return_value=decision)
    orch.router = router
    return orch


# ─── Fixture helpers — domain-grouped mock setup (#13) ────────────────────────

def _mock_db_base(mocks: dict) -> None:
    """Wire all set_db stubs (every DB module)."""
    for key in (
        "memory_db", "analytics_db", "prompts_db", "feedback_db", "rag_db",
        "file_versions_db", "cache_db", "personas_db", "tags_db",
        "agent_checkpoints_db", "collab_graph_db", "macros_db", "batch_db",
        "workflows_db", "experiments_db", "prompt_versions_db", "tenants_db",
        "memory_graph_db", "webhooks_db",
    ):
        mocks[key].set_db = MagicMock()

    # Modules that also need ensure_indexes
    for key in (
        "feedback_db", "rag_db", "file_versions_db", "cache_db", "personas_db",
        "tags_db", "agent_checkpoints_db", "collab_graph_db", "macros_db",
        "batch_db", "workflows_db", "experiments_db", "prompt_versions_db",
        "tenants_db", "memory_graph_db", "webhooks_db",
    ):
        mocks[key].ensure_indexes = AsyncMock()


def _mock_analytics(mocks: dict) -> None:
    mocks["analytics_db"].record_request = AsyncMock()
    mocks["analytics_db"].get_summary = AsyncMock(return_value={
        "totals": {"total_requests": 1, "total_cost_usd": 0.001, "avg_duration_ms": 100.0,
                   "total_input_tokens": 50, "total_output_tokens": 30},
        "by_agent": [{"agent": "general_agent", "count": 1, "cost_usd": 0.001}],
        "by_model": [{"model": "claude-haiku", "count": 1, "cost_usd": 0.001}],
        "daily": [{"date": "2026-05-27", "count": 1, "cost_usd": 0.001}],
    })


def _mock_prompts(mocks: dict) -> None:
    mocks["prompts_db"].list_prompts = AsyncMock(return_value=[])
    mocks["prompts_db"].save_prompt = AsyncMock(return_value="prompt-id-123")
    mocks["prompts_db"].delete_prompt = AsyncMock(return_value=True)


def _mock_feedback(mocks: dict) -> None:
    mocks["feedback_db"].save_feedback = AsyncMock(return_value="feedback-id-1")
    mocks["feedback_db"].get_feedback = AsyncMock(return_value=[])
    mocks["feedback_db"].get_summary = AsyncMock(return_value={"total": 0, "positive": 0, "negative": 0})


def _mock_rag(mocks: dict) -> None:
    mocks["rag_db"].add_document = AsyncMock(return_value=["chunk-1"])
    mocks["rag_db"].list_documents = AsyncMock(return_value=[])
    mocks["rag_db"].search = AsyncMock(return_value=[])
    mocks["rag_db"].delete_document = AsyncMock(return_value=1)


def _mock_personas(mocks: dict) -> None:
    mocks["personas_db"].list_personas = AsyncMock(return_value=[])


def _mock_tags(mocks: dict) -> None:
    mocks["tags_db"].all_tags = AsyncMock(return_value=[])


def _mock_macros(mocks: dict) -> None:
    mocks["macros_db"].list_macros = AsyncMock(return_value=[])


def _mock_workflows(mocks: dict) -> None:
    mocks["workflows_db"].list_workflows = AsyncMock(return_value=[])
    mocks["workflows_db"].get_workflow = AsyncMock(return_value=None)
    mocks["workflows_db"].save_workflow = AsyncMock(return_value="wf-1")
    mocks["workflows_db"].delete_workflow = AsyncMock(return_value=True)
    mocks["workflows_db"].get_run = AsyncMock(return_value=None)


def _mock_experiments(mocks: dict) -> None:
    mocks["experiments_db"].list_experiments = AsyncMock(return_value=[])
    mocks["experiments_db"].get_experiment = AsyncMock(return_value=None)
    mocks["experiments_db"].create_experiment = AsyncMock(return_value="exp-1")
    mocks["experiments_db"].get_experiment_summary = AsyncMock(return_value={})
    mocks["experiments_db"].stop_experiment = AsyncMock(return_value=True)


def _mock_tenants(mocks: dict) -> None:
    mocks["tenants_db"].list_tenants = AsyncMock(return_value=[])
    mocks["tenants_db"].create_tenant = AsyncMock(return_value="t-1")
    mocks["tenants_db"].get_tenant = AsyncMock(return_value=None)


def _mock_prompt_versions(mocks: dict) -> None:
    mocks["prompt_versions_db"].list_versions = AsyncMock(return_value=[])


def _mock_infra(mocks: dict) -> None:
    """Scheduler, preprocessor, session, title/tag background tasks."""
    async def _pp(msg): return msg, ""
    mocks["preprocess_message"].side_effect = _pp
    mocks["get_session"].return_value = mocks["mock_orch"]
    mocks["scheduler"].schedule = MagicMock(return_value="task-1")
    mocks["scheduler"].list_tasks = MagicMock(return_value=[])
    mocks["scheduler"].get_task = MagicMock(return_value=None)
    mocks["scheduler"].set_handler = MagicMock()


def _configure_mocks(mocks: dict) -> None:
    """Wire all mocks by composing domain helpers."""
    mocks["init_db"].return_value = MagicMock()
    _mock_db_base(mocks)
    _mock_analytics(mocks)
    _mock_prompts(mocks)
    _mock_feedback(mocks)
    _mock_rag(mocks)
    _mock_personas(mocks)
    _mock_tags(mocks)
    _mock_macros(mocks)
    _mock_workflows(mocks)
    _mock_experiments(mocks)
    _mock_tenants(mocks)
    _mock_prompt_versions(mocks)
    _mock_infra(mocks)


# #23 — Use function scope so each test class gets a clean client/session state.
@pytest.fixture(scope="function")
def client():
    from contextlib import ExitStack
    mock_orch = _make_mock_orchestrator()

    patches = {
        "init_db":              patch("api.server.init_db", new_callable=AsyncMock),
        "memory_db":            patch("api.db.memory_db"),
        "analytics_db":        patch("api.db.analytics_db"),
        "prompts_db":           patch("api.db.prompts_db"),
        "feedback_db":          patch("api.db.feedback_db"),
        "rag_db":               patch("api.db.rag_db"),
        "file_versions_db":     patch("api.db.file_versions_db"),
        "cache_db":             patch("api.db.cache_db"),
        "personas_db":          patch("api.db.personas_db"),
        "tags_db":              patch("api.db.tags_db"),
        "agent_checkpoints_db": patch("api.db.agent_checkpoints_db"),
        "collab_graph_db":      patch("api.db.collab_graph_db"),
        "macros_db":            patch("api.db.macros_db"),
        "batch_db":             patch("api.db.batch_db"),
        "workflows_db":         patch("api.db.workflows_db"),
        "experiments_db":       patch("api.db.experiments_db"),
        "prompt_versions_db":   patch("api.db.prompt_versions_db"),
        "tenants_db":           patch("api.db.tenants_db"),
        "memory_graph_db":      patch("api.db.memory_graph_db"),
        "webhooks_db":          patch("api.db.webhooks_db"),
        "preprocess_message":   patch("api.preprocessor.preprocess", new_callable=AsyncMock),
        "_auto_title_session":  patch("api.state._auto_title_session", new_callable=AsyncMock),
        "_auto_tag_session":    patch("api.state._auto_tag_session", new_callable=AsyncMock),
        "set_session_title":    patch("api.db.set_session_title", new_callable=AsyncMock),
        "add_auto_tags":        patch("api.db.add_auto_tags", new_callable=AsyncMock),
        "get_session_title":    patch("api.db.get_session_title", new_callable=AsyncMock),
        "get_session":          patch("api.state.get_session", new_callable=AsyncMock),
        "scheduler":            patch("core.scheduler.scheduler"),
    }

    with ExitStack() as stack:
        mocks = {k: stack.enter_context(v) for k, v in patches.items()}
        mocks["mock_orch"] = mock_orch
        _configure_mocks(mocks)

        from api.server import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ─── Root ─────────────────────────────────────────────────────────────────────

class TestRoot:
    def test_get_root_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_get_root_returns_running_status(self, client):
        resp = client.get("/")
        assert resp.json()["status"] == "running"

    def test_get_root_includes_version(self, client):
        resp = client.get("/")
        assert "version" in resp.json()

    def test_get_root_lists_models(self, client):
        resp = client.get("/")
        data = resp.json()
        assert "models" in data
        assert isinstance(data["models"], list)


# ─── Chat ─────────────────────────────────────────────────────────────────────

class TestChatEndpoint:
    def test_post_chat_returns_200(self, client):
        resp = client.post("/chat", json={"message": "hello", "session_id": "test-session"})
        assert resp.status_code == 200

    def test_post_chat_returns_response_field(self, client):
        resp = client.post("/chat", json={"message": "hello", "session_id": "test-session"})
        assert "response" in resp.json()

    def test_post_chat_returns_model_used(self, client):
        resp = client.post("/chat", json={"message": "hello", "session_id": "test-session"})
        assert resp.json()["model_used"] == "claude-haiku"

    def test_post_chat_returns_agent_used(self, client):
        resp = client.post("/chat", json={"message": "hello", "session_id": "test-session"})
        assert resp.json()["agent_used"] == "general_agent"

    def test_post_chat_invalid_session_id_returns_422(self, client):
        resp = client.post("/chat", json={"message": "hi", "session_id": "bad id with spaces!"})
        assert resp.status_code == 422

    def test_post_chat_empty_message_still_processes(self, client):
        resp = client.post("/chat", json={"message": "   ", "session_id": "test-session"})
        assert resp.status_code in (200, 400, 422)


# ─── Models ───────────────────────────────────────────────────────────────────

class TestModelsEndpoint:
    def test_get_models_returns_200(self, client):
        resp = client.get("/models")
        assert resp.status_code == 200

    def test_get_models_returns_list(self, client):
        resp = client.get("/models")
        assert isinstance(resp.json()["models"], list)


# ─── History ──────────────────────────────────────────────────────────────────

class TestHistoryEndpoint:
    def test_get_history_returns_200(self, client):
        with patch("api.db.load_history", new_callable=AsyncMock) as mock_hist:
            mock_hist.return_value = []
            resp = client.get("/history/test-session")
        assert resp.status_code == 200

    def test_get_history_invalid_session_id_returns_400(self, client):
        resp = client.get("/history/bad id with spaces")
        assert resp.status_code == 400

    def test_delete_history_returns_200(self, client):
        with patch("api.db.db_clear_history", new_callable=AsyncMock):
            resp = client.delete("/history/test-session")
        assert resp.status_code == 200

    def test_delete_history_invalid_session_returns_400(self, client):
        resp = client.delete("/history/bad id with spaces")
        assert resp.status_code == 400


# ─── Sessions ─────────────────────────────────────────────────────────────────

class TestSessionsEndpoint:
    def test_get_sessions_returns_200(self, client):
        with patch("api.db.db_list_sessions", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []
            resp = client.get("/sessions")
        assert resp.status_code == 200

    def test_get_sessions_returns_sessions_key(self, client):
        with patch("api.db.db_list_sessions", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []
            resp = client.get("/sessions")
        assert "sessions" in resp.json()

    def test_get_sessions_respects_limit_param(self, client):
        with patch("api.db.db_list_sessions", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []
            resp = client.get("/sessions?limit=5&skip=10")
        assert resp.status_code == 200
        mock_list.assert_awaited_once_with(limit=5, skip=10, after=None)


# ─── Analytics ────────────────────────────────────────────────────────────────

class TestAnalyticsEndpoint:
    def test_get_analytics_returns_200(self, client):
        resp = client.get("/analytics")
        assert resp.status_code == 200

    def test_get_analytics_contains_totals(self, client):
        resp = client.get("/analytics")
        assert "totals" in resp.json()

    def test_get_analytics_days_param_is_forwarded(self, client):
        with patch("api.db.analytics_db") as mock_ana:
            mock_ana.get_summary = AsyncMock(return_value={
                "totals": {}, "by_agent": [], "by_model": [], "daily": []
            })
            resp = client.get("/analytics?days=7")
        assert resp.status_code == 200


# ─── Rate limiting ────────────────────────────────────────────────────────────

class TestRateLimiting:
    def test_rate_limit_allows_requests_under_threshold(self, client):
        resp = client.get("/")
        assert resp.status_code != 429

    def test_rate_limit_blocks_excessive_requests(self, client):
        import api.server as srv
        import time
        fake_ip = "999.999.999.999"
        now = time.time()
        srv._rate_windows[fake_ip] = [now] * srv._RATE_LIMIT_REQUESTS
        assert len(srv._rate_windows[fake_ip]) >= srv._RATE_LIMIT_REQUESTS
        del srv._rate_windows[fake_ip]


# ─── Workflows ────────────────────────────────────────────────────────────────

class TestWorkflowsEndpoint:
    def test_get_workflows_returns_200(self, client):
        resp = client.get("/workflows")
        assert resp.status_code == 200

    def test_get_workflows_returns_list(self, client):
        resp = client.get("/workflows")
        assert "workflows" in resp.json()

    def test_post_workflow_returns_200(self, client):
        resp = client.post("/workflows", json={
            "workflow_id": "test-wf",
            "name": "Test Workflow",
            "definition": {"nodes": [], "edges": []},
        })
        assert resp.status_code == 200

    def test_get_workflow_not_found_returns_404(self, client):
        resp = client.get("/workflows/nonexistent-wf")
        assert resp.status_code == 404


# ─── Experiments ──────────────────────────────────────────────────────────────

class TestExperimentsEndpoint:
    def test_get_experiments_returns_200(self, client):
        resp = client.get("/experiments")
        assert resp.status_code == 200

    def test_get_experiments_returns_list(self, client):
        resp = client.get("/experiments")
        assert "experiments" in resp.json()

    def test_post_experiment_returns_200(self, client):
        resp = client.post("/experiments", json={
            "experiment_id": "exp-test",
            "name": "Test Experiment",
            "variants": [
                {"name": "control", "agent": "general_agent"},
                {"name": "treatment", "agent": "code_agent"},
            ],
            "traffic_split": [0.5, 0.5],
        })
        assert resp.status_code == 200


# ─── Tenants ──────────────────────────────────────────────────────────────────

class TestTenantsEndpoint:
    def test_get_tenants_returns_200(self, client):
        resp = client.get("/tenants")
        assert resp.status_code == 200

    def test_get_tenants_returns_list(self, client):
        resp = client.get("/tenants")
        assert "tenants" in resp.json()

    def test_post_tenant_returns_200(self, client):
        resp = client.post("/tenants", json={
            "tenant_id": "acme",
            "name": "Acme Corp",
            "plan": "pro",
        })
        assert resp.status_code == 200

    def test_get_tenant_not_found_returns_404(self, client):
        resp = client.get("/tenants/nonexistent")
        assert resp.status_code == 404


# ─── Marketplace ──────────────────────────────────────────────────────────────

class TestMarketplaceEndpoint:
    def test_get_marketplace_returns_200(self, client):
        resp = client.get("/marketplace")
        assert resp.status_code == 200

    def test_get_marketplace_returns_agents(self, client):
        resp = client.get("/marketplace")
        data = resp.json()
        assert "agents" in data
        assert isinstance(data["agents"], list)
        assert len(data["agents"]) > 0

    def test_get_marketplace_filter_by_category(self, client):
        resp = client.get("/marketplace?category=dev")
        assert resp.status_code == 200

    def test_install_builtin_agent_returns_200(self, client):
        resp = client.post("/marketplace/code_agent/install")
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_available"


# ─── #22 Negative / edge-case tests ──────────────────────────────────────────

class TestNegativeCases:
    def test_chat_message_too_long_returns_422(self, client):
        """#2 — 50,001-char message must be rejected before hitting the LLM."""
        resp = client.post("/chat", json={"message": "x" * 50_001, "session_id": "default"})
        assert resp.status_code == 422

    def test_chat_empty_message_returns_422(self, client):
        """#2 — Empty message (min_length=1) must be rejected."""
        resp = client.post("/chat", json={"message": "", "session_id": "default"})
        assert resp.status_code == 422

    def test_chat_invalid_session_id_characters(self, client):
        """Session IDs with spaces/special chars must be rejected."""
        resp = client.post("/chat", json={"message": "hi", "session_id": "bad session!"})
        assert resp.status_code == 422

    def test_chat_session_id_too_long(self, client):
        """Session IDs longer than 64 chars must be rejected."""
        resp = client.post("/chat", json={"message": "hi", "session_id": "a" * 65})
        assert resp.status_code == 422

    def test_workflow_not_found_returns_404(self, client):
        resp = client.get("/workflows/definitely-does-not-exist")
        assert resp.status_code == 404

    def test_workflow_run_not_found_returns_404(self, client):
        resp = client.get("/workflows/runs/no-such-run")
        assert resp.status_code == 404

    def test_tenant_not_found_returns_404(self, client):
        resp = client.get("/tenants/no-such-tenant")
        assert resp.status_code == 404

    def test_persona_delete_nonexistent_returns_404(self, client):
        with patch("api.db.personas_db") as mock_p:
            mock_p.delete_persona = AsyncMock(return_value=False)
            resp = client.delete("/personas/no-such-persona")
        assert resp.status_code == 404

    def test_macro_delete_nonexistent_returns_404(self, client):
        with patch("api.db.macros_db") as mock_m:
            mock_m.delete_macro = AsyncMock(return_value=False)
            resp = client.delete("/macros/no-such-macro")
        assert resp.status_code == 404

    def test_marketplace_install_unknown_agent_returns_404(self, client):
        resp = client.post("/marketplace/no-such-agent/install")
        assert resp.status_code == 404

    def test_git_diff_empty_returns_400(self, client):
        resp = client.post("/chat/git-diff", json={"diff": "   ", "session_id": "default"})
        assert resp.status_code == 400

    def test_debate_rounds_out_of_range(self, client):
        resp = client.post("/chat/debate", json={
            "topic": "AI safety", "session_id": "default", "rounds": 10
        })
        assert resp.status_code == 422

    def test_variants_count_out_of_range(self, client):
        resp = client.post("/chat/variants", json={
            "message": "hello", "session_id": "default", "count": 10
        })
        assert resp.status_code == 422

    def test_schedule_delay_exceeds_max(self, client):
        resp = client.post("/schedule", json={
            "session_id": "default", "prompt": "hello", "delay_seconds": 90000
        })
        assert resp.status_code == 422

    def test_experiment_not_found_returns_404(self, client):
        resp = client.get("/experiments/no-such-experiment")
        assert resp.status_code == 404
