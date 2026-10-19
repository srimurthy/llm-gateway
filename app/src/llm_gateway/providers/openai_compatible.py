"""Azure OpenAI and OpenAI-compatible servers (vLLM) through the official ``openai`` SDK.

The SDK's own retries are disabled: the router owns retry policy, by moving to the next
provider instead of hammering one that is already struggling.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from typing import Any, Final

import openai
from openai import AsyncOpenAI

from llm_gateway.config.routing import TokenParameter
from llm_gateway.core.errors import (
    ProviderError,
    ProviderRequestError,
    ProviderThrottledError,
    ProviderUnavailableError,
)
from llm_gateway.core.models import ChatChunk, ChatRequest, ChatResult, FinishReason, Usage

_FINISH_REASONS: Final[Mapping[str, FinishReason]] = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
}
_RETRYABLE_STATUS: Final = frozenset({408, 409, 429})


def map_finish_reason(reason: str | None) -> FinishReason:
    return _FINISH_REASONS.get(reason or "", FinishReason.STOP)


def map_openai_error(  # noqa: PLR0911 - one return per error class reads clearest
    provider: str, error: openai.OpenAIError
) -> ProviderError:
    if isinstance(error, openai.RateLimitError):
        return ProviderThrottledError(provider, "rate_limited")
    if isinstance(error, openai.APITimeoutError):
        return ProviderUnavailableError(provider, "timeout")
    if isinstance(error, openai.APIConnectionError):
        return ProviderUnavailableError(provider, "connection_error")
    if isinstance(
        error, openai.AuthenticationError | openai.PermissionDeniedError | openai.NotFoundError
    ):
        # Wrong key or missing deployment: a deployment mistake, not the caller's.
        return ProviderUnavailableError(provider, f"misconfigured ({error.status_code})")
    if isinstance(error, openai.APIStatusError):
        if error.status_code >= 500 or error.status_code in _RETRYABLE_STATUS:  # noqa: PLR2004
            return ProviderUnavailableError(provider, f"http_{error.status_code}")
        return ProviderRequestError(provider, error.message[:500])
    return ProviderUnavailableError(provider, type(error).__name__)


class OpenAICompatibleProvider:
    def __init__(
        self,
        name: str,
        *,
        client: AsyncOpenAI,
        model: str,
        token_parameter: TokenParameter = "max_tokens",  # noqa: S107 - a parameter name
    ) -> None:
        self._name = name
        self._client = client
        self._model = model
        self._token_parameter = token_parameter

    @property
    def name(self) -> str:
        return self._name

    def build_params(self, request: ChatRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            self._token_parameter: request.max_tokens,
        }
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.top_p is not None:
            params["top_p"] = request.top_p
        if request.stop:
            params["stop"] = list(request.stop)
        return params

    async def complete(self, request: ChatRequest) -> ChatResult:
        try:
            response = await self._client.chat.completions.create(
                **self.build_params(request), stream=False
            )
        except openai.OpenAIError as exc:
            raise map_openai_error(self._name, exc) from exc

        if not response.choices:
            raise ProviderUnavailableError(self._name, "empty_response")
        choice = response.choices[0]
        usage = (
            Usage(response.usage.prompt_tokens, response.usage.completion_tokens)
            if response.usage
            else None
        )
        return ChatResult(
            text=choice.message.content or "",
            finish_reason=map_finish_reason(choice.finish_reason),
            usage=usage,
        )

    async def stream(self, request: ChatRequest) -> AsyncGenerator[ChatChunk]:
        try:
            stream = await self._client.chat.completions.create(
                **self.build_params(request),
                stream=True,
                stream_options={"include_usage": True},
            )
            async for event in stream:
                if event.usage:
                    yield ChatChunk(
                        usage=Usage(event.usage.prompt_tokens, event.usage.completion_tokens)
                    )
                # Azure sends a first event with no choices (prompt filter results).
                for choice in event.choices[:1]:
                    text = (choice.delta.content or "") if choice.delta else ""
                    finish = (
                        map_finish_reason(choice.finish_reason) if choice.finish_reason else None
                    )
                    if text or finish:
                        yield ChatChunk(text=text, finish_reason=finish)
        except openai.OpenAIError as exc:
            raise map_openai_error(self._name, exc) from exc
