"""
Lightweight task scheduler — delayed and periodic agent task execution.
"""
import asyncio
import uuid
import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

_CLEANUP_KEEP_STATUSES = {"pending", "running"}
_MAX_COMPLETED_TASKS = 200


class ScheduledTask:
    def __init__(
        self,
        task_id: str,
        session_id: str,
        prompt: str,
        run_at: datetime,
        interval_seconds: float | None = None,
    ):
        self.task_id = task_id
        self.session_id = session_id
        self.prompt = prompt
        self.run_at = run_at
        self.interval_seconds = interval_seconds  # None = one-off
        self.status: str = "pending"  # pending | running | done | failed | recurring
        self.result: str | None = None
        self.error: str | None = None
        self.run_count: int = 0


class TaskScheduler:
    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        # #21 — retain asyncio.Task references to prevent GC before completion
        self._asyncio_tasks: dict[str, asyncio.Task] = {}
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

        # #21 — store reference so the task is not garbage-collected
        asyncio_task = asyncio.create_task(self._run_after(task, delay_seconds))
        self._asyncio_tasks[task_id] = asyncio_task

        # #22 — clean up old completed tasks to prevent unbounded growth
        self._cleanup_completed()
        return task_id

    def schedule_recurring(self, session_id: str, prompt: str, interval_seconds: float) -> str:
        """Schedule a recurring task that fires every interval_seconds. Returns task_id."""
        task_id = str(uuid.uuid4())[:8]
        run_at = datetime.now(timezone.utc)
        task = ScheduledTask(task_id, session_id, prompt, run_at, interval_seconds)
        task.status = "recurring"
        self._tasks[task_id] = task

        asyncio_task = asyncio.create_task(self._run_recurring(task, interval_seconds))
        self._asyncio_tasks[task_id] = asyncio_task
        return task_id

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending/recurring task. Returns True if cancelled."""
        asyncio_task = self._asyncio_tasks.pop(task_id, None)
        if asyncio_task:
            asyncio_task.cancel()
        task = self._tasks.get(task_id)
        if task:
            task.status = "cancelled"
            return True
        return False

    async def _run_after(self, task: ScheduledTask, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)
        task.status = "running"
        try:
            if self._handler:
                task.result = await self._handler(task.session_id, task.prompt)
            task.status = "done"
        except Exception as e:
            logger.warning("Scheduled task %s failed: %s", task.task_id, e)
            task.error = str(e)
            task.status = "failed"
        finally:
            # Release the asyncio.Task reference once complete
            self._asyncio_tasks.pop(task.task_id, None)

    async def _run_recurring(self, task: ScheduledTask, interval_seconds: float) -> None:
        try:
            while True:
                await asyncio.sleep(interval_seconds)
                task.run_count += 1
                try:
                    if self._handler:
                        task.result = await self._handler(task.session_id, task.prompt)
                except Exception as e:
                    logger.warning("Recurring task %s failed (run %d): %s", task.task_id, task.run_count, e)
                    task.error = str(e)
        except asyncio.CancelledError:
            task.status = "cancelled"
        finally:
            self._asyncio_tasks.pop(task.task_id, None)

    def _cleanup_completed(self) -> None:
        """#22 — remove oldest done/failed tasks beyond the retention limit."""
        completed = [
            t for t in self._tasks.values()
            if t.status not in _CLEANUP_KEEP_STATUSES
        ]
        if len(completed) > _MAX_COMPLETED_TASKS:
            completed.sort(key=lambda t: t.run_at)
            to_remove = completed[:len(completed) - _MAX_COMPLETED_TASKS]
            for t in to_remove:
                del self._tasks[t.task_id]

    def get_task(self, task_id: str) -> ScheduledTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self, session_id: str | None = None) -> list[dict]:
        tasks = list(self._tasks.values())
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
                "interval_seconds": t.interval_seconds,
                "run_count": t.run_count,
            }
            for t in tasks
        ]


# Global singleton
scheduler = TaskScheduler()
