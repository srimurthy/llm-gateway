"""Composition root: build every collaborator once, wire them together, tear them down.

Everything with a lifetime is registered on the ``AsyncExitStack`` the caller owns, so
shutdown runs in reverse order: background work drains before the clients it uses close.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from aiobotocore.session import get_session

from llm_gateway.config.routing import RoutingConfig
from llm_gateway.config.settings import Settings
from llm_gateway.infrastructure.aws import AwsClients
from llm_gateway.infrastructure.secrets import SecretResolver
from llm_gateway.infrastructure.tasks import TaskSupervisor
from llm_gateway.infrastructure.valkey import create_valkey_client
from llm_gateway.jobs.service import JobService
from llm_gateway.jobs.store import DynamoJobRepository, JobRepository, SqsJobQueue
from llm_gateway.providers.factory import ProviderFactory
from llm_gateway.ratelimit.token_budget import TokenBudgetLimiter
from llm_gateway.routing.router import Router
from llm_gateway.services.chat import ChatService
from llm_gateway.tenants.policies import (
    DynamoTenantPolicyStore,
    StaticTenantPolicyStore,
    TenantPolicyStore,
)
from llm_gateway.usage.ledger import DynamoUsageSink, NullUsageSink, UsageLedger, UsageSink

if TYPE_CHECKING:
    from types_aiobotocore_sqs import SQSClient

_DRAIN_TIMEOUT_S: Final = 30.0


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    router: Router
    policies: TenantPolicyStore
    chat: ChatService
    tasks: TaskSupervisor
    jobs: JobService | None = None
    job_repository: JobRepository | None = None
    sqs: SQSClient | None = None


ContainerFactory = Callable[[Settings, AsyncExitStack], Awaitable[Container]]


async def build_container(settings: Settings, stack: AsyncExitStack) -> Container:
    routing = RoutingConfig.from_yaml(settings.routing_config_path)
    aws = AwsClients(get_session(), stack, region=settings.aws_region)
    secrets = SecretResolver(aws.secrets_manager)

    providers = await ProviderFactory(stack=stack, aws=aws, secrets=secrets).build_all(routing)
    router = Router.from_config(routing, providers)

    valkey = create_valkey_client(settings)
    stack.push_async_callback(valkey.aclose)
    limiter = TokenBudgetLimiter(valkey, local_fallback_fraction=settings.local_fallback_fraction)

    policies: TenantPolicyStore = (
        DynamoTenantPolicyStore(
            await aws.dynamodb(),
            table=settings.tenants_table,
            default=routing.default_tenant_policy,
        )
        if settings.tenants_table
        else StaticTenantPolicyStore(routing.default_tenant_policy)
    )

    sink: UsageSink = (
        DynamoUsageSink(
            await aws.dynamodb(),
            table=settings.usage_table,
            region=settings.aws_region,
            retention=timedelta(days=settings.usage_retention_days),
        )
        if settings.usage_table
        else NullUsageSink()
    )
    ledger = UsageLedger(sink, flush_interval_s=settings.usage_flush_interval_s)
    ledger.start()
    stack.push_async_callback(ledger.stop)

    # Registered last so it drains first: settle tasks still need Valkey.
    tasks = TaskSupervisor(limit=settings.background_task_limit)
    stack.push_async_callback(tasks.drain, _DRAIN_TIMEOUT_S)

    chat = ChatService(
        router=router,
        limiter=limiter,
        policies=policies,
        ledger=ledger,
        tasks=tasks,
        region_quota_share=settings.region_quota_share,
    )

    if not (settings.jobs_table and settings.jobs_queue_url):
        return Container(
            settings=settings, router=router, policies=policies, chat=chat, tasks=tasks
        )

    sqs = await aws.sqs()
    repository = DynamoJobRepository(
        await aws.dynamodb(),
        table=settings.jobs_table,
        retention=timedelta(days=settings.job_retention_days),
    )
    jobs = JobService(
        router=router,
        policies=policies,
        repository=repository,
        queue=SqsJobQueue(sqs, queue_url=settings.jobs_queue_url),
    )
    return Container(
        settings=settings,
        router=router,
        policies=policies,
        chat=chat,
        tasks=tasks,
        jobs=jobs,
        job_repository=repository,
        sqs=sqs,
    )
