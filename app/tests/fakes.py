"""Test doubles. Each one implements a production protocol, not a mock of internals."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass, field
from typing import Any

from llm_gateway.config.routing import TenantPolicy
from llm_gateway.core.errors import ProviderError
from llm_gateway.core.models import ChatChunk, ChatRequest, ChatResult, FinishReason, Usage
from llm_gateway.jobs.models import Job, JobError, JobMessage, JobStatus
from llm_gateway.usage.ledger import UsageKey, UsageTotals


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Fail:
    """Raise ``error`` before producing anything."""

    error: ProviderError


@dataclass
class FailMidStream:
    """Stream ``chunks`` then raise ``error``."""

    chunks: list[str]
    error: ProviderError


@dataclass
class Succeed:
    text: str = "hello world"
    usage: Usage | None = field(default_factory=lambda: Usage(10, 2))


Behavior = Fail | FailMidStream | Succeed


class ScriptedProvider:
    """Plays one behavior per call, then repeats the last one."""

    def __init__(self, name: str, *behaviors: Behavior) -> None:
        self._name = name
        self._behaviors = list(behaviors) or [Succeed()]
        self.calls: list[ChatRequest] = []
        self.closed_streams = 0

    @property
    def name(self) -> str:
        return self._name

    def _next(self, request: ChatRequest) -> Behavior:
        self.calls.append(request)
        return self._behaviors.pop(0) if len(self._behaviors) > 1 else self._behaviors[0]

    async def complete(self, request: ChatRequest) -> ChatResult:
        behavior = self._next(request)
        if isinstance(behavior, Fail | FailMidStream):
            raise behavior.error
        return ChatResult(text=behavior.text, finish_reason=FinishReason.STOP, usage=behavior.usage)

    async def stream(self, request: ChatRequest) -> AsyncGenerator[ChatChunk]:
        behavior = self._next(request)
        try:
            if isinstance(behavior, Fail):
                raise behavior.error
            if isinstance(behavior, FailMidStream):
                for text in behavior.chunks:
                    yield ChatChunk(text=text)
                raise behavior.error
            for word in behavior.text.split(" "):
                yield ChatChunk(text=word + " ")
            yield ChatChunk(finish_reason=FinishReason.STOP, usage=behavior.usage)
        finally:
            self.closed_streams += 1


class StaticPolicies:
    def __init__(self, default: TenantPolicy, overrides: Mapping[str, TenantPolicy] | None = None):
        self._default = default
        self._overrides = dict(overrides or {})

    async def get(self, tenant: str) -> TenantPolicy:
        return self._overrides.get(tenant, self._default)


class RecordingUsageSink:
    def __init__(self) -> None:
        self.rows: list[tuple[UsageKey, UsageTotals]] = []

    async def write(self, key: UsageKey, totals: UsageTotals) -> None:
        self.rows.append((key, totals))


class InMemoryJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    async def create(self, job: Job) -> None:
        self.jobs[job.job_id] = job

    async def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def complete(self, job_id: str, result: Mapping[str, Any]) -> None:
        job = self.jobs[job_id]
        self.jobs[job_id] = Job(
            job.job_id, job.tenant, job.alias, JobStatus.SUCCEEDED, job.created_at, dict(result)
        )

    async def fail(self, job_id: str, error: JobError) -> None:
        job = self.jobs[job_id]
        self.jobs[job_id] = Job(
            job.job_id, job.tenant, job.alias, JobStatus.FAILED, job.created_at, error=error
        )


class InMemoryJobQueue:
    def __init__(self) -> None:
        self.messages: list[JobMessage] = []

    async def publish(self, message: JobMessage) -> None:
        self.messages.append(message)
