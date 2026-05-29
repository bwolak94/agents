"""
Load testing with Locust.
Install: pip install locust
Run:     locust -f locustfile.py --host=http://localhost:8000

Scenarios:
  - ChatUser: sends chat messages and reads history
  - AnalyticsReader: polls analytics/health endpoints
"""
import random
import uuid

from locust import HttpUser, between, task


class ChatUser(HttpUser):
    """Simulates a typical chat user: send message, read history, export."""

    wait_time = between(1, 4)

    def on_start(self):
        self.session_id = f"load-{uuid.uuid4().hex[:8]}"

    @task(5)
    def send_chat(self):
        prompts = [
            "Hello, what can you do?",
            "Write a haiku about Python.",
            "What is 2+2?",
            "Summarize the concept of machine learning in one sentence.",
            "List 3 programming languages.",
        ]
        self.client.post("/chat", json={
            "message": random.choice(prompts),
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
