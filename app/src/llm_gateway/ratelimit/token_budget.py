"""Tokens-per-minute budgets per tenant and alias, enforced atomically in Valkey.

A request reserves ``estimated prompt tokens + max_tokens`` up front, then settles the
difference once the provider reports real usage. Reserving the maximum means a burst of
long requests cannot overshoot the budget while they are all still running. Settling can
push a bucket below zero (the estimate was low); later requests then wait for the debt
to refill, so the budget holds over any one-minute window.

The scripts read the clock with ``TIME`` inside Valkey, so pods with skewed clocks still
agree. Each script touches one key, which keeps it valid in cluster mode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal

import structlog
from redis.exceptions import RedisError

from llm_gateway.core.errors import RateLimitExceededError, RequestTooLargeError
from llm_gateway.infrastructure.valkey import ValkeyClient
from llm_gateway.observability import metrics
from llm_gateway.ratelimit.local import LocalTokenBuckets

log = structlog.get_logger(__name__)

_MS_PER_MINUTE: Final = 60_000
# Twice the full-refill time: after that, a bucket is full again and need not be stored.
_KEY_TTL_MS: Final = 2 * _MS_PER_MINUTE

RESERVE_SCRIPT: Final = """
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])

local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)

local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end
if now > ts then
  tokens = math.min(capacity, tokens + (now - ts) * refill_per_ms)
  ts = now
end

local allowed = 0
local retry_after_ms = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  retry_after_ms = math.ceil((requested - tokens) / refill_per_ms)
end

redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(ts))
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return {allowed, math.floor(tokens), retry_after_ms}
"""

SETTLE_SCRIPT: Final = """
local capacity = tonumber(ARGV[1])
local delta = tonumber(ARGV[2])
local ttl_ms = tonumber(ARGV[3])

local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
if tokens == nil then
  return 0
end
tokens = math.min(capacity, tokens + delta)
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens))
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return 1
"""


@dataclass(frozen=True, slots=True)
class Reservation:
    key: str
    alias: str
    capacity: int
    reserved: int
    remaining: int
    backend: Literal["valkey", "local"]


def budget_key(tenant: str, alias: str) -> str:
    return f"llmgw:tpm:{tenant}:{alias}"


class TokenBudgetLimiter:
    def __init__(
        self,
        client: ValkeyClient,
        *,
        local_fallback_fraction: float,
        local_buckets: LocalTokenBuckets | None = None,
    ) -> None:
        self._reserve_script = client.register_script(RESERVE_SCRIPT)
        self._settle_script = client.register_script(SETTLE_SCRIPT)
        self._local_fraction = local_fallback_fraction
        self._local = local_buckets or LocalTokenBuckets()

    async def reserve(
        self, *, tenant: str, alias: str, tokens: int, tokens_per_minute: int
    ) -> Reservation:
        if tokens > tokens_per_minute:
            raise RequestTooLargeError(
                f"This request needs up to {tokens} tokens, more than your budget of "
                f"{tokens_per_minute} tokens per minute. Lower max_tokens or shorten the prompt."
            )
        key = budget_key(tenant, alias)
        try:
            allowed, remaining, retry_after_ms = await self._reserve_script(
                keys=[key],
                args=[tokens_per_minute, tokens_per_minute / _MS_PER_MINUTE, tokens, _KEY_TTL_MS],
            )
        except (RedisError, OSError) as exc:
            return self._reserve_locally(
                key, alias=alias, tokens=tokens, tokens_per_minute=tokens_per_minute, error=exc
            )

        if not allowed:
            metrics.BUDGET_REJECTIONS.labels(alias=alias).inc()
            raise RateLimitExceededError(
                retry_after_s=max(1, math.ceil(int(retry_after_ms) / 1000)),
                limit=tokens_per_minute,
                remaining=int(remaining),
            )
        return Reservation(
            key=key,
            alias=alias,
            capacity=tokens_per_minute,
            reserved=tokens,
            remaining=int(remaining),
            backend="valkey",
        )

    async def settle(self, reservation: Reservation, *, consumed: int) -> None:
        """Return unused tokens to the bucket (or charge extra if the estimate was low)."""
        delta = reservation.reserved - consumed
        if delta == 0:
            return
        if reservation.backend == "local":
            self._local.adjust(
                reservation.key, capacity=self._local_capacity(reservation.capacity), delta=delta
            )
            return
        try:
            await self._settle_script(
                keys=[reservation.key], args=[reservation.capacity, delta, _KEY_TTL_MS]
            )
        except (RedisError, OSError) as exc:
            metrics.LIMITER_FALLBACKS.labels(operation="settle").inc()
            log.warning("budget_settle_failed", key=reservation.key, delta=delta, error=str(exc))

    def _reserve_locally(
        self,
        key: str,
        *,
        alias: str,
        tokens: int,
        tokens_per_minute: int,
        error: Exception,
    ) -> Reservation:
        metrics.LIMITER_FALLBACKS.labels(operation="reserve").inc()
        log.warning("budget_backend_unavailable", key=key, error=str(error))
        capacity = self._local_capacity(tokens_per_minute)
        # A pod's share can be smaller than one large request. Cap the take at the share so
        # the request can still run; settling charges the real usage afterwards.
        taken = min(tokens, math.floor(capacity))
        decision = self._local.take(key, capacity=capacity, tokens=taken)
        if not decision.allowed:
            metrics.BUDGET_REJECTIONS.labels(alias=alias).inc()
            raise RateLimitExceededError(
                retry_after_s=max(1, math.ceil(decision.retry_after_ms / 1000)),
                limit=tokens_per_minute,
                remaining=decision.remaining,
            )
        return Reservation(
            key=key,
            alias=alias,
            capacity=tokens_per_minute,
            reserved=taken,
            remaining=decision.remaining,
            backend="local",
        )

    def _local_capacity(self, tokens_per_minute: int) -> float:
        return max(1.0, tokens_per_minute * self._local_fraction)
