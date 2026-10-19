import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError

from llm_gateway.core.errors import BackendUnavailableError
from llm_gateway.core.models import ChatMessage, ChatPrompt, Role
from llm_gateway.jobs.models import Job, JobError, JobMessage, JobStatus, new_job_id
from llm_gateway.jobs.store import MAX_RESULT_BYTES, DynamoJobRepository, SqsJobQueue
from llm_gateway.jobs.worker import RetryLater, SqsJobConsumer

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
PROMPT = ChatPrompt(messages=(ChatMessage(Role.USER, "hi"),), max_tokens=5, stop=("x",))


class FakeDynamo:
    """Just enough of the DynamoDB client for the job repository's three calls."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.fail = False

    def _check(self) -> None:
        if self.fail:
            raise ClientError({"Error": {"Code": "InternalServerError"}}, "op")

    async def put_item(self, *, Item: dict[str, Any], **_: Any) -> None:  # noqa: N803
        self._check()
        self.items[Item["job_id"]["S"]] = dict(Item)

    async def get_item(self, *, Key: dict[str, Any], **_: Any) -> dict[str, Any]:  # noqa: N803
        self._check()
        item = self.items.get(Key["job_id"]["S"])
        return {"Item": item} if item else {}

    async def update_item(
        self,
        *,
        Key: dict[str, Any],  # noqa: N803
        ExpressionAttributeNames: dict[str, str],  # noqa: N803
        ExpressionAttributeValues: dict[str, Any],  # noqa: N803
        **_: Any,
    ) -> None:
        self._check()
        item = self.items[Key["job_id"]["S"]]
        item[ExpressionAttributeNames["#status"]] = ExpressionAttributeValues[":status"]
        item[ExpressionAttributeNames["#field"]] = ExpressionAttributeValues[":value"]


@pytest.fixture
def dynamo() -> FakeDynamo:
    return FakeDynamo()


@pytest.fixture
def repository(dynamo: FakeDynamo) -> DynamoJobRepository:
    return DynamoJobRepository(
        dynamo,  # type: ignore[arg-type]
        table="jobs",
        retention=timedelta(days=7),
        clock=lambda: NOW,
    )


def queued_job() -> Job:
    return Job(new_job_id(), "t", "fast", JobStatus.QUEUED, NOW)


async def test_job_round_trip(repository: DynamoJobRepository, dynamo: FakeDynamo) -> None:
    job = queued_job()
    await repository.create(job)
    await repository.complete(job.job_id, {"object": "chat.completion"})

    stored = await repository.get(job.job_id)

    assert stored is not None
    assert stored.status is JobStatus.SUCCEEDED
    assert stored.result == {"object": "chat.completion"}
    expires = int(dynamo.items[job.job_id]["expires_at"]["N"])
    assert expires == int((NOW + timedelta(days=7)).timestamp())


async def test_failed_job_keeps_error(repository: DynamoJobRepository) -> None:
    job = queued_job()
    await repository.create(job)
    await repository.fail(job.job_id, JobError("model_not_allowed", "no"))

    stored = await repository.get(job.job_id)

    assert stored is not None
    assert stored.error == JobError("model_not_allowed", "no")


async def test_oversized_result_fails_the_job(repository: DynamoJobRepository) -> None:
    job = queued_job()
    await repository.create(job)

    await repository.complete(job.job_id, {"text": "x" * MAX_RESULT_BYTES})

    stored = await repository.get(job.job_id)
    assert stored is not None
    assert stored.error is not None
    assert stored.error.code == "result_too_large"


async def test_missing_job_is_none(repository: DynamoJobRepository) -> None:
    assert await repository.get("job-" + "0" * 32) is None


async def test_dynamodb_errors_become_backend_unavailable(
    repository: DynamoJobRepository, dynamo: FakeDynamo
) -> None:
    dynamo.fail = True

    with pytest.raises(BackendUnavailableError):
        await repository.create(queued_job())
    with pytest.raises(BackendUnavailableError):
        await repository.get("job-1")


def test_job_message_round_trip() -> None:
    message = JobMessage(job_id="job-1", tenant="t", alias="fast", prompt=PROMPT)

    assert JobMessage.from_json(message.to_json()) == message


@pytest.mark.parametrize("body", ["not json", "{}", '{"job_id": 1, "prompt": {"messages": 3}}'])
def test_malformed_job_message_raises_value_error(body: str) -> None:
    with pytest.raises(ValueError, match="malformed"):
        JobMessage.from_json(body)


class FakeSqs:
    def __init__(self, stop: asyncio.Event, messages: list[dict[str, Any]]) -> None:
        self._stop = stop
        self._batches = [messages]
        self.sent: list[str] = []
        self.deleted: list[str] = []
        self.deferred: dict[str, int] = {}

    async def send_message(self, *, MessageBody: str, **_: Any) -> None:  # noqa: N803
        self.sent.append(MessageBody)

    async def receive_message(self, **_: Any) -> dict[str, Any]:
        if self._batches:
            return {"Messages": self._batches.pop()}
        self._stop.set()
        return {}

    async def delete_message(self, *, ReceiptHandle: str, **_: Any) -> None:  # noqa: N803
        self.deleted.append(ReceiptHandle)

    async def change_message_visibility(
        self,
        *,
        ReceiptHandle: str,  # noqa: N803
        VisibilityTimeout: int,  # noqa: N803
        **_: Any,
    ) -> None:
        self.deferred[ReceiptHandle] = VisibilityTimeout


class ScriptedProcessor:
    def __init__(self, outcomes: dict[str, RetryLater | Exception | None]) -> None:
        self._outcomes = outcomes

    async def process(self, message: JobMessage) -> RetryLater | None:
        outcome = self._outcomes[message.job_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def sqs_message(receipt: str, job_id: str) -> dict[str, Any]:
    body = JobMessage(job_id=job_id, tenant="t", alias="fast", prompt=PROMPT).to_json()
    return {"ReceiptHandle": receipt, "MessageId": receipt, "Body": body}


async def test_consumer_deletes_defers_and_leaves_messages() -> None:
    stop = asyncio.Event()
    sqs = FakeSqs(
        stop,
        [
            sqs_message("r-done", "job-done"),
            sqs_message("r-later", "job-later"),
            sqs_message("r-crash", "job-crash"),
            {"ReceiptHandle": "r-bad", "MessageId": "r-bad", "Body": "garbage"},
        ],
    )
    processor = ScriptedProcessor(
        {"job-done": None, "job-later": RetryLater(7), "job-crash": RuntimeError("boom")}
    )
    consumer = SqsJobConsumer(
        sqs,  # type: ignore[arg-type]
        queue_url="q",
        processor=processor,  # type: ignore[arg-type]
        concurrency=4,
    )

    await asyncio.wait_for(consumer.run(stop), timeout=5)

    assert sorted(sqs.deleted) == ["r-bad", "r-done"]
    assert sqs.deferred == {"r-later": 7}


async def test_queue_publishes_message_json() -> None:
    sqs = FakeSqs(asyncio.Event(), [])
    message = JobMessage(job_id="job-1", tenant="t", alias="fast", prompt=PROMPT)

    await SqsJobQueue(sqs, queue_url="q").publish(message)  # type: ignore[arg-type]

    assert JobMessage.from_json(sqs.sent[0]) == message
