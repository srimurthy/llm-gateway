from collections.abc import AsyncIterator

import pytest

from llm_gateway.core.errors import (
    AliasNotFoundError,
    ProviderRequestError,
    ProvidersThrottledError,
    ProvidersUnavailableError,
    ProviderThrottledError,
    ProviderUnavailableError,
    UpstreamRejectedError,
)
from llm_gateway.core.models import ChatChunk, ChatMessage, ChatRequest, Role
from llm_gateway.routing.circuit_breaker import CircuitState
from tests.conftest import build_router
from tests.fakes import Fail, FailMidStream, ScriptedProvider, Succeed

REQUEST = ChatRequest(messages=(ChatMessage(Role.USER, "hi"),), max_tokens=16)


async def drain(chunks: AsyncIterator[ChatChunk], into: list[str] | None = None) -> None:
    async for chunk in chunks:
        if into is not None:
            into.append(chunk.text)


async def test_complete_uses_first_healthy_provider() -> None:
    primary, secondary = ScriptedProvider("a"), ScriptedProvider("b")
    router = build_router({"fast": [primary, secondary]})

    routed = await router.complete("fast", REQUEST)

    assert routed.provider == "a"
    assert not secondary.calls


async def test_complete_falls_back_on_retryable_error() -> None:
    primary = ScriptedProvider("a", Fail(ProviderThrottledError("a", "429")))
    secondary = ScriptedProvider("b", Succeed("from b"))
    router = build_router({"fast": [primary, secondary]})

    routed = await router.complete("fast", REQUEST)

    assert routed.provider == "b"
    assert routed.result.text == "from b"


async def test_complete_does_not_fall_back_when_request_is_rejected() -> None:
    primary = ScriptedProvider("a", Fail(ProviderRequestError("a", "content filtered")))
    secondary = ScriptedProvider("b")
    router = build_router({"fast": [primary, secondary]})

    with pytest.raises(UpstreamRejectedError):
        await router.complete("fast", REQUEST)
    assert not secondary.calls


async def test_all_throttled_maps_to_429() -> None:
    router = build_router(
        {
            "fast": [
                ScriptedProvider("a", Fail(ProviderThrottledError("a", "429"))),
                ScriptedProvider("b", Fail(ProviderThrottledError("b", "429"))),
            ]
        }
    )

    with pytest.raises(ProvidersThrottledError):
        await router.complete("fast", REQUEST)


async def test_mixed_failures_map_to_503() -> None:
    router = build_router(
        {
            "fast": [
                ScriptedProvider("a", Fail(ProviderThrottledError("a", "429"))),
                ScriptedProvider("b", Fail(ProviderUnavailableError("b", "timeout"))),
            ]
        }
    )

    with pytest.raises(ProvidersUnavailableError):
        await router.complete("fast", REQUEST)


async def test_open_circuit_skips_provider() -> None:
    failing = ScriptedProvider("a", Fail(ProviderUnavailableError("a", "500")))
    healthy = ScriptedProvider("b")
    router = build_router({"fast": [failing, healthy]})

    for _ in range(2):  # threshold in build_router is 2
        await router.complete("fast", REQUEST)
    calls_before = len(failing.calls)
    await router.complete("fast", REQUEST)

    assert len(failing.calls) == calls_before, "open circuit must not be called"


async def test_unknown_alias() -> None:
    router = build_router({"fast": [ScriptedProvider("a")]})

    with pytest.raises(AliasNotFoundError):
        await router.complete("nope", REQUEST)


async def test_stream_falls_back_before_first_chunk() -> None:
    primary = ScriptedProvider("a", Fail(ProviderUnavailableError("a", "503")))
    secondary = ScriptedProvider("b", Succeed("one two"))
    router = build_router({"fast": [primary, secondary]})

    routed = await router.open_stream("fast", REQUEST)
    text = "".join([chunk.text async for chunk in routed.chunks()])

    assert routed.provider == "b"
    assert text == "one two "
    assert primary.closed_streams == 1, "the failed stream must be closed"


async def test_stream_does_not_fall_back_after_first_chunk() -> None:
    primary = ScriptedProvider(
        "a", FailMidStream(["partial"], ProviderUnavailableError("a", "reset"))
    )
    secondary = ScriptedProvider("b")
    router = build_router({"fast": [primary, secondary]})

    routed = await router.open_stream("fast", REQUEST)
    received: list[str] = []
    with pytest.raises(ProviderUnavailableError):
        await drain(routed.chunks(), into=received)

    assert received == ["partial"]
    assert not secondary.calls


async def test_mid_stream_failures_count_against_the_breaker() -> None:
    error = ProviderUnavailableError("a", "reset")
    primary = ScriptedProvider("a", FailMidStream(["x"], error))
    router = build_router({"fast": [primary]})

    for _ in range(2):
        routed = await router.open_stream("fast", REQUEST)
        with pytest.raises(ProviderUnavailableError):
            await drain(routed.chunks())

    target = router._chains["fast"][0]
    assert target.breaker.state is CircuitState.OPEN
