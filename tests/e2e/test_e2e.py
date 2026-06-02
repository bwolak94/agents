"""#21 — End-to-end tests against a live API instance.

Set API_BASE_URL env var to the running API (default: http://localhost:8000).
These tests require a real MongoDB and API server — run via docker-compose.test.yml.
"""
import os
import pytest
import httpx

BASE = os.getenv("API_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=30) as c:
        yield c


def test_health(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "status" in r.json()


def test_models_health(client):
    r = client.get("/models/health")
    assert r.status_code == 200
    data = r.json()
    assert "health" in data


def test_list_workflows(client):
    r = client.get("/workflows")
    assert r.status_code == 200
    assert "workflows" in r.json()


def test_list_personas(client):
    r = client.get("/personas")
    assert r.status_code == 200
    assert "personas" in r.json()


def test_list_macros(client):
    r = client.get("/macros")
    assert r.status_code == 200
    assert "macros" in r.json()


def test_analytics_summary(client):
    r = client.get("/analytics/summary")
    assert r.status_code == 200


def test_collab_graph(client):
    r = client.get("/agents/collab-graph")
    assert r.status_code == 200
    data = r.json()
    assert "summary" in data
    assert isinstance(data["summary"], list)


def test_marketplace_list(client):
    r = client.get("/marketplace")
    assert r.status_code == 200
    data = r.json()
    assert "agents" in data
    assert len(data["agents"]) > 0


def test_create_and_delete_workflow(client):
    payload = {
        "workflow_id": "e2e-test-wf",
        "name": "E2E Test Workflow",
        "definition": {"nodes": [], "edges": []},
    }
    r = client.post("/workflows", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "saved"

    r = client.delete("/workflows/e2e-test-wf")
    assert r.status_code == 200


def test_negative_missing_workflow(client):
    r = client.get("/workflows/does-not-exist")
    assert r.status_code == 404


def test_negative_invalid_session_in_chat(client):
    r = client.post("/chat", json={"message": "hi", "session_id": "INVALID SESSION!"})
    assert r.status_code == 422


def test_negative_message_too_long(client):
    r = client.post("/chat", json={"message": "x" * 50_001, "session_id": "default"})
    assert r.status_code == 422
