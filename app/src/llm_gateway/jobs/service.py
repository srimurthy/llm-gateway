"""Submit and look up async jobs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from llm_gateway.core.errors import BackendUnavailableError, JobNotFoundError
from llm_gateway.core.models import ChatPrompt
from llm_gateway.jobs.models import Job, JobError, JobMessage, JobStatus, new_job_id
from llm_gateway.jobs.store import JobQueue, JobRepository
from llm_gateway.routing.router import Router
from llm_gateway.services.access import authorize_alias
from llm_gateway.tenants.policies import TenantPolicyStore


class JobService:
    def __init__(
        self,
        *,
        router: Router,
        policies: TenantPolicyStore,
        repository: JobRepository,
        queue: JobQueue,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._router = router
        self._policies = policies
        self._repository = repository
        self._queue = queue
        self._clock = clock

    async def submit(self, *, tenant: str, alias: str, prompt: ChatPrompt) -> Job:
        # Reject what can never succeed now, instead of failing it in the worker later.
        await authorize_alias(self._policies, self._router, tenant=tenant, alias=alias)

        job = Job(
            job_id=new_job_id(),
            tenant=tenant,
            alias=alias,
            status=JobStatus.QUEUED,
            created_at=self._clock(),
        )
        await self._repository.create(job)
        try:
            await self._queue.publish(
                JobMessage(job_id=job.job_id, tenant=tenant, alias=alias, prompt=prompt)
            )
        except BackendUnavailableError:
            await self._repository.fail(
                job.job_id, JobError(code="enqueue_failed", message="The job was not queued.")
            )
            raise
        return job

    async def get(self, *, tenant: str, job_id: str) -> Job:
        job = await self._repository.get(job_id)
        # Another tenant's job is reported as missing, so job IDs leak nothing.
        if job is None or job.tenant != tenant:
            raise JobNotFoundError(job_id)
        return job
