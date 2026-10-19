"""Run one chat request: authorize, reserve budget, route, settle, record usage.

The API layer and the async worker both call this service, so a job and a synchronous
request get exactly the same limits and routing.
"""

from __future__ import annotations

import math
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass

from llm_gateway.core.errors import GatewayError, InvalidRequestError, ProviderError
from llm_gateway.core.models import ChatChunk, ChatPrompt, ChatRequest, ChatResult, Usage
from llm_gateway.core.tokens import estimate_prompt_tokens, estimate_usage
from llm_gateway.infrastructure.tasks import TaskSupervisor
from llm_gateway.observability import metrics
from llm_gateway.ratelimit.token_budget import Reservation, TokenBudgetLimiter
from llm_gateway.routing.router import RoutedStream, Router
from llm_gateway.services.access import authorize_alias
from llm_gateway.tenants.policies import TenantPolicyStore
from llm_gateway.usage.ledger import UsageLedger


@dataclass(frozen=True, slots=True)
class _Admission:
    tenant: str
    alias: str
    request: ChatRequest
    prompt_estimate: int
    reservation: Reservation


@dataclass(frozen=True, slots=True)
class CompletionOutcome:
    result: ChatResult
    provider: str
    reservation: Reservation


@dataclass(frozen=True, slots=True)
class StreamOutcome:
    provider: str
    reservation: Reservation
    chunks: AsyncIterator[ChatChunk]


class ChatService:
    def __init__(
        self,
        *,
        router: Router,
        limiter: TokenBudgetLimiter,
        policies: TenantPolicyStore,
        ledger: UsageLedger,
        tasks: TaskSupervisor,
        region_quota_share: float,
    ) -> None:
        self._router = router
        self._limiter = limiter
        self._policies = policies
        self._ledger = ledger
        self._tasks = tasks
        self._region_quota_share = region_quota_share

    async def complete(self, *, tenant: str, alias: str, prompt: ChatPrompt) -> CompletionOutcome:
        admission = await self._admit(tenant, alias, prompt, mode="complete")
        try:
            routed = await self._router.complete(alias, admission.request)
        except BaseException as exc:
            self._settle(admission, consumed=0)
            _count(alias, "complete", exc)
            raise

        usage = routed.result.usage or estimate_usage(
            prompt_tokens=admission.prompt_estimate, output_text=routed.result.text
        )
        self._finish(admission, provider=routed.provider, usage=usage)
        metrics.CHAT_REQUESTS.labels(alias=alias, mode="complete", outcome="success").inc()
        return CompletionOutcome(
            result=routed.result, provider=routed.provider, reservation=admission.reservation
        )

    async def stream(self, *, tenant: str, alias: str, prompt: ChatPrompt) -> StreamOutcome:
        admission = await self._admit(tenant, alias, prompt, mode="stream")
        try:
            routed = await self._router.open_stream(alias, admission.request)
        except BaseException as exc:
            self._settle(admission, consumed=0)
            _count(alias, "stream", exc)
            raise
        return StreamOutcome(
            provider=routed.provider,
            reservation=admission.reservation,
            chunks=self._metered(admission, routed),
        )

    async def _metered(
        self, admission: _Admission, routed: RoutedStream
    ) -> AsyncGenerator[ChatChunk]:
        output: list[str] = []
        reported: Usage | None = None
        outcome = "client_disconnected"
        try:
            async for chunk in routed.chunks():
                output.append(chunk.text)
                if chunk.usage is not None:
                    reported = chunk.usage
                yield chunk
            outcome = "success"
        except ProviderError:
            outcome = "provider_interrupted"
            raise
        finally:
            # Runs on success, provider failure and client disconnect alike. Settling is
            # handed to the supervisor so it completes even if this task is cancelled.
            usage = reported or estimate_usage(
                prompt_tokens=admission.prompt_estimate, output_text="".join(output)
            )
            self._finish(admission, provider=routed.provider, usage=usage)
            metrics.CHAT_REQUESTS.labels(
                alias=admission.alias, mode="stream", outcome=outcome
            ).inc()

    async def _admit(self, tenant: str, alias: str, prompt: ChatPrompt, *, mode: str) -> _Admission:
        try:
            settings, policy = await authorize_alias(
                self._policies, self._router, tenant=tenant, alias=alias
            )
            max_tokens = prompt.max_tokens or settings.max_output_tokens
            if max_tokens > settings.max_output_tokens:
                raise InvalidRequestError(
                    f"max_tokens is {max_tokens}, but model '{alias}' allows at most "
                    f"{settings.max_output_tokens}."
                )
            request = prompt.to_request(max_tokens)
            prompt_estimate = estimate_prompt_tokens(request.messages)
            budget = max(1, math.floor(policy.tokens_per_minute * self._region_quota_share))
            reservation = await self._limiter.reserve(
                tenant=tenant,
                alias=alias,
                tokens=prompt_estimate + max_tokens,
                tokens_per_minute=budget,
            )
        except GatewayError as exc:
            _count(alias, mode, exc)
            raise
        return _Admission(
            tenant=tenant,
            alias=alias,
            request=request,
            prompt_estimate=prompt_estimate,
            reservation=reservation,
        )

    def _finish(self, admission: _Admission, *, provider: str, usage: Usage) -> None:
        self._settle(admission, consumed=usage.total_tokens)
        self._ledger.add(tenant=admission.tenant, alias=admission.alias, usage=usage)
        metrics.TOKENS.labels(alias=admission.alias, provider=provider, kind="prompt").inc(
            usage.prompt_tokens
        )
        metrics.TOKENS.labels(alias=admission.alias, provider=provider, kind="completion").inc(
            usage.completion_tokens
        )

    def _settle(self, admission: _Admission, *, consumed: int) -> None:
        self._tasks.spawn(
            self._limiter.settle(admission.reservation, consumed=consumed), name="budget-settle"
        )


def _count(alias: str, mode: str, error: BaseException) -> None:
    outcome = error.code if isinstance(error, GatewayError) else type(error).__name__
    metrics.CHAT_REQUESTS.labels(alias=alias, mode=mode, outcome=outcome).inc()
