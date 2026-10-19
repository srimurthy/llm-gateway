"""Route an alias to the first healthy provider in its chain.

Fallback rules:

* Retryable failures (throttling, 5xx, timeouts) move to the next provider.
* A non-retryable failure (the provider rejected the request content) fails the request,
  since the next provider would reject it too.
* A stream can only fall back before its first chunk. ``open_stream`` waits for that
  chunk, so the API can still answer with a proper 429 or 503 instead of a 200 that
  breaks halfway.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import structlog

from llm_gateway.config.routing import AliasSettings, RoutingConfig
from llm_gateway.core.errors import (
    AliasNotFoundError,
    GatewayError,
    ProviderError,
    ProvidersThrottledError,
    ProvidersUnavailableError,
    ProviderThrottledError,
    UpstreamRejectedError,
)
from llm_gateway.core.models import ChatChunk, ChatRequest, ChatResult
from llm_gateway.observability import metrics
from llm_gateway.providers.base import ChatProvider
from llm_gateway.routing.circuit_breaker import CircuitBreaker

log = structlog.get_logger(__name__)

THROTTLED_RETRY_AFTER_S: Final = 2
UNAVAILABLE_RETRY_AFTER_S: Final = 5


@dataclass(frozen=True, slots=True)
class RouteTarget:
    provider: ChatProvider
    breaker: CircuitBreaker


@dataclass(frozen=True, slots=True)
class RoutedResult:
    result: ChatResult
    provider: str


class RoutedStream:
    """A provider stream that has produced its first chunk. Fallback is no longer possible."""

    def __init__(
        self,
        *,
        target: RouteTarget,
        first: ChatChunk | None,
        rest: AsyncGenerator[ChatChunk],
        started: float,
    ) -> None:
        self._target = target
        self._first = first
        self._rest = rest
        self._started = started

    @property
    def provider(self) -> str:
        return self._target.provider.name

    async def chunks(self) -> AsyncGenerator[ChatChunk]:
        name = self.provider
        try:
            if self._first is not None:
                yield self._first
            async for chunk in self._rest:
                yield chunk
        except ProviderError as exc:
            metrics.PROVIDER_CALLS.labels(provider=name, outcome="interrupted").inc()
            if exc.retryable:
                self._target.breaker.record_failure()
            log.warning("provider_stream_interrupted", provider=name, error=exc.detail)
            raise
        else:
            # Success is recorded only for a complete stream. Recording it at the first
            # chunk would reset the failure count, and a provider that always breaks
            # mid-stream would never trip its breaker.
            self._target.breaker.record_success()
            metrics.PROVIDER_CALLS.labels(provider=name, outcome="success").inc()
            metrics.PROVIDER_LATENCY.labels(provider=name, mode="stream").observe(
                time.perf_counter() - self._started
            )
        finally:
            await self._rest.aclose()


class Router:
    def __init__(
        self, aliases: Mapping[str, AliasSettings], targets: Mapping[str, RouteTarget]
    ) -> None:
        self._aliases = dict(aliases)
        self._chains: dict[str, tuple[RouteTarget, ...]] = {
            alias: tuple(targets[name] for name in settings.chain)
            for alias, settings in aliases.items()
        }

    @classmethod
    def from_config(cls, config: RoutingConfig, providers: Mapping[str, ChatProvider]) -> Router:
        targets = {
            name: RouteTarget(
                provider=providers[name],
                breaker=CircuitBreaker(name, settings.circuit_breaker),
            )
            for name, settings in config.providers.items()
        }
        return cls(config.aliases, targets)

    @property
    def aliases(self) -> Mapping[str, AliasSettings]:
        return self._aliases

    def alias(self, name: str) -> AliasSettings:
        try:
            return self._aliases[name]
        except KeyError:
            raise AliasNotFoundError(name) from None

    async def complete(self, alias: str, request: ChatRequest) -> RoutedResult:
        failures: list[ProviderError] = []
        for target in self._chain(alias):
            if not self._admit(target):
                continue
            name = target.provider.name
            started = time.perf_counter()
            try:
                result = await target.provider.complete(request)
            except ProviderError as exc:
                self._handle_failure(alias, target, exc)
                failures.append(exc)
                continue
            target.breaker.record_success()
            metrics.PROVIDER_CALLS.labels(provider=name, outcome="success").inc()
            metrics.PROVIDER_LATENCY.labels(provider=name, mode="complete").observe(
                time.perf_counter() - started
            )
            return RoutedResult(result=result, provider=name)
        raise self._exhausted(alias, failures)

    async def open_stream(self, alias: str, request: ChatRequest) -> RoutedStream:
        failures: list[ProviderError] = []
        for target in self._chain(alias):
            if not self._admit(target):
                continue
            name = target.provider.name
            started = time.perf_counter()
            stream = target.provider.stream(request)
            try:
                first: ChatChunk | None = await anext(stream)
            except StopAsyncIteration:
                first = None
            except ProviderError as exc:
                await stream.aclose()
                self._handle_failure(alias, target, exc)
                failures.append(exc)
                continue
            except BaseException:
                await stream.aclose()
                raise
            metrics.TIME_TO_FIRST_TOKEN.labels(provider=name).observe(time.perf_counter() - started)
            return RoutedStream(target=target, first=first, rest=stream, started=started)
        raise self._exhausted(alias, failures)

    def _chain(self, alias: str) -> Sequence[RouteTarget]:
        try:
            return self._chains[alias]
        except KeyError:
            raise AliasNotFoundError(alias) from None

    @staticmethod
    def _admit(target: RouteTarget) -> bool:
        if target.breaker.allow_request():
            return True
        metrics.PROVIDER_CALLS.labels(provider=target.provider.name, outcome="circuit_open").inc()
        return False

    @staticmethod
    def _handle_failure(alias: str, target: RouteTarget, error: ProviderError) -> None:
        name = target.provider.name
        if not error.retryable:
            # The provider answered; the request was the problem. Its health is fine.
            target.breaker.record_success()
            metrics.PROVIDER_CALLS.labels(provider=name, outcome="rejected").inc()
            raise UpstreamRejectedError(error.detail) from error

        target.breaker.record_failure()
        outcome = "throttled" if isinstance(error, ProviderThrottledError) else "unavailable"
        metrics.PROVIDER_CALLS.labels(provider=name, outcome=outcome).inc()
        metrics.FALLBACKS.labels(alias=alias, from_provider=name).inc()
        log.warning(
            "provider_failed", alias=alias, provider=name, outcome=outcome, error=error.detail
        )

    @staticmethod
    def _exhausted(alias: str, failures: Sequence[ProviderError]) -> GatewayError:
        if failures and all(isinstance(f, ProviderThrottledError) for f in failures):
            return ProvidersThrottledError(alias, retry_after_s=THROTTLED_RETRY_AFTER_S)
        return ProvidersUnavailableError(alias, retry_after_s=UNAVAILABLE_RETRY_AFTER_S)
