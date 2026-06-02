"""
Load testing with Locust.
Install: pip install locust websocket-client
Run:     locust -f locustfile.py --host=http://localhost:8000

Scenarios:
  - ChatUser: sends chat messages and reads history
  - StreamUser: exercises /chat/stream SSE endpoint (F29)
  - FanOutUser: exercises /chat/fan-out endpoint (F29)
  - WsUser: exercises WebSocket /ws endpoint (F29)
  - AnalyticsReader: polls analytics/health endpoints
"""
import json
import random
import uuid

from locust import HttpUser, between, task

_PROMPTS = [
    "Hello, what can you do?",
    "Write a haiku about Python.",
    "What is 2+2?",
    "Summarize machine learning in one sentence.",
    "List 3 programming languages.",
    "What is the capital of France?",
    "Explain async/await in Python.",
]


class ChatUser(HttpUser):
    """Simulates a typical chat user: send message, read history, export."""

    wait_time = between(1, 4)

    def on_start(self):
        self.session_id = f"load-{uuid.uuid4().hex[:8]}"

    @task(5)
    def send_chat(self):
        self.client.post("/chat", json={
            "message": random.choice(_PROMPTS),
            "session_id": self.session_id,
        }, name="/chat")

    @task(2)
    def get_history(self):
        self.client.get(
            f"/history/{self.session_id}",
            name="/history/{session_id}",
        )

    @task(1)
    def get_stats(self):
        self.client.get(f"/stats?session_id={self.session_id}", name="/stats")

    @task(1)
    def list_sessions(self):
        self.client.get("/sessions?limit=20", name="/sessions")


class StreamUser(HttpUser):
    """F29 — exercises the SSE streaming endpoint /chat/stream."""

    wait_time = between(2, 6)

    def on_start(self):
        self.session_id = f"stream-{uuid.uuid4().hex[:8]}"

    @task(5)
    def stream_chat(self):
        with self.client.post(
            "/chat/stream",
            json={"message": random.choice(_PROMPTS), "session_id": self.session_id},
            stream=True,
            catch_response=True,
            name="/chat/stream",
        ) as resp:
            if resp.status_code == 200:
                for _ in resp.iter_lines():
                    pass  # consume the SSE stream
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(1)
    def health(self):
        self.client.get("/health", name="/health")


class FanOutUser(HttpUser):
    """F29 — exercises /chat/fan-out with multiple agents."""

    wait_time = between(3, 8)

    def on_start(self):
        self.session_id = f"fanout-{uuid.uuid4().hex[:8]}"

    @task(3)
    def fan_out(self):
        self.client.post("/chat/fan-out", json={
            "message": random.choice(_PROMPTS),
            "session_id": self.session_id,
            "agents": ["general_agent", "code_agent"],
        }, name="/chat/fan-out")

    @task(1)
    def get_history(self):
        self.client.get(f"/history/{self.session_id}", name="/history/{session_id}")


class WsUser(HttpUser):
    """F29 — exercises the WebSocket /ws endpoint."""

    wait_time = between(2, 5)

    def on_start(self):
        self.session_id = f"ws-{uuid.uuid4().hex[:8]}"

    @task
    def ws_chat(self):
        try:
            import websocket
            ws = websocket.create_connection(
                f"ws://localhost:8000/ws?session_id={self.session_id}",
                timeout=10,
            )
            ws.send(json.dumps({"message": random.choice(_PROMPTS)}))
            ws.recv()
            ws.close()
        except Exception:
            pass  # websocket-client may not be installed in all envs


class AnalyticsReader(HttpUser):
    """Simulates a dashboard user: health checks + analytics."""

    wait_time = between(2, 6)

    @task(3)
    def health(self):
        self.client.get("/health", name="/health")

    @task(2)
    def analytics(self):
        self.client.get("/analytics", name="/analytics")

    @task(1)
    def models(self):
        self.client.get("/models", name="/models")

    @task(1)
    def prometheus_metrics(self):
        self.client.get("/metrics", name="/metrics")
