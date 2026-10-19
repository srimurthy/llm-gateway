"""Usage ledger: tokens per tenant, alias and minute, summed across pods in DynamoDB.

Writing one row per request would make a busy tenant a hot partition. Instead each pod
sums usage in memory and flushes one ``ADD`` update per (tenant, alias, minute) every few
seconds, so write volume grows with the number of tenants, not the number of requests.

Row shape (usage table)::

    pk = "<tenant>#<alias>"    sk = "<YYYY-MM-DDTHH:MM>#<region>"
    prompt_tokens, completion_tokens, requests (numbers), expires_at (TTL)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

import structlog
from botocore.exceptions import BotoCoreError, ClientError

from llm_gateway.core.models import Usage
from llm_gateway.observability import metrics

if TYPE_CHECKING:
    from types_aiobotocore_dynamodb import DynamoDBClient

log = structlog.get_logger(__name__)

_MAX_CONCURRENT_WRITES = 16


@dataclass(frozen=True, slots=True)
class UsageKey:
    tenant: str
    alias: str
    minute: str


@dataclass(slots=True)
class UsageTotals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 0


class UsageSink(Protocol):
    async def write(self, key: UsageKey, totals: UsageTotals) -> None: ...


class NullUsageSink:
    """Discards usage. Used when no usage table is configured (local runs)."""

    async def write(self, key: UsageKey, totals: UsageTotals) -> None:  # noqa: ARG002
        return None


class DynamoUsageSink:
    def __init__(
        self, client: DynamoDBClient, *, table: str, region: str, retention: timedelta
    ) -> None:
        self._client = client
        self._table = table
        self._region = region
        self._retention = retention

    async def write(self, key: UsageKey, totals: UsageTotals) -> None:
        minute = datetime.fromisoformat(key.minute).replace(tzinfo=UTC)
        expires_at = int((minute + self._retention).timestamp())
        await self._client.update_item(
            TableName=self._table,
            Key={
                "pk": {"S": f"{key.tenant}#{key.alias}"},
                "sk": {"S": f"{key.minute}#{self._region}"},
            },
            UpdateExpression=(
                "ADD prompt_tokens :prompt, completion_tokens :completion, requests :requests "
                "SET expires_at = if_not_exists(expires_at, :expires)"
            ),
            ExpressionAttributeValues={
                ":prompt": {"N": str(totals.prompt_tokens)},
                ":completion": {"N": str(totals.completion_tokens)},
                ":requests": {"N": str(totals.requests)},
                ":expires": {"N": str(expires_at)},
            },
        )


class UsageLedger:
    def __init__(
        self,
        sink: UsageSink,
        *,
        flush_interval_s: float,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sink = sink
        self._flush_interval_s = flush_interval_s
        self._clock = clock
        self._pending: defaultdict[UsageKey, UsageTotals] = defaultdict(UsageTotals)
        self._task: asyncio.Task[None] | None = None

    def add(self, *, tenant: str, alias: str, usage: Usage) -> None:
        minute = self._clock().strftime("%Y-%m-%dT%H:%M")
        totals = self._pending[UsageKey(tenant=tenant, alias=alias, minute=minute)]
        totals.prompt_tokens += usage.prompt_tokens
        totals.completion_tokens += usage.completion_tokens
        totals.requests += 1

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="usage-ledger-flush")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self.flush()

    async def flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, defaultdict(UsageTotals)
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_WRITES)

        async def write(key: UsageKey, totals: UsageTotals) -> None:
            async with semaphore:
                try:
                    await self._sink.write(key, totals)
                except (BotoCoreError, ClientError) as exc:
                    metrics.USAGE_FLUSH_FAILURES.inc()
                    log.warning(
                        "usage_flush_failed",
                        tenant=key.tenant,
                        alias=key.alias,
                        minute=key.minute,
                        error=str(exc),
                    )

        await asyncio.gather(*(write(key, totals) for key, totals in batch.items()))

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval_s)
            await self.flush()
