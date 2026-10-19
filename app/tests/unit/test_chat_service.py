from collections.abc import AsyncGenerator

from fakeredis import FakeAsyncRedis

from llm_gateway.config.routing import TenantPolicy
from llm_gateway.core.models import ChatChunk, ChatMessage, ChatPrompt, Role
from llm_gateway.infrastructure.tasks import TaskSupervisor
from llm_gateway.ratelimit.token_budget import TokenBudgetLimiter, budget_key
from llm_gateway.services.chat import ChatService
from llm_gateway.usage.ledger import UsageLedger
from tests.conftest import build_router
from tests.fakes import RecordingUsageSink, ScriptedProvider, StaticPolicies, Succeed

PROMPT = ChatPrompt(messages=(ChatMessage(Role.USER, "hi"),), max_tokens=1000)
BUDGET = 100_000


def make_service(
    valkey: FakeAsyncRedis, sink: RecordingUsageSink
) -> tuple[ChatService, TaskSupervisor]:
    tasks = TaskSupervisor(limit=10)
    service = ChatService(
        router=build_router(
            {"fast": [ScriptedProvider("a", Succeed("one two three", usage=None))]}
        ),
        limiter=TokenBudgetLimiter(valkey, local_fallback_fraction=0.5),
        policies=StaticPolicies(TenantPolicy(tokens_per_minute=BUDGET)),
        ledger=UsageLedger(sink, flush_interval_s=60),
        tasks=tasks,
        region_quota_share=1.0,
    )
    return service, tasks


async def test_client_disconnect_still_settles_budget_and_records_usage(
    valkey: FakeAsyncRedis,
) -> None:
    sink = RecordingUsageSink()
    service, tasks = make_service(valkey, sink)

    stream = await service.stream(tenant="t", alias="fast", prompt=PROMPT)
    chunks = stream.chunks
    assert isinstance(chunks, AsyncGenerator)
    first: ChatChunk = await anext(chunks)
    await chunks.aclose()  # what Starlette does when the client goes away
    await tasks.drain(timeout_s=1)

    remaining = float(await valkey.hget(budget_key("t", "fast"), "tokens"))
    assert first.text == "one "
    assert remaining > BUDGET - 50, "the unused part of the 1,000-token reservation came back"


async def test_missing_provider_usage_is_settled_from_an_estimate(valkey: FakeAsyncRedis) -> None:
    sink = RecordingUsageSink()
    service, tasks = make_service(valkey, sink)

    await service.complete(tenant="t", alias="fast", prompt=PROMPT)
    await tasks.drain(timeout_s=1)

    remaining = float(await valkey.hget(budget_key("t", "fast"), "tokens"))
    assert remaining > BUDGET - 50
