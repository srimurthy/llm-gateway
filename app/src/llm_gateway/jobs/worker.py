"""Process queued jobs.

A job that hits a budget or provider limit is not failed: its message is hidden for the
``Retry-After`` delay and picked up again, which spreads batch work into spare capacity.
SQS moves a message to the dead-letter queue after the queue's ``maxReceiveCount``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import structlog
from botocore.exceptions import BotoCoreError, ClientError

from llm_gateway.api.openai_format import build_completion
from llm_gateway.core.errors import (
    BackendUnavailableError,
    GatewayError,
    ProvidersThrottledError,
    ProvidersUnavailableError,
    RateLimitExceededError,
)
from llm_gateway.jobs.models import JobError, JobMessage
from llm_gateway.jobs.store import JobRepository
from llm_gateway.observability import metrics
from llm_gateway.services.chat import ChatService

if TYPE_CHECKING:
    from types_aiobotocore_sqs import SQSClient
    from types_aiobotocore_sqs.type_defs import MessageTypeDef

log = structlog.get_logger(__name__)

_MAX_VISIBILITY_TIMEOUT_S: Final = 43_200  # SQS limit: 12 hours
_RECEIVE_ERROR_BACKOFF_S: Final = 5.0


@dataclass(frozen=True, slots=True)
class RetryLater:
    delay_s: int


class JobProcessor:
    def __init__(self, *, chat: ChatService, repository: JobRepository) -> None:
        self._chat = chat
        self._repository = repository

    async def process(self, message: JobMessage) -> RetryLater | None:
        """Run one job. Returns ``RetryLater`` when the job should run again later."""
        try:
            outcome = await self._chat.complete(
                tenant=message.tenant, alias=message.alias, prompt=message.prompt
            )
        except (RateLimitExceededError, ProvidersThrottledError, ProvidersUnavailableError) as exc:
            metrics.JOBS_PROCESSED.labels(outcome="deferred").inc()
            return RetryLater(delay_s=exc.retry_after_s)
        except BackendUnavailableError:
            raise
        except GatewayError as exc:
            await self._repository.fail(
                message.job_id, JobError(code=exc.code, message=exc.message)
            )
            metrics.JOBS_PROCESSED.labels(outcome="failed").inc()
            return None

        completion = build_completion(
            completion_id=message.job_id.replace("job-", "chatcmpl-", 1),
            alias=message.alias,
            created=int(time.time()),
            result=outcome.result,
        )
        await self._repository.complete(
            message.job_id, completion.model_dump(mode="json", exclude_none=True)
        )
        metrics.JOBS_PROCESSED.labels(outcome="succeeded").inc()
        return None


class SqsJobConsumer:
    def __init__(
        self,
        client: SQSClient,
        *,
        queue_url: str,
        processor: JobProcessor,
        concurrency: int,
        wait_time_s: int = 20,
    ) -> None:
        self._client = client
        self._queue_url = queue_url
        self._processor = processor
        self._concurrency = concurrency
        self._wait_time_s = wait_time_s

    async def run(self, stop: asyncio.Event, *, drain_timeout_s: float = 60.0) -> None:
        in_flight: set[asyncio.Task[None]] = set()
        while not stop.is_set():
            capacity = self._concurrency - len(in_flight)
            if capacity <= 0:
                await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
                continue
            for message in await self._receive(min(10, capacity)):
                task = asyncio.create_task(self._handle(message))
                in_flight.add(task)
                task.add_done_callback(in_flight.discard)

        if in_flight:
            log.info("worker_draining", in_flight=len(in_flight))
            await asyncio.wait(in_flight, timeout=drain_timeout_s)

    async def _receive(self, max_messages: int) -> list[MessageTypeDef]:
        try:
            response = await self._client.receive_message(
                QueueUrl=self._queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=self._wait_time_s,
            )
        except (BotoCoreError, ClientError) as exc:
            log.warning("job_receive_failed", error=str(exc))
            await asyncio.sleep(_RECEIVE_ERROR_BACKOFF_S)
            return []
        return response.get("Messages", [])

    async def _handle(self, message: MessageTypeDef) -> None:
        receipt = message["ReceiptHandle"]
        try:
            job = JobMessage.from_json(message["Body"])
        except ValueError as exc:
            log.error("job_message_invalid", message_id=message.get("MessageId"), error=str(exc))
            await self._delete(receipt)
            return

        structlog.contextvars.bind_contextvars(job_id=job.job_id, tenant=job.tenant)
        try:
            retry = await self._processor.process(job)
        except Exception:  # the message reappears after its visibility timeout and is retried
            metrics.JOBS_PROCESSED.labels(outcome="error").inc()
            log.exception("job_processing_failed")
            return

        if retry is None:
            await self._delete(receipt)
        else:
            await self._defer(receipt, retry.delay_s)

    async def _delete(self, receipt: str) -> None:
        await self._call(
            self._client.delete_message, QueueUrl=self._queue_url, ReceiptHandle=receipt
        )

    async def _defer(self, receipt: str, delay_s: int) -> None:
        await self._call(
            self._client.change_message_visibility,
            QueueUrl=self._queue_url,
            ReceiptHandle=receipt,
            VisibilityTimeout=min(max(delay_s, 1), _MAX_VISIBILITY_TIMEOUT_S),
        )

    @staticmethod
    async def _call(operation: Any, **kwargs: Any) -> None:  # noqa: ANN401 - typed SQS methods
        try:
            await operation(**kwargs)
        except (BotoCoreError, ClientError) as exc:
            log.warning("job_queue_update_failed", operation=operation.__name__, error=str(exc))
