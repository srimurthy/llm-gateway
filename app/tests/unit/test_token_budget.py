import pytest
from fakeredis import FakeAsyncRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from llm_gateway.core.errors import RateLimitExceededError, RequestTooLargeError
from llm_gateway.ratelimit.local import LocalTokenBuckets
from llm_gateway.ratelimit.token_budget import TokenBudgetLimiter, budget_key
from tests.fakes import FakeClock


@pytest.fixture
def limiter(valkey: FakeAsyncRedis) -> TokenBudgetLimiter:
    return TokenBudgetLimiter(valkey, local_fallback_fraction=0.5)


async def test_reserves_until_budget_is_spent(limiter: TokenBudgetLimiter) -> None:
    first = await limiter.reserve(tenant="t", alias="fast", tokens=600, tokens_per_minute=1000)
    assert first.backend == "valkey"
    assert first.remaining == 400

    with pytest.raises(RateLimitExceededError) as excinfo:
        await limiter.reserve(tenant="t", alias="fast", tokens=600, tokens_per_minute=1000)

    error = excinfo.value
    assert error.status_code == 429
    assert error.headers["x-ratelimit-limit-tokens"] == "1000"
    assert int(error.headers["retry-after"]) >= 1


async def test_settle_refunds_unused_tokens(limiter: TokenBudgetLimiter) -> None:
    reservation = await limiter.reserve(
        tenant="t", alias="fast", tokens=900, tokens_per_minute=1000
    )

    await limiter.settle(reservation, consumed=100)

    again = await limiter.reserve(tenant="t", alias="fast", tokens=800, tokens_per_minute=1000)
    assert again.remaining >= 0


async def test_settle_charges_extra_when_estimate_was_low(
    limiter: TokenBudgetLimiter, valkey: FakeAsyncRedis
) -> None:
    reservation = await limiter.reserve(
        tenant="t", alias="fast", tokens=100, tokens_per_minute=1000
    )

    await limiter.settle(reservation, consumed=1100)

    stored = float(await valkey.hget(budget_key("t", "fast"), "tokens"))
    assert stored < 0, "debt carries over so the budget holds over the minute"


async def test_budgets_are_independent_per_tenant_and_alias(limiter: TokenBudgetLimiter) -> None:
    await limiter.reserve(tenant="t1", alias="fast", tokens=1000, tokens_per_minute=1000)

    await limiter.reserve(tenant="t2", alias="fast", tokens=1000, tokens_per_minute=1000)
    await limiter.reserve(tenant="t1", alias="smart", tokens=1000, tokens_per_minute=1000)


async def test_request_larger_than_budget_is_rejected_outright(limiter: TokenBudgetLimiter) -> None:
    with pytest.raises(RequestTooLargeError):
        await limiter.reserve(tenant="t", alias="fast", tokens=1001, tokens_per_minute=1000)


class BrokenValkey(FakeAsyncRedis):
    async def evalsha(self, *args: object, **kwargs: object) -> object:
        raise RedisConnectionError("down")

    async def eval(self, *args: object, **kwargs: object) -> object:
        raise RedisConnectionError("down")


async def test_falls_back_to_local_bucket_when_valkey_is_down() -> None:
    clock = FakeClock()
    limiter = TokenBudgetLimiter(
        BrokenValkey(), local_fallback_fraction=0.5, local_buckets=LocalTokenBuckets(clock=clock)
    )

    reservation = await limiter.reserve(
        tenant="t", alias="fast", tokens=400, tokens_per_minute=1000
    )
    assert reservation.backend == "local"

    with pytest.raises(RateLimitExceededError):
        await limiter.reserve(tenant="t", alias="fast", tokens=400, tokens_per_minute=1000)

    clock.advance(30)  # half a minute refills half of the 500-token local share
    await limiter.reserve(tenant="t", alias="fast", tokens=250, tokens_per_minute=1000)
