from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI

from llm_gateway.config.routing import AliasSettings, CircuitBreakerSettings, TenantPolicy
from llm_gateway.config.settings import Settings
from llm_gateway.container import Container
from llm_gateway.infrastructure.tasks import TaskSupervisor
from llm_gateway.jobs.service import JobService
from llm_gateway.main import create_app
from llm_gateway.providers.base import ChatProvider
from llm_gateway.ratelimit.token_budget import TokenBudgetLimiter
from llm_gateway.routing.circuit_breaker import CircuitBreaker
from llm_gateway.routing.router import Router, RouteTarget
from llm_gateway.services.chat import ChatService
from llm_gateway.usage.ledger import UsageLedger
from tests.fakes import (
    InMemoryJobQueue,
    InMemoryJobRepository,
    RecordingUsageSink,
    ScriptedProvider,
    StaticPolicies,
)

TENANT = "team-search"
TENANT_HEADERS = {"x-tenant-id": TENANT}


def build_router(chains: dict[str, list[ChatProvider]], *, max_output_tokens: int = 1024) -> Router:
    targets: dict[str, RouteTarget] = {}
    aliases: dict[str, AliasSettings] = {}
    for alias, providers in chains.items():
        for provider in providers:
            targets.setdefault(
                provider.name,
                RouteTarget(
                    provider=provider,
                    breaker=CircuitBreaker(
                        provider.name, CircuitBreakerSettings(failure_threshold=2)
                    ),
                ),
            )
        aliases[alias] = AliasSettings(
            chain=tuple(p.name for p in providers), max_output_tokens=max_output_tokens
        )
    return Router(aliases, targets)


@pytest.fixture
def valkey() -> FakeAsyncRedis:
    return FakeAsyncRedis()


@pytest.fixture
def policies() -> StaticPolicies:
    return StaticPolicies(
        TenantPolicy(tokens_per_minute=100_000),
        overrides={
            "team-restricted": TenantPolicy(
                tokens_per_minute=100_000, allowed_aliases=frozenset({"fast"})
            ),
            "team-tiny": TenantPolicy(tokens_per_minute=1_100),
        },
    )


@pytest.fixture
def primary() -> ScriptedProvider:
    return ScriptedProvider("primary")


@pytest.fixture
def secondary() -> ScriptedProvider:
    return ScriptedProvider("secondary")


@pytest.fixture
def router(primary: ScriptedProvider, secondary: ScriptedProvider) -> Router:
    return build_router({"fast": [primary, secondary], "smart": [secondary]})


@pytest.fixture
def usage_sink() -> RecordingUsageSink:
    return RecordingUsageSink()


@pytest.fixture
def jobs_repository() -> InMemoryJobRepository:
    return InMemoryJobRepository()


@pytest.fixture
def jobs_queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
def make_container(
    valkey: FakeAsyncRedis,
    policies: StaticPolicies,
    usage_sink: RecordingUsageSink,
    jobs_repository: InMemoryJobRepository,
    jobs_queue: InMemoryJobQueue,
) -> Callable[[Router], Container]:
    def factory(router: Router) -> Container:
        tasks = TaskSupervisor(limit=100)
        chat = ChatService(
            router=router,
            limiter=TokenBudgetLimiter(valkey, local_fallback_fraction=0.5),
            policies=policies,
            ledger=UsageLedger(usage_sink, flush_interval_s=60),
            tasks=tasks,
            region_quota_share=1.0,
        )
        return Container(
            settings=Settings(environment="local", log_format="console"),
            router=router,
            policies=policies,
            chat=chat,
            tasks=tasks,
            jobs=JobService(
                router=router, policies=policies, repository=jobs_repository, queue=jobs_queue
            ),
            job_repository=jobs_repository,
        )

    return factory


@pytest.fixture
def app(make_container: Callable[[Router], Container], router: Router) -> FastAPI:
    container = make_container(router)

    async def container_factory(_: Settings, stack: AsyncExitStack) -> Container:
        stack.push_async_callback(container.tasks.drain, 5.0)
        return container

    return create_app(
        Settings(environment="local", log_format="console"), container_factory=container_factory
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            yield client
