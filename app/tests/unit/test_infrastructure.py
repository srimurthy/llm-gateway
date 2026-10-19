import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import pytest

from llm_gateway.config.settings import Settings
from llm_gateway.container import build_container
from llm_gateway.infrastructure.secrets import SecretResolutionError, SecretResolver
from llm_gateway.infrastructure.tasks import TaskSupervisor

LOCAL_ROUTING = Path(__file__).parents[2] / "config" / "routing.local.yaml"


class FakeSecretsManager:
    def __init__(self, value: str | None) -> None:
        self._value = value

    async def get_secret_value(self, *, SecretId: str) -> dict[str, Any]:  # noqa: N803
        return {"SecretString": self._value} if self._value else {}


def resolver(value: str | None = "s3cr3t") -> SecretResolver:
    async def factory() -> Any:
        return FakeSecretsManager(value)

    return SecretResolver(factory)


async def test_resolves_env_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_KEY", "from-env")

    assert await resolver().resolve("env:AZURE_KEY") == "from-env"


async def test_missing_env_reference_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_KEY", raising=False)

    with pytest.raises(SecretResolutionError):
        await resolver().resolve("env:AZURE_KEY")


async def test_resolves_secrets_manager_reference() -> None:
    assert await resolver().resolve("llm-gateway/azure") == "s3cr3t"
    with pytest.raises(SecretResolutionError):
        await resolver(None).resolve("llm-gateway/azure")


async def test_supervisor_drops_work_beyond_its_limit() -> None:
    supervisor = TaskSupervisor(limit=1)
    gate = asyncio.Event()
    finished: list[str] = []

    async def job(name: str) -> None:
        await gate.wait()
        finished.append(name)

    supervisor.spawn(job("kept"), name="t")
    supervisor.spawn(job("dropped"), name="t")
    gate.set()
    await supervisor.drain(timeout_s=1)

    assert finished == ["kept"]


async def test_supervisor_survives_failing_work_and_cancels_on_timeout() -> None:
    supervisor = TaskSupervisor(limit=10)

    async def fail() -> None:
        raise RuntimeError("boom")

    async def hang() -> None:
        await asyncio.sleep(60)

    supervisor.spawn(fail(), name="fail")
    supervisor.spawn(hang(), name="hang")
    await supervisor.drain(timeout_s=0.05)
    await asyncio.sleep(0)

    assert supervisor.pending == 0


async def test_container_builds_and_closes_with_local_config() -> None:
    settings = Settings(routing_config_path=LOCAL_ROUTING, valkey_url="redis://127.0.0.1:1/0")

    async with AsyncExitStack() as stack:
        container = await build_container(settings, stack)

        assert set(container.router.aliases) == {"fast", "private"}
        assert container.jobs is None, "jobs stay off without a table and a queue"
