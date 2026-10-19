from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from llm_gateway.config.routing import TenantPolicy
from llm_gateway.core.models import Usage
from llm_gateway.tenants.policies import DynamoTenantPolicyStore
from llm_gateway.usage.ledger import UsageLedger
from tests.fakes import FakeClock, RecordingUsageSink

DEFAULT = TenantPolicy(tokens_per_minute=1000)


async def test_ledger_sums_usage_per_tenant_alias_and_minute() -> None:
    sink = RecordingUsageSink()
    ledger = UsageLedger(
        sink, flush_interval_s=60, clock=lambda: datetime(2026, 10, 18, 12, 30, 15, tzinfo=UTC)
    )

    ledger.add(tenant="a", alias="fast", usage=Usage(10, 5))
    ledger.add(tenant="a", alias="fast", usage=Usage(1, 1))
    ledger.add(tenant="b", alias="fast", usage=Usage(2, 2))
    await ledger.flush()

    rows = {(key.tenant, key.minute): totals for key, totals in sink.rows}
    assert rows[("a", "2026-10-18T12:30")].prompt_tokens == 11
    assert rows[("a", "2026-10-18T12:30")].requests == 2
    assert len(sink.rows) == 2

    await ledger.flush()
    assert len(sink.rows) == 2, "a flush only writes what arrived since the last one"


class FakeDynamo:
    def __init__(self, item: dict[str, Any] | None = None, *, fail: bool = False) -> None:
        self.item = item
        self.fail = fail
        self.calls = 0

    async def get_item(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        if self.fail:
            raise ClientError({"Error": {"Code": "InternalServerError"}}, "GetItem")
        return {"Item": self.item} if self.item else {}


async def test_policy_store_reads_and_caches_override() -> None:
    dynamo = FakeDynamo(
        {
            "tenant_id": {"S": "a"},
            "tokens_per_minute": {"N": "5000"},
            "allowed_aliases": {"SS": ["fast"]},
        }
    )
    clock = FakeClock()
    store = DynamoTenantPolicyStore(dynamo, table="t", default=DEFAULT, clock=clock)  # type: ignore[arg-type]

    policy = await store.get("a")
    await store.get("a")

    assert policy.tokens_per_minute == 5000
    assert policy.allows("fast")
    assert not policy.allows("smart")
    assert dynamo.calls == 1

    clock.advance(61)
    await store.get("a")
    assert dynamo.calls == 2


async def test_policy_store_serves_last_known_policy_when_dynamodb_fails() -> None:
    dynamo = FakeDynamo({"tenant_id": {"S": "a"}, "tokens_per_minute": {"N": "5000"}})
    clock = FakeClock()
    store = DynamoTenantPolicyStore(dynamo, table="t", default=DEFAULT, clock=clock)  # type: ignore[arg-type]
    await store.get("a")

    dynamo.fail = True
    clock.advance(61)

    assert (await store.get("a")).tokens_per_minute == 5000
    assert (await store.get("unknown")).tokens_per_minute == DEFAULT.tokens_per_minute
