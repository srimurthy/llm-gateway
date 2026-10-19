"""Valkey client construction.

Timeouts are short on purpose: the budget check is on every request's critical path, and
the limiter falls back to an in-pod bucket rather than let a slow Valkey add latency.
"""

from __future__ import annotations

from redis.asyncio import Redis
from redis.asyncio.cluster import RedisCluster
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from llm_gateway.config.settings import Settings

type ValkeyClient = Redis | RedisCluster


def create_valkey_client(settings: Settings) -> ValkeyClient:
    password = settings.valkey_password.get_secret_value() if settings.valkey_password else None
    if settings.valkey_cluster_mode:
        return RedisCluster.from_url(
            settings.valkey_url,
            password=password,
            socket_timeout=settings.valkey_timeout_s,
            socket_connect_timeout=settings.valkey_timeout_s,
            retry=Retry(NoBackoff(), retries=1),
        )
    return Redis.from_url(
        settings.valkey_url,
        password=password,
        socket_timeout=settings.valkey_timeout_s,
        socket_connect_timeout=settings.valkey_timeout_s,
        retry=Retry(NoBackoff(), retries=1),
        health_check_interval=30,
    )
