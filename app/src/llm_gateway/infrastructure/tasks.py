"""Supervised fire-and-forget work.

Settling a token reservation must happen even when the client disconnects mid-stream,
which cancels the request's own task. Work handed to the supervisor runs in its own task,
is held by a strong reference until it finishes, and is drained on shutdown.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import structlog

from llm_gateway.observability import metrics

log = structlog.get_logger(__name__)


class TaskSupervisor:
    def __init__(self, *, limit: int) -> None:
        self._limit = limit
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def pending(self) -> int:
        return len(self._tasks)

    def spawn(self, coro: Coroutine[Any, Any, None], *, name: str) -> None:
        if len(self._tasks) >= self._limit:
            coro.close()
            metrics.BACKGROUND_TASKS_DROPPED.labels(task=name).inc()
            log.warning("background_task_dropped", task=name, pending=len(self._tasks))
            return
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)

    def _on_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            log.error("background_task_failed", task=task.get_name(), exc_info=error)

    async def drain(self, timeout_s: float) -> None:
        if not self._tasks:
            return
        _, pending = await asyncio.wait(set(self._tasks), timeout=timeout_s)
        if not pending:
            return
        log.warning("background_tasks_abandoned", count=len(pending))
        for task in pending:
            task.cancel()
        # Wait for the cancellations to land so nothing outlives the clients it uses.
        await asyncio.gather(*pending, return_exceptions=True)
