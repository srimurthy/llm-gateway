"""Job storage (DynamoDB) and the job queue (SQS).

Both translate AWS errors into ``BackendUnavailableError`` so callers never see botocore.
The jobs table is a global table, so a job submitted in one region can be read from the
other after a failover.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Protocol

from botocore.exceptions import BotoCoreError, ClientError

from llm_gateway.core.errors import BackendUnavailableError
from llm_gateway.jobs.models import Job, JobError, JobMessage, JobStatus

if TYPE_CHECKING:
    from types_aiobotocore_dynamodb import DynamoDBClient
    from types_aiobotocore_sqs import SQSClient

# DynamoDB items max out at 400 KB; leave room for the other attributes.
MAX_RESULT_BYTES: Final = 350_000


class JobRepository(Protocol):
    async def create(self, job: Job) -> None: ...

    async def get(self, job_id: str) -> Job | None: ...

    async def complete(self, job_id: str, result: Mapping[str, Any]) -> None: ...

    async def fail(self, job_id: str, error: JobError) -> None: ...


class JobQueue(Protocol):
    async def publish(self, message: JobMessage) -> None: ...


class DynamoJobRepository:
    def __init__(
        self,
        client: DynamoDBClient,
        *,
        table: str,
        retention: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._table = table
        self._retention = retention
        self._clock = clock

    async def create(self, job: Job) -> None:
        expires_at = int((job.created_at + self._retention).timestamp())
        try:
            await self._client.put_item(
                TableName=self._table,
                Item={
                    "job_id": {"S": job.job_id},
                    "tenant": {"S": job.tenant},
                    "alias": {"S": job.alias},
                    "status": {"S": job.status.value},
                    "created_at": {"S": job.created_at.isoformat()},
                    "expires_at": {"N": str(expires_at)},
                },
                ConditionExpression="attribute_not_exists(job_id)",
            )
        except (BotoCoreError, ClientError) as exc:
            raise BackendUnavailableError("Could not store the job. Try again.") from exc

    async def get(self, job_id: str) -> Job | None:
        try:
            response = await self._client.get_item(
                TableName=self._table, Key={"job_id": {"S": job_id}}
            )
        except (BotoCoreError, ClientError) as exc:
            raise BackendUnavailableError("Could not read the job. Try again.") from exc
        item = response.get("Item")
        if item is None:
            return None
        error = json.loads(item["error"]["S"]) if "error" in item else None
        return Job(
            job_id=item["job_id"]["S"],
            tenant=item["tenant"]["S"],
            alias=item["alias"]["S"],
            status=JobStatus(item["status"]["S"]),
            created_at=datetime.fromisoformat(item["created_at"]["S"]),
            result=json.loads(item["result"]["S"]) if "result" in item else None,
            error=JobError(code=error["code"], message=error["message"]) if error else None,
        )

    async def complete(self, job_id: str, result: Mapping[str, Any]) -> None:
        body = json.dumps(result, separators=(",", ":"))
        if len(body.encode()) > MAX_RESULT_BYTES:
            await self.fail(
                job_id,
                JobError(
                    code="result_too_large",
                    message="The completion is too large to store. Use a streaming request.",
                ),
            )
            return
        await self._finish(job_id, JobStatus.SUCCEEDED, "result", body)

    async def fail(self, job_id: str, error: JobError) -> None:
        body = json.dumps({"code": error.code, "message": error.message})
        await self._finish(job_id, JobStatus.FAILED, "error", body)

    async def _finish(self, job_id: str, status: JobStatus, field: str, value: str) -> None:
        try:
            await self._client.update_item(
                TableName=self._table,
                Key={"job_id": {"S": job_id}},
                UpdateExpression="SET #status = :status, #field = :value, updated_at = :now",
                ConditionExpression="attribute_exists(job_id)",
                ExpressionAttributeNames={"#status": "status", "#field": field},
                ExpressionAttributeValues={
                    ":status": {"S": status.value},
                    ":value": {"S": value},
                    ":now": {"S": self._clock().isoformat()},
                },
            )
        except (BotoCoreError, ClientError) as exc:
            raise BackendUnavailableError("Could not update the job.") from exc


class SqsJobQueue:
    def __init__(self, client: SQSClient, *, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    async def publish(self, message: JobMessage) -> None:
        try:
            await self._client.send_message(QueueUrl=self._queue_url, MessageBody=message.to_json())
        except (BotoCoreError, ClientError) as exc:
            raise BackendUnavailableError("Could not queue the job. Try again.") from exc
