"""Where tenant policies come from.

Tenants are authenticated by the ingress gateway, so an unknown tenant is a real internal
team without an override row: it gets the default policy from the routing file.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from llm_gateway.config.routing import TenantPolicy

if TYPE_CHECKING:
    from types_aiobotocore_dynamodb import DynamoDBClient

log = structlog.get_logger(__name__)


class TenantPolicyStore(Protocol):
    async def get(self, tenant: str) -> TenantPolicy: ...


class StaticTenantPolicyStore:
    """Every tenant gets the default policy. Used when no tenants table is configured."""

    def __init__(self, default: TenantPolicy) -> None:
        self._default = default

    async def get(self, tenant: str) -> TenantPolicy:  # noqa: ARG002 - protocol signature
        return self._default


@dataclass(frozen=True, slots=True)
class _CachedPolicy:
    policy: TenantPolicy
    fetched_at: float


class DynamoTenantPolicyStore:
    """Policies from the tenants table, cached per pod.

    A DynamoDB failure serves the last known policy (or the default), so a policy lookup
    never takes the gateway down.
    """

    def __init__(
        self,
        client: DynamoDBClient,
        *,
        table: str,
        default: TenantPolicy,
        ttl_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._table = table
        self._default = default
        self._ttl_s = ttl_s
        self._clock = clock
        self._cache: dict[str, _CachedPolicy] = {}

    async def get(self, tenant: str) -> TenantPolicy:
        cached = self._cache.get(tenant)
        if cached and self._clock() - cached.fetched_at < self._ttl_s:
            return cached.policy

        try:
            response = await self._client.get_item(
                TableName=self._table, Key={"tenant_id": {"S": tenant}}
            )
        except (BotoCoreError, ClientError) as exc:
            log.warning("tenant_policy_lookup_failed", tenant=tenant, error=str(exc))
            return cached.policy if cached else self._default

        item = response.get("Item")
        policy = self._parse(tenant, item) if item else self._default
        self._cache[tenant] = _CachedPolicy(policy=policy, fetched_at=self._clock())
        return policy

    def _parse(self, tenant: str, item: Mapping[str, Any]) -> TenantPolicy:
        try:
            aliases = item.get("allowed_aliases", {}).get("SS")
            return TenantPolicy(
                tokens_per_minute=int(item["tokens_per_minute"]["N"]),
                allowed_aliases=frozenset(aliases) if aliases is not None else None,
            )
        except (KeyError, ValueError, ValidationError) as exc:
            log.error("tenant_policy_invalid", tenant=tenant, error=str(exc))
            return self._default
