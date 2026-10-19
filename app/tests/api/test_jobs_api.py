import httpx

from llm_gateway.core.errors import ProviderThrottledError
from llm_gateway.jobs.models import JobStatus
from llm_gateway.jobs.worker import JobProcessor, RetryLater
from llm_gateway.services.chat import ChatService
from tests.conftest import TENANT_HEADERS
from tests.fakes import Fail, InMemoryJobQueue, InMemoryJobRepository, ScriptedProvider

BODY = {"model": "fast", "messages": [{"role": "user", "content": "summarize"}]}


async def test_submit_then_process_then_fetch(
    client: httpx.AsyncClient,
    app: object,
    jobs_queue: InMemoryJobQueue,
    jobs_repository: InMemoryJobRepository,
) -> None:
    submitted = await client.post("/v1/async/chat/completions", json=BODY, headers=TENANT_HEADERS)
    assert submitted.status_code == 202
    job_id = submitted.json()["id"]

    pending = await client.get(f"/v1/async/jobs/{job_id}", headers=TENANT_HEADERS)
    assert pending.json()["status"] == "queued"

    chat: ChatService = app.state.container.chat  # type: ignore[attr-defined]
    processor = JobProcessor(chat=chat, repository=jobs_repository)
    assert await processor.process(jobs_queue.messages[0]) is None

    done = await client.get(f"/v1/async/jobs/{job_id}", headers=TENANT_HEADERS)
    body = done.json()
    assert body["status"] == "succeeded"
    assert body["result"]["choices"][0]["message"]["content"] == "hello world"


async def test_other_tenants_cannot_see_a_job(client: httpx.AsyncClient) -> None:
    submitted = await client.post("/v1/async/chat/completions", json=BODY, headers=TENANT_HEADERS)
    job_id = submitted.json()["id"]

    response = await client.get(f"/v1/async/jobs/{job_id}", headers={"x-tenant-id": "team-other"})

    assert response.status_code == 404


async def test_disallowed_alias_is_rejected_at_submission(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/async/chat/completions",
        json={**BODY, "model": "smart"},
        headers={"x-tenant-id": "team-restricted"},
    )

    assert response.status_code == 403


async def test_throttled_job_is_deferred_not_failed(
    client: httpx.AsyncClient,
    app: object,
    primary: ScriptedProvider,
    secondary: ScriptedProvider,
    jobs_queue: InMemoryJobQueue,
    jobs_repository: InMemoryJobRepository,
) -> None:
    primary._behaviors = [Fail(ProviderThrottledError("primary", "429"))]
    secondary._behaviors = [Fail(ProviderThrottledError("secondary", "429"))]
    await client.post("/v1/async/chat/completions", json=BODY, headers=TENANT_HEADERS)
    message = jobs_queue.messages[0]

    chat: ChatService = app.state.container.chat  # type: ignore[attr-defined]
    outcome = await JobProcessor(chat=chat, repository=jobs_repository).process(message)

    assert isinstance(outcome, RetryLater)
    assert jobs_repository.jobs[message.job_id].status is JobStatus.QUEUED
