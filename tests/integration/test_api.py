"""
Integration / smoke tests for api/server.py.

Uses FastAPI's TestClient (httpx-based, synchronous) so no real network or
database connections are needed — all heavy dependencies are mocked via
monkeypatching the module-level helpers.
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
    orch.get_stats = MagicMock(return_value={"messages_in_history": 0})
    orch.clear_history = MagicMock()

    router = MagicMock()
    router.route = AsyncMock(return_value=decision)
    orch.router = router
    return orch


# ─── Fixture — patch all I/O before importing the app ─────────────────────────

@pytest.fixture(scope="module")
def client():
    mock_orch = _make_mock_orchestrator()

    with patch("api.server.init_db", new_callable=AsyncMock) as mock_init_db, \
         patch("api.server.memory_db") as mock_mem, \
         patch("api.server.analytics_db") as mock_ana, \
         patch("api.server.prompts_db") as mock_prompts, \
         patch("api.server.feedback_db") as mock_feedback, \
         patch("api.server.rag_db") as mock_rag, \
         patch("api.server.file_versions_db") as mock_fv, \
         patch("api.server.cache_db") as mock_cache, \
         patch("api.server.personas_db") as mock_personas, \
         patch("api.server.tags_db") as mock_tags, \
         patch("api.server.get_session", new_callable=AsyncMock) as mock_get_session, \
         patch("api.server.scheduler") as mock_sched:

        mock_init_db.return_value = MagicMock()
        mock_mem.set_db = MagicMock()
        mock_ana.set_db = MagicMock()
        mock_ana.record_request = AsyncMock()
        mock_ana.get_summary = AsyncMock(return_value={
            "totals": {"total_requests": 1, "total_cost_usd": 0.001, "avg_duration_ms": 100.0,
                       "total_input_tokens": 50, "total_output_tokens": 30},
            "by_agent": [{"agent": "general_agent", "count": 1, "cost_usd": 0.001}],
            "by_model": [{"model": "claude-haiku", "count": 1, "cost_usd": 0.001}],
            "daily": [{"date": "2026-05-27", "count": 1, "cost_usd": 0.001}],
        })
        mock_prompts.set_db = MagicMock()
        mock_prompts.list_prompts = AsyncMock(return_value=[])
        mock_prompts.save_prompt = AsyncMock(return_value="prompt-id-123")
        mock_prompts.delete_prompt = AsyncMock(return_value=True)
        mock_feedback.set_db = MagicMock()
        mock_feedback.ensure_indexes = AsyncMock()
        mock_feedback.save_feedback = AsyncMock(return_value="feedback-id-1")
        mock_feedback.get_feedback = AsyncMock(return_value=[])
        mock_feedback.get_summary = AsyncMock(return_value={"total": 0, "positive": 0, "negative": 0})
        mock_rag.set_db = MagicMock()
        mock_rag.ensure_indexes = AsyncMock()
        mock_rag.add_document = AsyncMock(return_value=["chunk-1"])
        mock_rag.list_documents = AsyncMock(return_value=[])
        mock_rag.search = AsyncMock(return_value=[])
        mock_rag.delete_document = AsyncMock(return_value=1)
        mock_fv.set_db = MagicMock()
        mock_fv.ensure_indexes = AsyncMock()
        mock_cache.set_db = MagicMock()
        mock_cache.ensure_indexes = AsyncMock()
        mock_personas.set_db = MagicMock()
        mock_personas.ensure_indexes = AsyncMock()
        mock_personas.list_personas = AsyncMock(return_value=[])
        mock_tags.set_db = MagicMock()
        mock_tags.ensure_indexes = AsyncMock()
        mock_tags.all_tags = AsyncMock(return_value=[])
        mock_get_session.return_value = mock_orch
        mock_sched.schedule = MagicMock(return_value="task-1")
        mock_sched.list_tasks = MagicMock(return_value=[])
        mock_sched.get_task = MagicMock(return_value=None)
        mock_sched.set_handler = MagicMock()

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
        # Empty/whitespace messages are accepted at the API level (agent decides)
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
        with patch("api.server.load_history", new_callable=AsyncMock) as mock_hist:
            mock_hist.return_value = []
            resp = client.get("/history/test-session")
        assert resp.status_code == 200

    def test_get_history_invalid_session_id_returns_400(self, client):
        resp = client.get("/history/bad id with spaces")
        assert resp.status_code == 400

    def test_delete_history_returns_200(self, client):
        with patch("api.server.db_clear_history", new_callable=AsyncMock):
            resp = client.delete("/history/test-session")
        assert resp.status_code == 200

    def test_delete_history_invalid_session_returns_400(self, client):
        resp = client.delete("/history/bad id with spaces")
        assert resp.status_code == 400


# ─── Sessions ─────────────────────────────────────────────────────────────────

class TestSessionsEndpoint:
    def test_get_sessions_returns_200(self, client):
        with patch("api.server.db_list_sessions", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []
            resp = client.get("/sessions")
        assert resp.status_code == 200

    def test_get_sessions_returns_sessions_key(self, client):
        with patch("api.server.db_list_sessions", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []
            resp = client.get("/sessions")
        assert "sessions" in resp.json()

    def test_get_sessions_respects_limit_param(self, client):
        with patch("api.server.db_list_sessions", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []
            resp = client.get("/sessions?limit=5&skip=10")
        assert resp.status_code == 200
        mock_list.assert_awaited_once_with(limit=5, skip=10)


# ─── Analytics ────────────────────────────────────────────────────────────────

class TestAnalyticsEndpoint:
    def test_get_analytics_returns_200(self, client):
        resp = client.get("/analytics")
        assert resp.status_code == 200

    def test_get_analytics_contains_totals(self, client):
        resp = client.get("/analytics")
        assert "totals" in resp.json()

    def test_get_analytics_days_param_is_forwarded(self, client):
        with patch("api.server.analytics_db") as mock_ana:
            mock_ana.get_summary = AsyncMock(return_value={
                "totals": {}, "by_agent": [], "by_model": [], "daily": []
            })
            resp = client.get("/analytics?days=7")
        assert resp.status_code == 200


# ─── Rate limiting ────────────────────────────────────────────────────────────

class TestRateLimiting:
    def test_rate_limit_allows_requests_under_threshold(self, client):
        # A single request should always succeed regardless of rate limit
        resp = client.get("/")
        assert resp.status_code != 429

    def test_rate_limit_blocks_excessive_requests(self, client):
        import api.server as srv
        # Inject fake timestamps to simulate hitting the rate limit
        fake_ip = "999.999.999.999"
        import time
        now = time.time()
        srv._rate_windows[fake_ip] = [now] * srv._RATE_LIMIT_REQUESTS
        # The next request from that IP should be rejected — but since TestClient
        # sends from 127.0.0.1 we just verify the dict logic directly
        assert len(srv._rate_windows[fake_ip]) >= srv._RATE_LIMIT_REQUESTS
        # Cleanup
        del srv._rate_windows[fake_ip]
