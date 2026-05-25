"""
Lightweight task scheduler — delayed and periodic agent task execution.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Callable, Awaitable


class ScheduledTask:
    def __init__(self, task_id: str, session_id: str, prompt: str, run_at: datetime):
        self.task_id = task_id
        self.session_id = session_id
        self.prompt = prompt
        self.run_at = run_at
        self.status: str = "pending"  # pending | running | done | failed
        self.result: str | None = None
        self.error: str | None = None


class TaskScheduler:
    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        self._handler: Callable[[str, str], Awaitable[str]] | None = None

    def set_handler(self, handler: Callable[[str, str], Awaitable[str]]) -> None:
        """Register the coroutine to call when a task fires (session_id, message) -> response."""
        self._handler = handler

    def schedule(self, session_id: str, prompt: str, delay_seconds: float) -> str:
        """Schedule a task to run after delay_seconds. Returns task_id."""
        task_id = str(uuid.uuid4())[:8]
        run_at = datetime.now(timezone.utc)
        task = ScheduledTask(task_id, session_id, prompt, run_at)
        self._tasks[task_id] = task
        asyncio.create_task(self._run_after(task, delay_seconds))
        return task_id

    async def _run_after(self, task: ScheduledTask, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)
        task.status = "running"
        try:
            if self._handler:
                task.result = await self._handler(task.session_id, task.prompt)
            task.status = "done"
        except Exception as e:
            task.error = str(e)
            task.status = "failed"

    def get_task(self, task_id: str) -> ScheduledTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self, session_id: str | None = None) -> list[dict]:
        tasks = self._tasks.values()
        if session_id:
            tasks = [t for t in tasks if t.session_id == session_id]
        return [
            {
                "task_id": t.task_id,
                "session_id": t.session_id,
                "prompt": t.prompt[:100],
                "status": t.status,
                "run_at": t.run_at.isoformat(),
                "result": t.result[:200] if t.result else None,
                "error": t.error,
            }
            for t in tasks
        ]


# Global singleton
scheduler = TaskScheduler()
